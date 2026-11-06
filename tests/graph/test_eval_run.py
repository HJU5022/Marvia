"""평가 실행 시험 (done 3.2). 가짜 모델·가짜 RAG로 키 없이 돈다. tests/graph 준비물(agent_deps)을 쓴다."""

from dataclasses import replace

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from marvia.eval.dataset import Item, load_set
from marvia.eval.run import (
    articles,
    behaviour,
    cost_usd,
    estimate,
    evaluate_item,
    existing_results,
    preflight,
    result_name,
    stop_reason,
)
from marvia.graph.schemas import Draft
from marvia.rag.schemas import Rewrite
from marvia.tools.rules import load_rules

TODAY = load_set().as_of
PRICES = load_rules("pricing")
CITING = Draft(
    answer="반입일부터 30일 안에 수입신고해야 해요.",
    citations=["L001556@20261002#제241조.3항"],
    next_options=[],
    forwarder_message="",
)


class ToolModel(GenericFakeChatModel):
    """정해 둔 AIMessage를 차례로 내는 가짜 모델. bind_tools는 자기를 그대로 돌려준다."""

    def bind_tools(self, tools, **kwargs):
        return self


def model(*calls: tuple[str, dict]) -> ToolModel:
    """도구 호출 한 단계(calls가 있으면) 뒤 끝내는 가짜 모델."""
    step = AIMessage(
        content="", tool_calls=[{"name": n, "args": a, "id": f"c{i}"} for i, (n, a) in enumerate(calls)]
    )
    return ToolModel(messages=iter(([step] if calls else []) + [AIMessage(content="끝")]))


def item(question: str, **fields) -> Item:
    base = {"id": "T1", "group": "related", "kind": "시험", "question": question, "behaviour": ["answer"]}
    return Item.model_validate(base | fields)


def test_agent_row_keeps_citations_evidence_tools_and_rag_log(agent_deps):
    deps = agent_deps(model=model(("search_law", {"query": "수입신고 기한"})), write=lambda prompt: CITING)
    row, raw = evaluate_item(deps, item("DEMO0001 언제까지 수입신고 해요?"), "agent", TODAY, PRICES)
    assert row["behaviour"] == "answer" and row["error"] is None
    assert row["cited"] == ["L001556@20261002#제241조.3항"]
    assert row["evidence"] == ["L001556@20261002#제241조.3항"]
    assert row["tools"] == ["search_law"]
    assert row["rag"][0] == {"step": "grade", "sufficient": True, "units": ["L001556@20261002#제241조.3항"]}
    assert row["leak"] is False  # DEMO0001은 어떤 LLM 입력에도 없다
    # [주의] 줄에는 답 글이 없다. 답 글은 raw에만 있다
    assert "반입일부터" not in str(row) and "반입일부터" in raw["draft"]
    assert raw["question"] == "[BL1] 언제까지 수입신고 해요?"


def test_planner_row_records_the_plan_and_cargo_answer(agent_deps):
    row, _ = evaluate_item(agent_deps(), item("DEMO0001 언제까지 수입신고 해요?"), "planner", TODAY, PRICES)
    assert row["behaviour"] == "answer"  # 화물을 찾아 답했다 (가짜 계획자는 바로 쓴다)
    assert row["plan"] == ["write"] and row["tools"] == []


def test_fault_cuts_search_and_ends_in_a_partial_answer(agent_deps):
    deps = agent_deps(model=model(("search_law", {"query": "검사 장소"})), write=lambda prompt: CITING)
    row, _ = evaluate_item(deps, item("검사는 어디서 받나요?", fault="search"), "agent", TODAY, PRICES)
    assert row["behaviour"] == "partial"
    assert row["failed"] == ["search_law: ConnectError"]


def test_rewrite_is_logged_as_article_numbers_without_the_query_text(agent_deps, fake_rag):
    # [왜] 11-02에 고친 질의에 질문과 관계없는 "관세법 제248조"가 끼었다. 그 조문 번호만 남는지 본다
    rag = replace(
        fake_rag(sufficient=False), rewrite=lambda prompt: Rewrite(search_query="관세법 제 248 조 수리")
    )
    deps = agent_deps(model=model(("search_law", {"query": "가산세"})), rag=rag)
    row, _ = evaluate_item(deps, item("DEMO0001 늦게 신고하면요?"), "agent", TODAY, PRICES)
    assert [e for e in row["rag"] if e["step"] == "rewrite"] == [{"step": "rewrite", "articles": ["제248조"]}]
    assert "수리" not in str(row["rag"])  # 고친 질의 글(LLM 글)은 남기지 않는다
    assert articles("시행령 제1조의4와 제 9 조") == ["제1조의4", "제9조"]


def test_ambiguous_number_is_a_choice_and_decline_is_declined(agent_deps):
    ambiguous = item("MOCK12345678TEST87654321 어디예요?")
    row, _ = evaluate_item(agent_deps(model=model()), ambiguous, "agent", TODAY, PRICES)
    assert row["behaviour"] == "choice"
    deps = agent_deps(model=model(("decline", {"reason": "날씨"})))
    row, _ = evaluate_item(deps, item("오늘 날씨 어때요?"), "agent", TODAY, PRICES)
    assert row["behaviour"] == "decline" and row["tools"] == ["decline"]


def test_every_eval_item_runs_through_both_loops_without_keys(agent_deps):
    allowed = {"answer", "guide", "choice", "partial", "decline", "unsupported"}
    for case in load_set().items:
        for loop in ("planner", "agent"):
            row, _ = evaluate_item(agent_deps(model=model()), case, loop, TODAY, PRICES)
            assert row["error"] is None and row["behaviour"] in allowed, (case.id, loop, row)
            assert row["leak"] is False, (case.id, loop)


def test_behaviour_reads_the_answer_shape():
    decline = load_rules("agent")["scope"]["decline"]
    assert behaviour({"answer": decline}, []) == "decline"
    assert behaviour({"answer": "x", "draft": {"forwarder_message": "번호를 알려 주세요"}}, []) == "guide"
    assert (
        behaviour({"answer": "x", "draft": {"citations": []}, "calc": {"deadlines": []}}, []) == "unsupported"
    )
    assert behaviour({"answer": "x"}, [{"kind": "choice"}]) == "choice"


def test_cost_and_estimate_use_the_price_table():
    assert cost_usd({"claude-haiku-5-5": {"in": 1_000_000, "out": 100_000}}, PRICES) == 0.15
    assert cost_usd({"unknown-model": {"in": 1, "out": 1}}, PRICES) is None
    plan = estimate(30, ["agent"], ["claude-haiku-5-5", "claude-sonnet-5-5"], PRICES)
    per = load_rules("eval")["estimate"]
    haiku = (per["input"] * 0.10 + per["output"] * 0.50) / 1e6 * 30
    assert plan[0] == {"loop": "agent", "model": "claude-haiku-5-5", "items": 30, "usd": round(haiku, 3)}
    assert plan[1]["usd"] > plan[0]["usd"] * 10  # Sonnet 단가가 Haiku의 20배다


def test_preflight_refuses_unpriced_models_and_over_cap_estimates():
    assert preflight(30, ["agent"], ["claude-haiku-5-5"], PRICES, 1.0) == []
    unpriced = preflight(30, ["agent"], ["claude-opus-5-5"], PRICES, 1.0)
    assert len(unpriced) == 1 and "claude-opus-5-5" in unpriced[0]
    over = preflight(30, ["planner", "agent"], ["claude-sonnet-5-5"], PRICES, 0.5)
    assert len(over) == 1 and "상한" in over[0]


def test_stop_reason_fires_on_unpriced_or_unmetered_rows():
    ok = {"cost_usd": 0.01, "real_llm_calls": 3, "tokens": {"m": {"in": 1, "out": 1}}}
    assert stop_reason(ok) is None
    assert stop_reason(ok | {"cost_usd": None}) is not None
    assert stop_reason(ok | {"tokens": {}}) is not None
    assert stop_reason({"cost_usd": 0.0, "real_llm_calls": 0, "tokens": {}}) is None  # 호출이 없던 줄


def test_existing_result_files_are_found_before_spending(tmp_path):
    assert (
        result_name("agent", "m", "ctx") == "agent-m-ctx" and result_name("planner", "m", "") == "planner-m"
    )
    assert existing_results(tmp_path, ["agent"], ["m"], "") == []
    (tmp_path / "agent-m.raw.json").write_text("[]")
    found = existing_results(tmp_path, ["planner", "agent"], ["m"], "")
    assert [f.name for f in found] == ["agent-m.raw.json"]
