"""하이브리드 검색: 벡터 검색 상위 k와 키워드 검색 상위 k를 RRF로 합친다 (설계 5.4의 2번, 2절 결정 9).

expand를 주면 하이브리드 상위 단위에서 그래프 이웃을 더한다 (설계 5.4의 3번, 계획 3b Task 4).
질의가 "법령 이름 + 제N조"로 조문을 지목하면 조문 직접 조회 결과를 후보 맨 앞에 둔다
(rules/rag.yaml search.named_article).
하지 않는 일: 리랭커·근거 채점(graph/rag.py), Neo4j 질의(graphdb.py). 그래프는 unit_id만 주고 글은 여기서
읽는다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import psycopg

from marvia.rag.index import Embed
from marvia.rag.keywords import keywords
from marvia.rag.models import Evidence
from marvia.rag.provision import ARTICLE_HINT, find_provision, named_targets
from marvia.tools.rules import load_rules

# [왜] <=>는 코사인 거리(작을수록 가깝다). 기준 날짜보다 뒤에 시행된 단위는 뺀다
VECTOR_SQL = """
SELECT unit_id FROM corpus_units WHERE effective <= %s
ORDER BY embedding <=> %s::vector LIMIT %s
"""
# [왜] websearch_to_tsquery는 따옴표 같은 기호가 섞여도 오류를 내지 않는다
# [왜] ts_rank는 질문 낱말이 많이 겹칠수록 크다
# [왜] 점수가 같으면 unit_id 순서로 둔다. 둘째 기준이 없으면 동점인 단위의 순서가 DB 안에 줄이 놓인 순서에
#      달려, 같은 코퍼스로 DB를 새로 지을 때마다 상위 k의 구성이 달라진다 (11-13 실측)
KEYWORD_SQL = """
SELECT unit_id FROM corpus_units
WHERE effective <= %s AND keywords @@ websearch_to_tsquery('simple', %s)
ORDER BY ts_rank(keywords, websearch_to_tsquery('simple', %s)) DESC, unit_id LIMIT %s
"""
# [왜] 그래프 이웃 가운데 하이브리드에 없고 기준 날짜에 시행 중인 단위만, 질의 벡터에 가까운 순서로 자른다.
#      Postgres에 없는 unit_id는 여기서 걸러져 근거가 되지 않는다(두 저장소가 어긋나도 KeyError 없음)
GRAPH_SQL = """
SELECT unit_id FROM corpus_units
WHERE unit_id = ANY(%s) AND NOT unit_id = ANY(%s) AND effective <= %s
ORDER BY embedding <=> %s::vector LIMIT %s
"""
LAW_NAMES_SQL = "SELECT DISTINCT law_name FROM corpus_units"  # 색인에 있는 법령 이름
ROWS_SQL = (
    "SELECT unit_id, law_name, heading, effective, source_url, body FROM corpus_units WHERE unit_id = ANY(%s)"
)


Expand = Callable[[list[str], str], list[str]]  # (시드 unit_id들, 질의) → 이웃 unit_id들


def rrf(rankings: list[list[str]], k: int) -> list[tuple[str, float]]:
    """여러 순위 목록을 하나로 합친다. 점수 = 목록마다 1 / (k + 순위)의 합. 점수가 큰 순서로 돌려준다."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, unit_id in enumerate(ranking, start=1):
            scores[unit_id] = scores.get(unit_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def hybrid_search(
    conn: psycopg.Connection, query: str, embed: Embed, as_of: date, expand: Expand | None = None
) -> list[Evidence]:
    """질문 하나로 근거 후보를 찾는다. score는 RRF 점수(그래프 후보는 0)다.

    DB 오류가 나면 연결을 되돌린 뒤 다시 던진다. 그래프 오류(SearchFailed)는 그대로 올라간다.
    """
    try:
        return _hybrid_search(conn, query, embed, as_of, expand)
    except psycopg.Error:
        # [왜] 오류 뒤 트랜잭션이 실패 상태로 남으면 같은 연결의 다음 검색이
        #   모두 InFailedSqlTransaction으로 죽는다
        # [주의] 읽기 전용 검색이라 되돌릴 쓰기가 없다. autocommit은 쓰기 경로
        #   (index_corpus)까지 바꾸므로 connect()에는 걸지 않는다
        conn.rollback()
        raise


def leg_search(conn: psycopg.Connection, query: str, embed: Embed, as_of: date, leg: str) -> list[Evidence]:
    """다리 하나만의 후보(leg는 "vector" 또는 "keyword"). 측정용이다 (scripts/retrieval_check.py).

    [주의] 그 다리의 순위 그대로다. RRF, 그래프 확장, 조문 직접 조회는 붙지 않는다. score는 0이다.
    """
    cfg = load_rules("rag")["search"]
    try:
        if leg == "vector":
            ids = [row[0] for row in conn.execute(VECTOR_SQL, (as_of, embed([query])[0], cfg["vector_k"]))]
        elif leg == "keyword":
            terms = " OR ".join(keywords(query))
            found = conn.execute(KEYWORD_SQL, (as_of, terms, terms, cfg["keyword_k"])) if terms else []
            ids = [row[0] for row in found]
        else:
            raise ValueError(f"모르는 다리: {leg}")
        rows = {row[0]: row for row in conn.execute(ROWS_SQL, (ids,))}
    except psycopg.Error:
        conn.rollback()  # [왜] hybrid_search와 같다: 실패한 트랜잭션을 남기지 않는다
        raise
    return [
        Evidence(
            unit_id=u,
            law_name=rows[u][1],
            heading=rows[u][2],
            effective=rows[u][3],
            source_url=rows[u][4],
            text=rows[u][5],
            score=0.0,
        )
        for u in ids
    ]


def _named_provisions(conn: psycopg.Connection, query: str, as_of: date) -> list[Evidence]:
    """질의가 지목한 조문의 단위들(origin="provision"). 지목하지 않았거나 꺼져 있으면 빈 목록."""
    cfg = load_rules("rag")["search"]["named_article"]
    # [왜] 조 번호가 없는 질의는 법령 이름 목록도 읽지 않는다. 그런 질의의 결과는 한 글자도 달라지지 않는다
    if not cfg["enabled"] or not ARTICLE_HINT.search(query):
        return []
    targets = named_targets(query, [row[0] for row in conn.execute(LAW_NAMES_SQL)])
    found: dict[str, Evidence] = {}

    def take(label: str) -> None:
        # [주의] 조회에도 검색과 같은 기준 날짜를 건다. 그 날짜에 시행 전인 단위는 오지 않는다
        for unit in find_provision(conn, label, as_of):
            if len(found) < cfg["max_units"]:
                found.setdefault(unit.unit_id, unit.model_copy(update={"origin": "provision"}))

    # [왜] 조문이 길면 상한에서 잘린다. 질의가 항까지 지목했으면 그 항의 단위를 먼저 두고, 남는 자리를
    #      같은 조문의 나머지 단위로 채운다. 그 항이 색인에 없으면 조문 단위 그대로다
    for _, paragraph in targets:  # 질의에 나온 순서
        if paragraph:
            take(paragraph)
    for article in dict.fromkeys(article for article, _ in targets):
        take(article)
    return list(found.values())


def _hybrid_search(
    conn: psycopg.Connection, query: str, embed: Embed, as_of: date, expand: Expand | None
) -> list[Evidence]:
    cfg = load_rules("rag")["search"]
    vector = embed([query])[0]  # [왜] 그래프 후보를 자를 때도 같은 질의 벡터를 쓴다(추가 API 호출 없음)
    vector_ids = [row[0] for row in conn.execute(VECTOR_SQL, (as_of, vector, cfg["vector_k"]))]
    # [왜] OR로 묶어야 낱말 하나만 맞아도 후보가 된다 (기본은 모든 낱말이 다 있어야 한다)
    terms = " OR ".join(keywords(query))
    keyword_ids = (
        [row[0] for row in conn.execute(KEYWORD_SQL, (as_of, terms, terms, cfg["keyword_k"]))]
        if terms
        else []
    )
    fused = rrf([vector_ids, keyword_ids], k=cfg["rrf_k"])
    fused_ids = [unit_id for unit_id, _ in fused]
    graph_ids: list[str] = []
    if expand is not None and fused_ids:
        g = load_rules("graph")["expand"]
        near = expand(fused_ids[: g["seeds"]], query)
        if near:
            params = (near, fused_ids, as_of, vector, g["max_candidates"])
            graph_ids = [row[0] for row in conn.execute(GRAPH_SQL, params)]
    rows = {row[0]: row for row in conn.execute(ROWS_SQL, (fused_ids + graph_ids,))}
    hits = [(unit_id, score, "hybrid") for unit_id, score in fused] + [(u, 0.0, "graph") for u in graph_ids]
    named = _named_provisions(conn, query, as_of)
    # [왜] 조회한 단위를 후보 맨 앞에 두고, 하이브리드·그래프가 찾은 같은 단위는 뺀다(한 번만 둔다).
    #      순위는 뒤에서 리랭커가 다시 매긴다 (graph/rag.py top_ranked)
    taken = {e.unit_id for e in named}
    return named + [
        Evidence(
            unit_id=unit_id,
            law_name=rows[unit_id][1],
            heading=rows[unit_id][2],
            effective=rows[unit_id][3],
            source_url=rows[unit_id][4],
            text=rows[unit_id][5],
            score=score,
            origin=origin,
        )
        for unit_id, score, origin in hits
        if unit_id not in taken
    ]
