from dataclasses import replace
from datetime import date

from marvia.graph.rag import RagDeps, build_rag_graph, top_ranked
from marvia.rag.models import Evidence
from marvia.rag.schemas import Grade, QueryAnalysis, Rewrite

START_STATE = {"question": "같은 제품을 다시 수입하면 정밀검사가 면제되나요?", "as_of": date(2026, 10, 30)}


def _evidence(label: str, text: str) -> Evidence:
    return Evidence(
        unit_id=f"LTEST@20261002#{label}",
        law_name="시험법",
        heading=f"시험법 > {label}",
        effective=date(2026, 10, 2),
        source_url="https://example.test",
        text=text,
        score=0.0,
    )


def _deps(grades: list[Grade], as_of: date | None = None, seen: dict | None = None) -> RagDeps:
    """가짜 바깥 기능. grades는 채점할 때마다 앞에서부터 하나씩 돌려준다. seen에 받은 값을 적어 둔다."""
    grades_left = iter(grades)
    seen = seen if seen is not None else {}

    def analyze(prompt: str) -> QueryAnalysis:
        seen["analyze_prompt"] = prompt
        return QueryAnalysis(question_type="문구 해석", as_of=as_of, search_query="정밀검사 면제")

    def search(query: str, when: date) -> list[Evidence]:
        seen.setdefault("search", []).append((query, when))
        return [_evidence("제1조", "보세구역에 반입한다"), _evidence("제2조", "정밀검사를 면제할 수 있다")]

    return RagDeps(
        analyze=analyze,
        search=search,
        rerank=lambda query, texts: [0.1, 0.9],  # 제2조가 더 가깝다고 점수를 준다
        grade=lambda prompt: next(grades_left),
        rewrite=lambda prompt: Rewrite(search_query="재수입 물품 정밀검사 면제 요건"),
    )


ENOUGH = Grade(sufficient=True, reason="면제 조문이 있다", missing="")
NOT_ENOUGH = Grade(sufficient=False, reason="면제 조건이 없다", missing="재수입 면제 조건 조문")


def test_enough_on_first_search_keeps_reranked_order():
    out = build_rag_graph(_deps([ENOUGH])).invoke(START_STATE)
    assert out["sufficient"] is True and out["rewrites"] == 0
    assert [e["unit_id"] for e in out["evidence"]] == ["LTEST@20261002#제2조", "LTEST@20261002#제1조"]
    assert out["evidence"][0]["score"] == 0.9  # RRF 점수 대신 리랭커 점수가 남는다


def test_rewrites_query_when_not_enough():
    seen: dict = {}
    out = build_rag_graph(_deps([NOT_ENOUGH, ENOUGH], seen=seen)).invoke(START_STATE)
    assert out["rewrites"] == 1 and out["sufficient"] is True
    assert [query for query, _ in seen["search"]] == ["정밀검사 면제", "재수입 물품 정밀검사 면제 요건"]


def test_stops_at_rewrite_limit_with_missing():
    out = build_rag_graph(_deps([NOT_ENOUGH] * 3)).invoke(START_STATE)
    assert out["rewrites"] == 2 and out["sufficient"] is False  # rules/rag.yaml의 max_rewrites
    assert out["missing"] == "재수입 면제 조건 조문"


def test_date_named_in_question_goes_to_search():
    seen: dict = {}
    build_rag_graph(_deps([ENOUGH], as_of=date(2024, 1, 1), seen=seen)).invoke(START_STATE)
    assert seen["search"][0][1] == date(2024, 1, 1)


def test_question_is_wrapped_as_data_in_prompt():
    seen: dict = {}
    build_rag_graph(_deps([ENOUGH], seen=seen)).invoke(START_STATE)
    assert f"<question>\n{START_STATE['question']}\n</question>" in seen["analyze_prompt"]
    assert "Today is 2026-10-30." in seen["analyze_prompt"]


def test_max_rewrites_override_replaces_the_rule_value():
    out = build_rag_graph(_deps([NOT_ENOUGH] * 3), max_rewrites=1).invoke(START_STATE)
    assert out["rewrites"] == 1 and out["sufficient"] is False


def test_top_ranked_sorts_by_the_reranker_and_keeps_the_top_n():
    many = [_evidence(f"제{i}조", f"글 {i}") for i in range(1, 11)]
    scores = lambda query, texts: [float(i) for i in range(len(texts))]  # noqa: E731
    found = top_ranked(lambda query, when: many, scores, "질의", date(2026, 10, 30))
    assert [e.unit_id for e in found] == [
        f"LTEST@20261002#제{i}조" for i in range(10, 2, -1)
    ]  # rerank_top_n 8
    assert found[0].score == 9.0


def test_ranked_dep_replaces_search_and_rerank():
    # [왜] MCP 길(계획 3b Task 8)은 검색·리랭커를 서버가 하고 RAG는 결과만 받는다
    seen: dict = {}
    deps = replace(
        _deps([ENOUGH], seen=seen), ranked=lambda query, when: [_evidence("제9조", "MCP가 준 근거")]
    )
    out = build_rag_graph(deps).invoke(START_STATE)
    assert [e["unit_id"] for e in out["evidence"]] == ["LTEST@20261002#제9조"]
    assert "search" not in seen


def test_a_long_query_still_goes_through_the_mcp_server():
    # [왜] 질의 분석 LLM이 쓴 질의가 MCP 서버의 글자 수 상한(rules/rag.yaml mcp.max_query)을 넘으면
    #      서버가 거절해 검색 전체가 실패했다. 서버로 보내기 전에 상한까지 자른다 (계획 3b에서 넘어온 일)
    from marvia.rag.mcp import MAX_QUERY, build_server, mcp_ranked

    seen: list[str] = []

    def ranked(query: str, when: date) -> list[Evidence]:
        seen.append(query)
        return [_evidence("제2조", "정밀검사를 면제할 수 있다")]

    long = QueryAnalysis(question_type="문구 해석", as_of=None, search_query="정밀검사 면제 " * 60)
    deps = replace(_deps([ENOUGH]), analyze=lambda prompt: long, ranked=mcp_ranked(build_server(ranked)))
    out = build_rag_graph(deps).invoke(START_STATE)
    assert [e["unit_id"] for e in out["evidence"]] == ["LTEST@20261002#제2조"]
    assert len(seen[0]) == MAX_QUERY


def test_a_long_query_is_cut_on_the_direct_path_too():
    # [왜] 두 길(direct, mcp)이 같은 질의를 쓴다. direct 길의 search가 받는 질의도 상한까지 잘려야 한다
    from marvia.rag.mcp import MAX_QUERY

    seen: dict = {}
    long = QueryAnalysis(question_type="문구 해석", as_of=None, search_query="정밀검사 면제 " * 60)
    deps = replace(_deps([ENOUGH], seen=seen), analyze=lambda prompt: long)
    build_rag_graph(deps).invoke(START_STATE)
    assert len(seen["search"][0][0]) == MAX_QUERY
