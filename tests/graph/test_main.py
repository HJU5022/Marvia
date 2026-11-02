from dataclasses import replace

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from marvia.graph.main import build_main_graph, merge_evidence
from marvia.graph.schemas import Draft, Plan, Step
from marvia.llm import LLMFailed
from marvia.rag.schemas import Grade
from marvia.tools.reimport import ItemFacts
from marvia.tools.rules import load_rules

# 근거 묶음에 없는 unit_id를 인용한 초안. 검증에서 늘 걸린다
BAD = Draft(
    answer="나쁜 답이에요.", citations=["LNOPE@20260101#제1조"], next_options=[], forwarder_message=""
)
FIXED = Draft(answer="고친 답이에요.", citations=[], next_options=[], forwarder_message="")
# 가짜 RAG가 찾는 제241조제3항을 인용한 초안 (조문 이름과 30일이 인용한 근거에 있다)
CITING = Draft(
    answer="관세법 제241조에 따라 반입일부터 30일 이내에 수입신고해야 해요.",
    citations=["L001556@20261002#제241조.3항"],
    next_options=[],
    forwarder_message="",
)
SEARCH = Plan(steps=[Step(action="search_law", query="수입신고 기한", reason="기한 조문을 찾는다")])
WRITE = Plan(steps=[Step(action="write", query="", reason="찾은 근거로 답한다")])
CALC = Plan(steps=[Step(action="calc", query="", reason="기한을 계산한다")])
EXTRACT = Plan(steps=[Step(action="extract_item", query="", reason="품목 사실을 뽑는다")])
# 건고추를 5년 안에 다시 들여오고 조건을 모두 채운 사실
CHILI = ItemFacts(
    category="농산물·임산물",
    same=["생산국", "품명", "수출업소", "포장장소"],
    different=[],
    prior_precise="받음",
    prior_result="적합",
    prior_cert_on="2026-03-10",
    flags=[],
)


def cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def recording(prompts: list[str], *answers):
    """받은 프롬프트를 prompts에 적고 answers를 앞에서부터 하나씩 돌려주는 가짜 LLM (작성자·계획자 공용)."""
    left = iter(answers)

    def call(prompt: str):
        prompts.append(prompt)
        return next(left)

    return call


def failing(error: Exception):
    """부르면 error를 내는 가짜 LLM."""

    def call(prompt: str):
        raise error

    return call


def test_unambiguous_answers_directly(agent_deps):
    graph = build_main_graph(agent_deps(), InMemorySaver())
    out = graph.invoke({"text": "demo0001 demo0002 어디야?"}, cfg("t1"))
    assert "2건으로 읽었어요." in out["answer"]
    assert "DEMO0002: 수입신고 (부산)" in out["answer"]
    assert "시험 답이에요." in out["answer"]  # 코드가 쓴 화물 줄 아래에 작성자 답


def test_ambiguous_interrupts_then_resumes(agent_deps):
    graph = build_main_graph(agent_deps(), InMemorySaver())
    out = graph.invoke({"text": "MOCK12345678TEST87654321"}, cfg("t2"))
    question = out["__interrupt__"][0].value
    assert question["kind"] == "choice" and question["recommended"] == 0
    out = graph.invoke(Command(resume={"selected": 0}), cfg("t2"))
    assert "MOCK12345678: 입항 (인천)" in out["answer"]
    assert "TEST87654321: 하선신고 (인천)" in out["answer"]


def test_custom_reply(agent_deps):
    graph = build_main_graph(agent_deps(), InMemorySaver())
    graph.invoke({"text": "MOCK12345678TEST87654321"}, cfg("t3"))
    out = graph.invoke(Command(resume={"custom": "MOCK12345678"}), cfg("t3"))
    assert "MOCK12345678" in out["answer"]
    assert "TEST87654321" not in out["answer"]


def test_no_number_guides_user(agent_deps):
    asked = Draft(
        answer="화물을 찾으려면 번호가 필요해요.",
        citations=[],
        next_options=[],
        forwarder_message="이번 고추 화물의 운송 서류 번호를 알려 주세요.",
    )
    graph = build_main_graph(agent_deps(write=lambda prompt: asked), InMemorySaver())
    out = graph.invoke({"text": "다음 주에 칭다오에서 고추 와요"}, cfg("t4"))
    assert "B/L" in out["answer"]  # 코드가 쓰는 포워더 안내 줄


def test_writer_sees_masked_text_only(agent_deps):
    prompts: list[str] = []
    graph = build_main_graph(agent_deps(write=recording(prompts, FIXED)), InMemorySaver())
    graph.invoke({"text": "DEMO0001 언제까지 신고해야 해요?"}, cfg("t5"))
    assert "[BL1] 언제까지 신고해야 해요?" in prompts[0]
    assert "[BL1]: 반입신고 (부산) 2026-10-27" in prompts[0]  # 화물 줄도 토큰으로
    assert "DEMO0001" not in prompts[0]


def test_violation_gets_one_rewrite(agent_deps):
    prompts: list[str] = []
    graph = build_main_graph(agent_deps(write=recording(prompts, BAD, FIXED)), InMemorySaver())
    out = graph.invoke({"text": "DEMO0001 어디야?"}, cfg("t6"))
    assert "고친 답이에요." in out["answer"]
    assert "근거 묶음에 없는 인용: LNOPE@20260101#제1조" in prompts[1]  # 위반을 두 번째 프롬프트에 넘긴다


def test_second_violation_gives_partial_answer(agent_deps):
    graph = build_main_graph(agent_deps(write=lambda prompt: BAD), InMemorySaver())
    out = graph.invoke({"text": "DEMO0001 어디야?"}, cfg("t7"))
    assert "끝까지 확인하지 못했어요" in out["answer"]
    assert "DEMO0001: 반입신고 (부산)" in out["answer"]
    assert "나쁜 답이에요." not in out["answer"]  # 검증을 못 넘은 초안은 쓰지 않는다
    assert graph.get_state(cfg("t7")).values["write_attempts"] == 2


def test_second_turn_starts_clean(agent_deps):
    graph = build_main_graph(agent_deps(), InMemorySaver())
    graph.invoke({"text": "DEMO0001 어디야?"}, cfg("t8"))
    graph.invoke({"text": "DEMO0002 어디야?"}, cfg("t8"))
    values = graph.get_state(cfg("t8")).values
    assert values["write_attempts"] == 1 and values["llm_calls"] == 2  # 이번 차례의 계획 1 + 작성 1
    assert len(values["plan"]) == 1  # 지난 차례의 할 일이 남지 않는다


def test_interrupted_second_turn_does_not_show_last_answer(agent_deps):
    # [왜] 지난 차례 답(실제 번호를 되돌린 글)이 멈춘 차례의 결과에 남으면
    #      화면이 지난 답을 다시 보여 줄 수 있다
    graph = build_main_graph(agent_deps(), InMemorySaver())
    graph.invoke({"text": "DEMO0001 어디야?"}, cfg("t8b"))
    out = graph.invoke({"text": "MOCK12345678TEST87654321"}, cfg("t8b"))
    assert "__interrupt__" in out and out.get("answer", "") == ""


def test_plan_search_then_write(agent_deps):
    plan_prompts: list[str] = []
    deps = agent_deps(plan=recording(plan_prompts, SEARCH, WRITE), write=lambda prompt: CITING)
    graph = build_main_graph(deps, InMemorySaver())
    out = graph.invoke({"text": "DEMO0001 언제까지 수입신고 해야 해요?"}, cfg("t9"))
    # 코드가 쓰는 근거 목록에 인용한 조문의 제목·출처가 붙는다
    assert "관세법 > 제9장 통관 > 제241조(수출ㆍ수입 또는 반송의 신고)" in out["answer"]
    values = graph.get_state(cfg("t9")).values
    assert [(s["action"], s["status"]) for s in values["plan"]] == [
        ("search_law", "done"),
        ("write", "in_progress"),
    ]
    assert values["llm_calls"] == 5  # 계획 2 + RAG 상한 2 (고쳐 쓰기 0) + 작성 1
    # 두 번째 계획 프롬프트는 찾은 근거의 제목과 한 일을 본다. 실제 번호는 어디에도 없다
    assert "[L001556@20261002#제241조.3항] 관세법 > 제9장 통관" in plan_prompts[1]
    assert "search_law: 수입신고 기한" in plan_prompts[1]
    assert "DEMO0001" not in "".join(plan_prompts)


def test_search_gap_and_rewrites_counted(agent_deps, fake_rag):
    deps = agent_deps(
        rag=fake_rag(sufficient=False), plan=recording([], SEARCH, WRITE), write=lambda p: CITING
    )
    graph = build_main_graph(deps, InMemorySaver())
    graph.invoke({"text": "가산세가 붙는 보세구역은 어디예요?"}, cfg("t10"))
    values = graph.get_state(cfg("t10")).values
    assert values["gaps"] == ["가산세 대상 보세구역 목록"]
    assert values["llm_calls"] == 9  # 계획 2 + RAG 상한 6 (고쳐 쓰기 2, rules/rag.yaml) + 작성 1


def test_empty_missing_is_not_a_gap(agent_deps, fake_rag):
    # 채점이 "부족"이어도 빠진 근거 문장이 비면 빈 줄을 남기지 않는다
    rag = replace(
        fake_rag(sufficient=False), grade=lambda p: Grade(sufficient=False, reason="시험", missing="")
    )
    deps = agent_deps(rag=rag, plan=recording([], SEARCH, WRITE), write=lambda p: CITING)
    graph = build_main_graph(deps, InMemorySaver())
    graph.invoke({"text": "수입신고는 언제 해요?"}, cfg("t10b"))
    assert graph.get_state(cfg("t10b")).values["gaps"] == []


def test_empty_plan_goes_to_write(agent_deps):
    graph = build_main_graph(agent_deps(plan=lambda prompt: Plan(steps=[])), InMemorySaver())
    out = graph.invoke({"text": "수입신고는 언제 해요?"}, cfg("t11"))
    assert "시험 답이에요." in out["answer"]


def test_merge_keeps_best_score_per_unit():
    old = [{"unit_id": "A", "score": 0.2}, {"unit_id": "B", "score": 0.5}]
    new = [{"unit_id": "A", "score": 0.7}]
    assert merge_evidence(old, new) == [{"unit_id": "A", "score": 0.7}, {"unit_id": "B", "score": 0.5}]


def test_calc_gives_deadline_from_stage_date(agent_deps, calc):
    due = Draft(
        answer="[BL1]은 2026-11-26까지 수입신고해야 해요. 24일 남았어요.",
        citations=[],
        next_options=[],
        forwarder_message="",
    )
    write_prompts: list[str] = []
    deps = agent_deps(plan=recording([], CALC, WRITE), write=recording(write_prompts, due))
    graph = build_main_graph(deps, InMemorySaver())
    out = graph.invoke({"text": "DEMO0001 언제까지 수입신고 해야 해요?"}, cfg("t12"))
    # 반입신고 2026-10-27 (한국 날짜) + 30일 = 2026-11-26. 계산 결과의 모양은 conftest의 calc 준비물과 같다
    assert graph.get_state(cfg("t12")).values["calc"] == calc
    assert '"due": "2026-11-26"' in write_prompts[0]
    assert (
        "DEMO0001은 2026-11-26까지 수입신고해야 해요." in out["answer"]
    )  # 검증을 넘어 실제 번호로 되돌린 답


def test_item_facts_then_reimport_check(agent_deps):
    item_prompts: list[str] = []
    deps = agent_deps(plan=recording([], EXTRACT, CALC, WRITE), item=recording(item_prompts, CHILI))
    graph = build_main_graph(deps, InMemorySaver())
    graph.invoke({"text": "작년 3월에 정밀검사 받은 건고추를 같은 수출업소에서 다시 들여와요"}, cfg("t13"))
    values = graph.get_state(cfg("t13")).values
    assert values["calc"]["reimport"]["verdict"] == "서류검사 요건 충족"
    assert values["calc"]["reimport"]["window_end"] == "2031-03-10"
    assert values["llm_calls"] == 5  # 계획 3 + 품목 사실 1 + 작성 1
    assert "100kg" in item_prompts[0]  # 정밀검사 사유와 yaml 이름표를 함께 보여 준다


def test_second_turn_drops_item(agent_deps):
    deps = agent_deps(plan=recording([], EXTRACT, CALC, WRITE, WRITE), item=lambda prompt: CHILI)
    graph = build_main_graph(deps, InMemorySaver())
    graph.invoke({"text": "건고추를 다시 들여와요"}, cfg("t14"))
    graph.invoke({"text": "수입신고는 언제 해요?"}, cfg("t14"))
    values = graph.get_state(cfg("t14")).values
    assert values["item"] == {} and values["calc"] == {}  # 지난 차례의 품목 사실과 계산이 남지 않는다


def test_llm_call_cap_gives_partial_answer(agent_deps):
    # 계획자가 끝없이 검색만 고른다. 호출 수 상한에 닿으면 부분 답으로 끝난다
    graph = build_main_graph(agent_deps(plan=lambda prompt: SEARCH), InMemorySaver())
    out = graph.invoke({"text": "수입신고 기한이 언제예요?"}, cfg("t15"))
    assert "끝까지 확인하지 못했어요" in out["answer"]
    assert "찾은 근거:" in out["answer"]  # 그동안 찾은 근거의 제목은 남긴다
    assert graph.get_state(cfg("t15")).values["llm_calls"] >= load_rules("agent")["loop"]["max_llm_calls"]


def test_remaining_steps_gives_partial_answer(agent_deps):
    # recursion_limit을 작게 주면 호출 수 상한보다 먼저 남은 단계가 모자란다. 오류 대신 부분 답
    graph = build_main_graph(agent_deps(plan=lambda prompt: SEARCH), InMemorySaver())
    out = graph.invoke({"text": "수입신고 기한이 언제예요?"}, cfg("t16") | {"recursion_limit": 10})
    assert "끝까지 확인하지 못했어요" in out["answer"]
    assert graph.get_state(cfg("t16")).values["llm_calls"] < load_rules("agent")["loop"]["max_llm_calls"]


def test_rewrite_path_fits_in_remaining_steps(agent_deps):
    # [왜] 계산 뒤 작성자가 두 번 다 검증에 걸려도(write → verify → write → verify → finish)
    #      한도 경계에서 GraphRecursionError 대신 부분 답이 나와야 한다 (검증 담당 11-02 실측: 5면 모자랐다)
    deps = agent_deps(plan=recording([], CALC, WRITE), write=lambda prompt: BAD)
    graph = build_main_graph(deps, InMemorySaver())
    out = graph.invoke({"text": "DEMO0001 언제까지 신고해요?"}, cfg("t16b") | {"recursion_limit": 10})
    assert "끝까지 확인하지 못했어요" in out["answer"]


def test_recursion_limit_from_rules(agent_deps):
    graph = build_main_graph(agent_deps(), InMemorySaver())
    assert graph.config["recursion_limit"] == load_rules("agent")["loop"]["recursion_limit"]


def test_search_failure_is_recorded_and_planner_sees_it(agent_deps, fake_rag):
    plan_prompts: list[str] = []
    rag = fake_rag(fail=httpx.ConnectError("연결 안 됨"))
    graph = build_main_graph(
        agent_deps(rag=rag, plan=recording(plan_prompts, SEARCH, WRITE)), InMemorySaver()
    )
    out = graph.invoke({"text": "수입신고 기한이 언제예요?"}, cfg("t17"))
    assert "search_law: ConnectError" in plan_prompts[1]  # 오류 글(연결 안 됨)은 넣지 않는다
    assert "시험 답이에요." in out["answer"]  # 검색이 실패해도 차례는 이어 간다


def test_planner_failure_gives_partial_answer(agent_deps):
    graph = build_main_graph(agent_deps(plan=failing(LLMFailed("APITimeoutError"))), InMemorySaver())
    out = graph.invoke({"text": "DEMO0001 어디야?"}, cfg("t18"))
    assert "끝까지 확인하지 못했어요" in out["answer"] and "- plan: APITimeoutError" in out["answer"]


def test_item_failure_gives_partial_answer_without_another_plan_call(agent_deps):
    plan_prompts: list[str] = []
    deps = agent_deps(plan=recording(plan_prompts, EXTRACT), item=failing(LLMFailed("OutputParserException")))
    graph = build_main_graph(deps, InMemorySaver())
    out = graph.invoke({"text": "건고추를 다시 들여와요"}, cfg("t19"))
    assert "- extract_item: OutputParserException" in out["answer"]
    assert len(plan_prompts) == 1  # 실패 뒤에는 계획자를 다시 부르지 않는다


def test_writer_failure_gives_partial_answer(agent_deps):
    graph = build_main_graph(agent_deps(write=failing(LLMFailed("RateLimitError"))), InMemorySaver())
    out = graph.invoke({"text": "DEMO0001 어디야?"}, cfg("t20"))
    assert "끝까지 확인하지 못했어요" in out["answer"] and "- write: RateLimitError" in out["answer"]
