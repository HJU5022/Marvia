"""하이브리드 검색: 벡터 검색 상위 k와 키워드 검색 상위 k를 RRF로 합친다 (설계 5.4의 2번, 2절 결정 9).

하지 않는 일: 리랭커·근거 채점(graph/rag.py), GraphRAG(계획 3).
"""

from __future__ import annotations

from datetime import date

import psycopg

from marvia.rag.index import Embed
from marvia.rag.keywords import keywords
from marvia.rag.models import Evidence
from marvia.tools.rules import load_rules

# [왜] <=>는 코사인 거리(작을수록 가깝다). 기준 날짜보다 뒤에 시행된 단위는 뺀다
VECTOR_SQL = """
SELECT unit_id FROM corpus_units WHERE effective <= %s
ORDER BY embedding <=> %s::vector LIMIT %s
"""
# [왜] websearch_to_tsquery는 따옴표 같은 기호가 섞여도 오류를 내지 않는다
# [왜] ts_rank는 질문 낱말이 많이 겹칠수록 크다
KEYWORD_SQL = """
SELECT unit_id FROM corpus_units
WHERE effective <= %s AND keywords @@ websearch_to_tsquery('simple', %s)
ORDER BY ts_rank(keywords, websearch_to_tsquery('simple', %s)) DESC LIMIT %s
"""
ROWS_SQL = (
    "SELECT unit_id, law_name, heading, effective, source_url, body FROM corpus_units WHERE unit_id = ANY(%s)"
)


def rrf(rankings: list[list[str]], k: int) -> list[tuple[str, float]]:
    """여러 순위 목록을 하나로 합친다. 점수 = 목록마다 1 / (k + 순위)의 합. 점수가 큰 순서로 돌려준다."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, unit_id in enumerate(ranking, start=1):
            scores[unit_id] = scores.get(unit_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def hybrid_search(conn: psycopg.Connection, query: str, embed: Embed, as_of: date) -> list[Evidence]:
    """질문 하나로 근거 후보를 찾는다. score는 RRF 점수다. DB 오류가 나면 연결을 되돌린 뒤 다시 던진다."""
    try:
        return _hybrid_search(conn, query, embed, as_of)
    except psycopg.Error:
        # [왜] 오류 뒤 트랜잭션이 실패 상태로 남으면 같은 연결의 다음 검색이
        #   모두 InFailedSqlTransaction으로 죽는다
        # [주의] 읽기 전용 검색이라 되돌릴 쓰기가 없다. autocommit은 쓰기 경로
        #   (index_corpus)까지 바꾸므로 connect()에는 걸지 않는다
        conn.rollback()
        raise


def _hybrid_search(conn: psycopg.Connection, query: str, embed: Embed, as_of: date) -> list[Evidence]:
    cfg = load_rules("rag")["search"]
    vector_ids = [row[0] for row in conn.execute(VECTOR_SQL, (as_of, embed([query])[0], cfg["vector_k"]))]
    # [왜] OR로 묶어야 낱말 하나만 맞아도 후보가 된다 (기본은 모든 낱말이 다 있어야 한다)
    terms = " OR ".join(keywords(query))
    keyword_ids = (
        [row[0] for row in conn.execute(KEYWORD_SQL, (as_of, terms, terms, cfg["keyword_k"]))]
        if terms
        else []
    )
    fused = rrf([vector_ids, keyword_ids], k=cfg["rrf_k"])
    rows = {row[0]: row for row in conn.execute(ROWS_SQL, ([unit_id for unit_id, _ in fused],))}
    return [
        Evidence(
            unit_id=unit_id,
            law_name=rows[unit_id][1],
            heading=rows[unit_id][2],
            effective=rows[unit_id][3],
            source_url=rows[unit_id][4],
            text=rows[unit_id][5],
            score=score,
        )
        for unit_id, score in fused
    ]
