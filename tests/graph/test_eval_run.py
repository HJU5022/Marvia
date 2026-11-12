"""평가 실행 시험 (done 3.2). 가짜 모델·가짜 RAG로 키 없이 돈다. tests/graph 준비물(agent_deps)을 쓴다."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from marvia.cli_model import ClaudeCLIChat
from marvia.eval.dataset import Item, load_set
from marvia.eval.run import (
    Contract,
    LlmWatch,
    articles,
    behaviour,
    cost_usd,
    estimate,
    eval_deps,
    evaluate_item,
    existing_results,
    graph_setting_problem,
    halt_reason,
    inside_repo,
    llm_meta,
    masked_queries,
    observe,
    preflight,
    ragas_contexts,
    result_name,
    run_problems,
    save_result,
    stop_reason,
)
from marvia.graph.answer import NOT_FOUND_LEAD
from marvia.graph.schemas import Draft
from marvia.llm import CLIFailed, LLMFailed
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
    # [왜] 계획 3b부터 rag 기록에 검색 단계({"step": "search", "graph": n})도 있다. 채점 단계만 본다
    grades = [e for e in row["rag"] if e["step"] == "grade"]
    assert grades[0] == {"step": "grade", "sufficient": True, "units": ["L001556@20261002#제241조.3항"]}
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
    cited = {"citations": ["U1"]}
    assert behaviour({"answer": f"{NOT_FOUND_LEAD}\n\n근거", "draft": cited}, []) == "not_found"
    assert behaviour({"answer": "근거만 있는 답", "draft": cited}, []) == "answer"


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


def test_an_error_row_whose_number_never_reached_an_llm_input_does_not_leak(agent_deps, monkeypatch):
    # [왜] 음성 대조: 죽었어도 실제 번호가 LLM 입력에 간 적이 없으면 새는 번호가 아니다
    def dying(graph, it, thread, callbacks):
        callbacks[0].inputs.append("질문 [BL1] 언제까지")
        raise RuntimeError("죽음")

    monkeypatch.setattr("marvia.eval.run.drive", dying)
    row, _ = evaluate_item(
        agent_deps(model=model()), item("DEMO0001 언제까지 수입신고 해요?"), "agent", TODAY, PRICES
    )
    assert row["error"] == "RuntimeError" and row["leak"] is False


def test_error_row_reads_the_checkpoints_mask_map_for_numbers_masked_after_the_question(
    agent_deps, monkeypatch
):
    # [왜] 질문에서 읽은 번호가 아니라 그래프 노드가 가린 번호도 새는 번호로 센다. 질문 번호 경로는 막아 둔다
    class Boom(ToolModel):
        def _generate(self, *args, **kwargs):
            raise RuntimeError("죽음")

    seen_real = []

    def start(self, serialized, messages, **kwargs):
        self.calls += 1
        self.inputs.append(str(messages) + " DEMO0001")  # 실제 번호가 LLM 입력에 간 것을 흉내 낸다
        seen_real.append(True)

    monkeypatch.setattr(LlmWatch, "on_chat_model_start", start)
    monkeypatch.setattr("marvia.eval.run.mask_text", lambda text: (text, {}))  # 질문 번호 경로를 끈다
    deps = agent_deps(model=Boom(messages=iter([])))
    row, _ = evaluate_item(deps, item("DEMO0001 언제까지 수입신고 해요?"), "agent", TODAY, PRICES)
    assert seen_real and row["error"] == "RuntimeError" and row["leak"] is True


def test_observe_keeps_citations_of_a_not_found_row():
    # [왜] wrong_evidence와 정답 근거 인용률이 이 인용을 봐야 한다 (ragas는 answer·guide 줄만 채점한다)
    values = {"answer": f"{NOT_FOUND_LEAD}\n\n근거", "draft": {"citations": ["U1"]}}
    row = observe(values, [], LlmWatch(), "agent", [])
    assert row["behaviour"] == "not_found" and row["cited"] == ["U1"]


def test_behaviour_base_is_the_v1_classification_without_the_not_found_rule():
    lead = f"{NOT_FOUND_LEAD}\n\n근거"
    cited = {"answer": lead, "draft": {"citations": ["U1"]}}
    bare = {"answer": lead, "draft": {"citations": []}}
    for values, new, base in ((cited, "not_found", "answer"), (bare, "not_found", "unsupported")):
        row = observe(values, [], LlmWatch(), "agent", [])
        assert (row["behaviour"], row["behaviour_base"]) == (new, base)
    plain = observe({"answer": "x", "draft": {"citations": ["U1"]}}, [], LlmWatch(), "agent", [])
    assert plain["behaviour_base"] == plain["behaviour"] == "answer"
    assert behaviour(cited, [], not_found=False) == "answer"


def test_graph_candidates_are_counted_per_item(agent_deps, fake_rag):
    # [왜] "그래프 켬" 실행이 실제로 그래프 후보를 받았는지 줄에 남긴다 (계획 3b 사전 부검 F1)
    found = [
        unit(1),
        unit(2).model_copy(update={"origin": "graph"}),
        unit(3).model_copy(update={"origin": "graph"}),
    ]
    rag = replace(
        fake_rag(), search=lambda query, as_of: found, rerank=lambda query, texts: [0.5] * len(texts)
    )
    deps = agent_deps(model=model(("search_law", {"query": "q"})), rag=rag, write=lambda prompt: CITING)
    row, _ = evaluate_item(deps, item("DEMO0001 q"), "agent", TODAY, PRICES)
    assert row["graph_added"] == 2


def test_run_problems_reject_runs_that_did_not_measure_what_they_claim():
    clean = {"errors": 0, "leaks": 0, "cap_breaches": 0}
    rows = [
        {"id": "R07", "failed": ["agent: LLM 호출 한도(20회)에 닿았어요"], "graph_added": 0},
        {"id": "B02", "failed": ["search_law: ConnectError"], "graph_added": 0},  # 일부러 끊은 문항
    ]
    off = {"annex_units": 75, "graph": "off", "unipass_mode": "replay"}
    assert run_problems(off, rows, clean, {"B02"}) == []
    on = off | {
        "graph": "on",
        "graph_meta": {"sha": "a", "items_sha": "i", "refers": 5},
        "units_sha256": "a",
        "items_sha256": "i",
        "refers_expected": 5,
    }
    assert run_problems(on, rows, clean, {"B02"}) == ["그래프 켬인데 그래프가 더한 후보가 0이다"]
    graph_on = [rows[0] | {"graph_added": 3}]
    stale = on | {"units_sha256": "b"}
    assert run_problems(stale, graph_on, clean, set()) == [
        "그래프가 지금 단위 파일로 만든 것이 아니다 (sha 다름)"
    ]
    # [왜] 단위 파일이 같아도 품목 파일이나 간선을 만드는 코드가 바뀌면 그래프는 지금 결과가 아니다
    assert run_problems(on | {"items_sha256": "j"}, graph_on, clean, set()) == [
        "그래프가 지금 품목 파일로 만든 것이 아니다 (items.yaml sha 다름)"
    ]
    assert run_problems(on | {"refers_expected": 6}, graph_on, clean, set()) == [
        "그래프 참조 간선 수가 지금 코드 결과와 다르다 (그래프 5, 코드 6)"
    ]
    old_graph = on | {
        "graph_meta": {"sha": "a"}
    }  # 품목 sha·간선 수를 안 남긴 옛 적재도 지금 결과로 볼 수 없다
    assert len(run_problems(old_graph, graph_on, clean, set())) == 2
    broken = [{"id": "R01", "failed": ["search_law: graph_unavailable"]}]
    assert run_problems(
        {"annex_units": 0, "unipass_mode": "replay"}, broken, clean | {"leaks": 1}, set()
    ) == [
        "DB에 별표 단위가 없다 (scripts/index_corpus.py)",
        "leaks 1",
        "검색 길이 실패한 문항: R01",
    ]


def test_run_problems_flag_runs_that_did_not_cover_the_whole_set():
    # [왜] 상한에서 끊겼거나 --ids·--limit로 일부만 돈 실행은 세지 않는다 (metrics.gate_uncovered와 같은 규칙)
    clean = {"errors": 0, "leaks": 0, "cap_breaches": 0}
    meta = {"annex_units": 75, "graph": "off", "unipass_mode": "replay"}
    assert run_problems(meta, [], clean, set(), uncovered=[]) == []
    assert run_problems(meta, [], clean, set(), uncovered=["빠짐: R02", "빠짐: R03"]) == [
        "평가셋 문항을 다 덮지 못했다: 빠짐: R02, 빠짐: R03"
    ]


def test_graph_setting_problem_stops_a_run_whose_real_setting_differs_from_the_requested_one():
    assert graph_setting_problem("on", "on") is None
    assert graph_setting_problem("on", "off") == "--graph on인데 실제 설정(MARVIA_GRAPH)은 off다"


def test_run_problems_treat_a_missing_or_live_unipass_mode_as_invalid():
    # [왜] 모드 칸이 없으면 실제 API를 불렀는지 알 수 없다. 재생으로 보지 않는다 (계획 3b Task 6 검토 M-2)
    clean = {"errors": 0, "leaks": 0, "cap_breaches": 0}
    base = {"annex_units": 75, "graph": "off"}
    expect = ["UNI-PASS 재생 모드가 아니다 (meta.unipass_mode)"]
    assert run_problems(base, [], clean, set()) == expect
    assert run_problems(base | {"unipass_mode": "live"}, [], clean, set()) == expect
    assert run_problems(base | {"unipass_mode": "replay"}, [], clean, set()) == []


def test_evaluate_item_runs_the_graph_with_the_tracer_callbacks(agent_deps):
    # [왜] 평가도 서버·CLI와 같은 트레이서 콜백(trace.tracer_callbacks)을 받는다 (계획 6b)
    class Seen(BaseCallbackHandler):
        def __init__(self):
            self.chains = 0

        def on_chain_start(self, serialized, inputs, **kwargs):
            self.chains += 1

    seen = Seen()
    evaluate_item(
        agent_deps(), item("DEMO0001 언제까지 수입신고 해요?"), "planner", TODAY, PRICES, callbacks=[seen]
    )
    assert seen.chains > 0


class LimitModel(ToolModel):
    """부르면 `claude -p` 실패(사용량 한도 등)를 내는 가짜 모델."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise CLIFailed("CLI(success,429)")


def test_a_cli_failure_makes_the_item_an_error_not_a_quiet_partial_answer(agent_deps):
    # [왜] 그래프는 모델 실패를 부분 답으로 바꾼다. 사용량 한도로 끊긴 문항이 행동 점수에 섞이면 안 된다
    deps = agent_deps(model=LimitModel(messages=iter([])))
    row, _ = evaluate_item(deps, item("수입신고 기한은요?"), "agent", TODAY, PRICES, llm_via="cli")
    assert row["behaviour"] == "partial" and row["error"] == "CLIFailed: CLI(success,429)"
    ok, _ = evaluate_item(agent_deps(model=model()), item("수입신고 기한은요?"), "agent", TODAY, PRICES)
    assert ok["error"] is None


def test_cli_rows_carry_the_path_and_no_cost(agent_deps):
    deps = agent_deps(model=model(("search_law", {"query": "수입신고 기한"})), write=lambda prompt: CITING)
    api, _ = evaluate_item(deps, item("수입신고 기한은요?"), "agent", TODAY, PRICES)
    assert api["llm_via"] == "api" and api["cost_usd"] is not None
    deps = agent_deps(model=model(("search_law", {"query": "수입신고 기한"})), write=lambda prompt: CITING)
    cli, _ = evaluate_item(deps, item("수입신고 기한은요?"), "agent", TODAY, PRICES, llm_via="cli")
    # [왜] 구독으로 부른 호출은 청구액이 없다. 단가로 환산한 값을 비용으로 남기지 않는다
    assert cli["llm_via"] == "cli" and cli["cost_usd"] is None
    # 비용이 없어도 cli 줄은 실행을 멈추지 않는다. 호출은 있는데 토큰이 없으면 멈춘다
    counted = {"llm_via": "cli", "cost_usd": None, "real_llm_calls": 3, "tokens": {"m": {"in": 1, "out": 1}}}
    assert stop_reason(counted) is None
    assert stop_reason(counted | {"tokens": {}}) is not None


def test_run_meta_names_the_llm_path_and_the_cli_version(monkeypatch):
    class Done:
        stdout = "2.1.322 (Claude Code)\n"

    monkeypatch.setattr("marvia.cli_model.subprocess.run", lambda *args, **kwargs: Done())
    assert llm_meta("cli") == {"llm_via": "cli", "llm_cli": "2.1.322 (Claude Code)"}
    assert llm_meta("api") == {"llm_via": "api", "llm_cli": None}


def test_row_counts_tool_calls_by_name(agent_deps):
    calls = (("search_law", {"query": "수입신고 기한"}), ("search_law", {"query": "가산세"}))
    deps = agent_deps(model=model(*calls), write=lambda prompt: CITING)
    row, _ = evaluate_item(deps, item("DEMO0001 언제까지 수입신고 해요?"), "agent", TODAY, PRICES)
    assert row["tool_counts"] == {"search_law": 2}
    quiet, _ = evaluate_item(agent_deps(model=model()), item("수입신고 기한은요?"), "agent", TODAY, PRICES)
    assert quiet["tool_counts"] == {}


BAD = Draft(
    answer="기한이 있어요.", citations=["L999999@20260101#제1조"], next_options=[], forwarder_message=""
)
PASSING = Draft(answer="화물 상태를 확인했어요.", citations=[], next_options=[], forwarder_message="")


def test_row_keeps_write_attempts_verification_rule_names_and_the_stop_reason(agent_deps):
    drafts = iter([BAD, PASSING])
    row, _ = evaluate_item(
        agent_deps(write=lambda prompt: next(drafts)), item("DEMO0001 어디예요?"), "planner", TODAY, PRICES
    )
    # [왜] 검증에 걸렸다가 다시 써서 통과한 문항도 걸린 규칙이 남아야 출력 계약을 몇 번 어겼는지 셀 수 있다
    assert row["write_attempts"] == 2 and row["verification"] == ["근거 묶음에 없는 인용"]
    assert row["verification_final"] == [] and row["stopped"] == ""
    # [주의] 줄에는 규칙 이름만 둔다. 위반 문장의 뒷부분(모델이 쓴 값)은 남기지 않는다
    assert "L999999" not in str(row)
    blocked, _ = evaluate_item(
        agent_deps(write=lambda prompt: BAD), item("DEMO0001 어디예요?"), "planner", TODAY, PRICES
    )
    limit = load_rules("agent")["answer"]["max_write_attempts"]
    assert blocked["behaviour"] == "partial" and blocked["write_attempts"] == limit
    assert blocked["verification_final"] == ["근거 묶음에 없는 인용"] and blocked["stopped"] == ""
    failed, _ = evaluate_item(
        agent_deps(model=LimitModel(messages=iter([]))), item("수입신고 기한은요?"), "agent", TODAY, PRICES
    )
    assert failed["stopped"] == "llm_failed" and failed["write_attempts"] == 0


def test_raw_keeps_each_search_query_masked_and_the_row_keeps_none(agent_deps):
    deps = agent_deps(model=model(("search_law", {"query": "수입신고 기한"})), write=lambda prompt: CITING)
    row, raw = evaluate_item(deps, item("DEMO0001 언제까지 수입신고 해요?"), "agent", TODAY, PRICES)
    assert raw["searches"] == ["수입신고 기한"]
    assert "수입신고 기한" not in str(row["rag"])  # 검색어(LLM 글)는 저장소에 들어가는 줄에 두지 않는다
    # [주의] raw의 answer는 화면에 나간 답이라 번호가 보인다(기존 동작). 검색어 칸에는 번호가 없어야 한다
    numbered = model(("search_law", {"query": "DEMO0001 수입신고 기한"}))
    _, raw = evaluate_item(
        agent_deps(model=numbered, write=lambda prompt: CITING),
        item("DEMO0001 언제까지 수입신고 해요?"),
        "agent",
        TODAY,
        PRICES,
    )
    assert "DEMO0001" not in str(raw["searches"])


def test_a_real_number_in_a_search_query_never_reaches_the_raw_file():
    # 이 차례의 가림 표에 있는 번호는 그 토큰으로, 표에 없는 번호 덩어리도 토큰으로 바꾼다
    out = masked_queries(["DEMO0001 수입신고 기한", "MOCK0002 통관"], {"[BL1]": "DEMO0001"})
    assert out[0] == "[BL1] 수입신고 기한"
    assert "DEMO0001" not in str(out) and "MOCK0002" not in str(out)


def failing_write(name: str):
    def write(prompt):
        raise LLMFailed(name)

    return write


def test_row_counts_structured_calls_and_those_that_kept_the_schema_on_the_first_try(agent_deps):
    question = item("DEMO0001 어디예요?")
    ok, _ = evaluate_item(agent_deps(), question, "planner", TODAY, PRICES)
    counted = {"calls": 2, "first_try": 2, "no_answer": 0, "unknown": 0, "requests": {}}
    assert ok["contract"] == counted  # 계획 1 + 작성 1
    broken = agent_deps(write=failing_write("OutputParserException"))
    shape, _ = evaluate_item(broken, question, "planner", TODAY, PRICES)
    assert shape["contract"] == counted | {"first_try": 1}
    # [왜] 시간 초과 같은 호출 실패는 모델이 답을 내지 못한 것이라 계약 준수의 분모에 넣지 않는다
    timed_out = agent_deps(write=failing_write("APITimeoutError"))
    down, _ = evaluate_item(timed_out, question, "planner", TODAY, PRICES)
    # 대신 답이 없던 호출 수를 따로 남긴다: 비율이 높아도 몇 번이 빠졌는지 보인다
    assert down["contract"] == counted | {"calls": 1, "first_try": 1, "no_answer": 1}
    # RAG 안의 구조화 호출(질의 분석, 근거 채점)도 센다
    deps = agent_deps(model=model(("search_law", {"query": "수입신고 기한"})), write=lambda prompt: CITING)
    searched, _ = evaluate_item(deps, item("수입신고 기한은요?"), "agent", TODAY, PRICES)
    assert searched["contract"]["calls"] >= 3


def structured_end(watch: LlmWatch, first_try, requests) -> None:
    """`claude -p`의 구조화 호출 하나가 끝났을 때 모델이 남기는 것(cli_model.py)을 콜백에 넣는다."""
    meta = {"structured_first_try": first_try, "api_requests": requests}
    message = AIMessage(content="", response_metadata=meta)
    watch.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=uuid4())


@pytest.mark.parametrize(
    ("first_try", "requests", "fails", "expected"),
    [
        (True, 2, False, {"first_try": 1, "requests": {"2": 1}}),
        # CLI가 모양이 틀려 안에서 다시 시켰다: 끝내 맞아도 첫 시도 통과가 아니다
        (False, 3, False, {"first_try": 0, "requests": {"3": 1}}),
        # 다시 시킨 뒤 pydantic 검증에서 떨어졌다: 한 번만 뺀다
        (False, 3, True, {"first_try": 0, "requests": {"3": 1}}),
        # CLI 결과에 요청 수가 없으면 통과로 치지 않고 알 수 없음으로 따로 센다
        (None, None, False, {"first_try": 0, "unknown": 1, "requests": {"없음": 1}}),
    ],
)
def test_each_structured_call_lands_in_exactly_one_contract_count(
    agent_deps, first_try, requests, fails, expected
):
    contract = Contract()
    watch = LlmWatch(contract)

    def write(prompt):
        structured_end(watch, first_try, requests)
        if fails:
            raise LLMFailed("OutputParserException")
        return CITING

    deps = eval_deps(agent_deps(write=write), item("질문"), TODAY, [], contract=contract)
    if fails:
        with pytest.raises(LLMFailed):
            deps.write("프롬프트")
    else:
        deps.write("프롬프트")
    base = {"calls": 1, "first_try": 1, "no_answer": 0, "unknown": 0, "requests": {}}
    assert contract.row() == base | expected
    # API 길의 답과 도구 호출 답에는 이 칸이 없다: 세지 않는다
    plain = AIMessage(content="도구 호출")
    watch.on_llm_end(LLMResult(generations=[[ChatGeneration(message=plain)]]), run_id=uuid4())
    assert contract.row() == base | expected


class FakeCLI:
    """`claude -p` 프로세스를 흉내 낸다: 부를 때마다 정해 둔 이벤트 묶음을 차례로 낸다."""

    def __init__(self, *runs: list[dict]):
        self.runs = iter(runs)

    def __call__(self, command, **kwargs):
        lines = [json.dumps(e, ensure_ascii=False) + "\n" for e in next(self.runs)]
        stdin = SimpleNamespace(write=lambda text: None, close=lambda: None)
        return SimpleNamespace(stdin=stdin, stdout=iter(lines), kill=lambda: None, wait=lambda: 0)


CLI_INIT = {"type": "system", "subtype": "init", "mcp_servers": [{"name": "marvia", "status": "connected"}]}


def cli_event(kind: str, **fields) -> dict:
    return {"type": "stream_event", "event": {"type": kind, **fields}}


def test_the_run_stops_at_the_first_item_with_a_cli_failure_even_when_other_calls_worked(
    agent_deps, monkeypatch
):
    block = {"type": "tool_use", "name": "mcp__marvia__search_law", "input": {"query": "기한"}}
    searched = [
        CLI_INIT,
        cli_event("message_start", message={"usage": {"input_tokens": 10}}),
        {"type": "assistant", "message": {"model": "claude-haiku-5-5", "content": [block]}},
        cli_event("message_delta", delta={"stop_reason": "tool_use"}, usage={"output_tokens": 5}),
        cli_event("message_stop"),
    ]
    # 둘째 호출에서 사용량 한도에 걸렸다: 모델 메시지 없이 결과가 먼저 온다
    limited = [CLI_INIT, {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429}]
    monkeypatch.setattr("marvia.cli_model.subprocess.Popen", FakeCLI(searched, limited))
    model = ClaudeCLIChat(model="claude-haiku-5-5", timeout=5)
    deps = agent_deps(model=model, write=lambda prompt: CITING)
    row, _ = evaluate_item(deps, item("수입신고 기한은요?"), "agent", TODAY, PRICES, llm_via="cli")
    # 앞 호출은 성공해 호출 수와 검색 기록이 있다. 그래도 이 줄은 CLI 실패 줄이다
    assert row["real_llm_calls"] >= 2 and row["tools"] == ["search_law"]
    assert row["error"] == "CLIFailed: CLI(success,429)"
    limit = load_rules("eval")["run"]["cli_failure_rows"]
    assert limit == 1
    # [왜] 사용량 한도나 로그인 문제는 다음 문항에서도 되풀이된다. 남은 문항을 오류로 채우지 않고 멈춘다
    reason = halt_reason([row], limit)
    # [주의] 멈춘 실행은 문항을 다 덮지 못해 무효다. 이어 돌린 파일도 판정에 못 쓰니 다시 돌리라고 알린다
    assert "claude -p" in reason and "처음부터 다시" in reason and "--ids" not in reason
    clean = row | {"error": None}
    assert halt_reason([clean], limit) is None
    assert halt_reason([clean, row], 2) is None and halt_reason([row, clean, row], 2) is not None
    # 돈이 새는 줄의 멈춤 규칙(stop_reason)도 그대로 본다
    assert halt_reason([clean | {"tokens": {}}], limit) == stop_reason(clean | {"tokens": {}})


def test_supervisor_row_lists_subagent_visits_and_the_tools_called_inside_them(agent_deps):
    # 수퍼바이저 길(계획 7b): 화물·기한 서브에이전트 → 법령 조사 서브에이전트
    def call(name, args, id):
        return AIMessage("", tool_calls=[{"name": name, "args": args, "id": id}])

    script = [
        call("handoff", {"to": "cargo", "task": "[BL1]의 수입신고 기한 계산"}, "h1"),
        call("calc_deadlines", {}, "c1"),
        AIMessage("기한을 계산했어요."),
        call("handoff", {"to": "law", "task": "수입신고 기한의 근거"}, "h2"),
        call("search_law", {"query": "수입신고 기한"}, "s1"),
        AIMessage("관세법 제241조제3항이에요."),
        AIMessage(""),
    ]
    deps = agent_deps(model=ToolModel(messages=iter(script)), write=lambda prompt: CITING)
    row, _ = evaluate_item(deps, item("DEMO0001 언제까지 수입신고 해요?"), "supervisor", TODAY, PRICES)
    assert row["error"] is None and row["behaviour"] == "answer"
    assert row["visits"] == ["cargo", "law"]
    # [왜] 넘기기는 "sub:이름"으로 적고 그 뒤에 그 서브에이전트가 부른 도구를 잇는다.
    #      궤적 조건이 이 순서를 본다
    assert row["tools"] == ["sub:cargo", "calc_deadlines", "sub:law", "search_law"]
    # [왜] 이름별 호출 수도 서브에이전트 안의 도구를 센다. 도구 길이 돌았는지 줄만 보고 안다
    assert row["tool_counts"] == {"sub:cargo": 1, "calc_deadlines": 1, "sub:law": 1, "search_law": 1}
    assert row["cited"] == ["L001556@20261002#제241조.3항"] and not row["leak"]


def test_supervisor_row_that_hit_the_cap_inside_a_subagent_is_one_cap_stop(agent_deps):
    from marvia.eval.metrics import cap_stops

    cap = load_rules("agent")["loop"]["max_llm_calls"]

    def call(name, args, id):
        return AIMessage("", tool_calls=[{"name": name, "args": args, "id": id}])

    # 수퍼바이저 1 + 화물·기한 서브에이전트 19번에서 상한
    script = [call("handoff", {"to": "cargo", "task": "기한 계산"}, "h1")]
    script += [call("calc_deadlines", {}, f"k{i}") for i in range(cap - 1)]
    deps = agent_deps(model=ToolModel(messages=iter(script)))
    row, _ = evaluate_item(deps, item("DEMO0001 언제까지 수입신고 해요?"), "supervisor", TODAY, PRICES)
    assert row["behaviour"] == "partial" and row["stopped"] == "llm_calls" and row["llm_calls"] == cap
    assert row["failed"] == [f"cargo: LLM 호출 한도({cap}회)에 닿았어요"]
    # [왜] 멈춘 이유 칸과 실패 기록 둘 다 상한을 말해도 한 줄은 한 번만 센다
    assert cap_stops([row]) == 1


def test_agent_row_has_no_visits(agent_deps):
    deps = agent_deps(model=model(("search_law", {"query": "수입신고 기한"})), write=lambda prompt: CITING)
    row, _ = evaluate_item(deps, item("DEMO0001 언제까지 수입신고 해요?"), "agent", TODAY, PRICES)
    assert row["visits"] == [] and row["tools"] == ["search_law"]
