"""평가 실행 시험 (done 3.2). 가짜 모델·가짜 RAG로 키 없이 돈다. tests/graph 준비물(agent_deps)을 쓴다."""

import json
from dataclasses import replace
from pathlib import Path

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage

from marvia.eval.dataset import Item, load_set
from marvia.eval.run import (
    LlmWatch,
    articles,
    behaviour,
    cost_usd,
    estimate,
    eval_deps,
    evaluate_item,
    existing_results,
    inside_repo,
    observe,
    preflight,
    ragas_contexts,
    result_name,
    save_result,
    stop_reason,
)
from marvia.graph.schemas import Draft
from marvia.rag.models import Evidence
from marvia.rag.schemas import Grade, Rewrite
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
    assert row["real_llm_calls"] >= 1
    assert row["cited"] == ["L001556@20261002#제241조.3항"]
    assert row["evidence"] == ["L001556@20261002#제241조.3항"]
    assert row["tools"] == ["search_law"]
    assert row["rag"][0] == {"step": "grade", "sufficient": True, "units": ["L001556@20261002#제241조.3항"]}
    assert row["leak"] is False  # DEMO0001은 어떤 LLM 입력에도 없다
    # [주의] 줄에는 답 글이 없다. 답 글은 raw에만 있다
    assert "반입일부터" not in str(row) and "반입일부터" in raw["draft"]
    assert raw["question"] == "[BL1] 언제까지 수입신고 해요?"
    # [왜] ragas 충실도는 답이 인용한 조문과 작성자가 본 계산·화물 줄로, 정밀도·재현율은 RAG 순위로 잰다
    assert len(raw["cited_texts"]) == 1 and "반입일부터" in raw["cited_texts"][0]
    assert raw["ranked_texts"] == raw["cited_texts"]
    assert any(line.startswith("[BL1]:") for line in raw["calc_lines"])
    assert "DEMO0001" not in str(raw["calc_lines"])  # 가린 글만


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


def test_retrieved_is_the_rag_order_and_leaves_out_get_provision(agent_deps):
    # [왜] get_provision 근거는 evidence에는 들지만 검색 순위(retrieved)에는 들지 않는다
    deps = agent_deps(
        model=model(("get_provision", {"label": "관세법 제241조제3항"})), write=lambda prompt: CITING
    )
    row, _ = evaluate_item(deps, item("검사는 어디서 받나요?"), "agent", TODAY, PRICES)
    assert row["tools"] == ["get_provision"]
    assert row["evidence"] == ["L001556@20261002#제241조.3항"] and row["retrieved"] == []
    deps = agent_deps(model=model(("search_law", {"query": "수입신고 기한"})), write=lambda prompt: CITING)
    row, _ = evaluate_item(deps, item("언제까지 수입신고 해요?"), "agent", TODAY, PRICES)
    assert row["retrieved"] == ["L001556@20261002#제241조.3항"]


def test_leak_flag_turns_true_when_an_llm_input_holds_a_real_number():
    # [왜] "leaks 0"은 합격 기준이다. 표시가 켜질 수 있다는 것을 양성 대조로 본다
    watch = LlmWatch()
    watch.on_chat_model_start({}, [[HumanMessage("DEMO0001 어디예요?")]])
    values = {"mask_map": {"[BL1]": "DEMO0001"}}
    assert observe(values, [], watch, "agent", [])["leak"] is True
    assert observe({"mask_map": {"[BL1]": "DEMO0002"}}, [], watch, "agent", [])["leak"] is False
    assert watch.calls == 1


def test_out_folder_inside_the_repo_is_refused(tmp_path):
    assert inside_repo(Path("eval/results")) and inside_repo(Path.cwd() / "x")
    assert not inside_repo(tmp_path)


def test_save_result_rewrites_both_files_each_time(tmp_path):
    # [왜] 문항이 끝날 때마다 쓴다. 중간에 멈춰도 돈을 낸 줄이 남고, 파일 모양은 report가 읽는 그대로다
    save_result(
        tmp_path, "agent-m", {"loop": "agent"}, {"n": 1}, [{"id": "R1"}], [{"id": "R1", "draft": "x"}]
    )
    save_result(tmp_path, "agent-m", {"loop": "agent"}, {"n": 2}, [{"id": "R1"}, {"id": "R2"}], [])
    result = json.loads((tmp_path / "agent-m.json").read_text(encoding="utf-8"))
    assert result["rows"] == [{"id": "R1"}, {"id": "R2"}] and result["summary"] == {"n": 2}
    assert result["meta"] == {"loop": "agent"}
    assert (tmp_path / "agent-m.raw.json").exists()


def test_eval_run_binds_a_watch_stub_so_the_never_check_can_fire(agent_deps):
    # [왜] watch가 없으면 watch_cargo가 도구로 묶이지 않아, 감시 등록을 막는 궤적 검사가 걸릴 수 없다
    deps = eval_deps(agent_deps(), item("DEMO0001 지켜봐 줘"), TODAY, [])
    assert deps.watch is not None
    deps.watch.add("u", "DEMO0001", "")  # 가짜라 DB 없이 돈다
    assert deps.watch.news("u") == []


def test_error_row_still_reports_a_real_number_that_reached_an_llm_input(agent_deps, monkeypatch):
    # [왜] 실행이 중간에 죽어도 그 전에 LLM 입력에 실제 번호가 갔으면 새는 번호로 센다 (R-063)
    def dying(graph, it, thread, callbacks):
        callbacks[0].inputs.append("질문 DEMO0001 언제까지")
        raise RuntimeError("죽음")

    monkeypatch.setattr("marvia.eval.run.drive", dying)
    row, _ = evaluate_item(
        agent_deps(model=model()), item("DEMO0001 언제까지 수입신고 해요?"), "agent", TODAY, PRICES
    )
    assert row["error"] == "RuntimeError" and row["leak"] is True


def test_eval_run_has_no_outside_lookup(agent_deps):
    # [왜] 색인 밖 문항은 "바깥 조회 없음"을 전제한다. 평가 결과가 바깥 사이트에 기대면 안 된다
    from dataclasses import replace

    import httpx

    live = replace(agent_deps(), web=httpx.Client())
    deps = eval_deps(live, item("식물방역법은 언제부터예요?"), TODAY, [])
    assert deps.web is None
    from marvia.graph.tools import make_tools

    def bound(d):  # main.py가 도구를 묶는 부름과 같다
        return {t.name for t in make_tools(None, d.today, d.provision, d.model, d.web, d.watch)}

    assert "official_lookup" in bound(live)  # 대조: 바깥 조회가 있으면 묶인다
    assert "official_lookup" not in bound(deps)


def test_row_records_how_many_cargos_were_found_and_their_stage_names_but_no_number():
    cargos = [
        {"token": "[BL1]", "facts": {"stage": "반입신고", "stage_at": None}, "error": None},
        {"token": "[BL2]", "facts": None, "error": {"message": "x", "code": "e"}},
    ]
    row = observe({"cargos": cargos, "mask_map": {"[BL1]": "DEMO0001"}}, [], LlmWatch(), "agent", [])
    assert row["cargo_count"] == 2 and row["stages"] == ["반입신고"]
    assert "DEMO0001" not in str(row["stages"])
    assert observe({}, [], LlmWatch(), "agent", [])["cargo_count"] == 0


def unit(n: int, score: float = 0.5):
    return Evidence(
        unit_id=f"L001556@20261002#제{n}조",
        law_name="관세법",
        heading=f"관세법 > 제{n}조",
        effective=TODAY,
        source_url="https://www.law.go.kr/test",
        text=f"제{n}조 본문",
        score=score,
    )


def test_ranked_texts_keep_the_first_attempts_units_that_a_rewrite_replaced(agent_deps, fake_rag):
    # [왜] RAG는 시도마다 근거를 갈아 끼운다. 첫 시도의 상위 근거도 정밀도·재현율 맥락이다 (I-2)
    calls = []

    def search(query, as_of):
        calls.append(query)
        return [unit(1), unit(2), unit(3)] if len(calls) == 1 else [unit(4)]

    verdicts = iter([False, True])
    rag = replace(
        fake_rag(),
        search=search,
        # 재순위 점수: 2번 > 3번 > 1번 (검색이 준 순서와 다르다)
        rerank=lambda query, texts: [0.1, 0.9, 0.5] if len(texts) == 3 else [0.8],
        grade=lambda prompt: Grade(sufficient=next(verdicts), reason="시험", missing="x"),
    )
    deps = agent_deps(model=model(("search_law", {"query": "q"})), rag=rag, write=lambda prompt: CITING)
    row, raw = evaluate_item(deps, item("DEMO0001 q"), "agent", TODAY, PRICES)
    assert row["retrieved"] == [unit(n).unit_id for n in (2, 3, 1, 4)]
    assert [e for e in row["evidence"]] == [unit(4).unit_id]  # 최종 근거는 둘째 시도의 것뿐이다
    assert raw["ranked_texts"] == ["제2조 본문", "제3조 본문", "제1조 본문", "제4조 본문"]
    assert "제2조 본문" not in str(row)  # 줄(커밋되는 것)에는 글이 없다


def test_ragas_contexts_follow_retrieved_order_and_cut_at_top():
    seen = {unit(n).unit_id: f"제{n}조 본문" for n in (1, 2, 3, 4)}
    row = {"retrieved": [unit(n).unit_id for n in (3, 1, 4, 2)], "cited": []}
    got = ragas_contexts({"evidence": []}, row, 2, seen)
    assert got["ranked_texts"] == ["제3조 본문", "제1조 본문"]
