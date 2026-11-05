"""에이전트 길(계획 3c) 시험. 가짜 도구 호출 모델로 키 없이 돈다."""

import anthropic
import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from marvia.graph.agent import ONE_IN_PROGRESS
from marvia.graph.main import build_main_graph
from marvia.graph.schemas import Draft
from marvia.tools.rules import load_rules

CITING = Draft(
    answer="관세법 제241조에 따라 반입일부터 30일 이내에 수입신고해야 해요.",
    citations=["L001556@20261002#제241조.3항"],
    next_options=[],
    forwarder_message="",
)

CHILI = {
    "category": "농산물·임산물",
    "same": ["생산국", "품명", "수출업소", "포장장소"],
    "different": [],
    "prior_precise": "받음",
    "prior_result": "적합",
    "prior_cert_on": "2026-03-10",
    "flags": [],
}

TWO = [{"label": "부산", "description": "부산항 기준"}, {"label": "인천", "description": "인천항 기준"}]


class ToolModel(GenericFakeChatModel):
    """정해 둔 AIMessage를 차례로 내는 가짜 모델. bind_tools는 자기를 그대로 돌려준다."""

    def bind_tools(self, tools, **kwargs):
        return self


class BrokenModel(ToolModel):
    """부르면 API 오류를 내는 가짜 모델."""

    def _generate(self, *args, **kwargs):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.test"))


class FailsAfter(ToolModel):
    """정해 둔 메시지를 다 낸 뒤에는 API 오류를 내는 가짜 모델."""

    def _generate(self, *args, **kwargs):
        # [왜] GenericFakeChatModel은 메시지가 떨어지면 next()가 StopIteration을 낸다
        #      (langchain_core 소스 확인)
        try:
            return super()._generate(*args, **kwargs)
        except StopIteration:
            raise anthropic.APIConnectionError(
                request=httpx.Request("POST", "https://api.anthropic.test")
            ) from None


def say(*calls: tuple[str, dict], text: str = "") -> AIMessage:
    """도구 호출을 담은 AIMessage. calls가 없으면 루프를 끝내는 답이다."""
    return AIMessage(
        content=text, tool_calls=[{"name": n, "args": a, "id": f"c{i}-{n}"} for i, (n, a) in enumerate(calls)]
    )


def model(*messages: AIMessage) -> ToolModel:
    return ToolModel(messages=iter(messages))


def cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def agent_graph(agent_deps, *messages, store=None, permission_mode="ask", **changes):
    deps = agent_deps(model=model(*messages), **changes)
    return build_main_graph(deps, InMemorySaver(), loop="agent", store=store, permission_mode=permission_mode)


def all_text(values: dict) -> str:
    """에이전트 메시지의 글과 도구 호출 인자를 한 글로 모은다 (번호가 새는지 볼 때)."""
    parts = []
    for message in values.get("messages", []):
        parts.append(str(message.content))
        parts += [str(call["args"]) for call in getattr(message, "tool_calls", None) or []]
    return "\n".join(parts)


def test_agent_searches_then_writer_answers(agent_deps):
    graph = agent_graph(
        agent_deps, say(("search_law", {"query": "수입신고 기한"})), say(), write=lambda p: CITING
    )
    out = graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a1"))
    values = graph.get_state(cfg("a1")).values
    assert "관세법 > 제9장 통관 > 제241조" in out["answer"]  # 인용은 코드가 붙인다
    assert [e["unit_id"] for e in values["evidence"]] == ["L001556@20261002#제241조.3항"]
    # 모델 2 + RAG 2(질의 분석·채점) + 작성자 1
    assert values["llm_calls"] == 5


def test_agent_path_needs_a_model(agent_deps):
    with pytest.raises(ValueError, match="AgentDeps.model"):
        build_main_graph(agent_deps(), InMemorySaver(), loop="agent")


def test_parallel_searches_merge_into_one_bundle(agent_deps):
    calls = (("search_law", {"query": "수입신고 기한"}), ("search_law", {"query": "반입신고"}))
    graph = agent_graph(agent_deps, say(*calls), say(), write=lambda p: CITING)
    graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a2"))
    values = graph.get_state(cfg("a2")).values
    assert len(values["evidence"]) == 1  # 같은 조문은 하나로 합친다
    assert values["llm_calls"] == 2 + 4 + 1


def test_same_query_is_not_searched_twice(agent_deps, fake_rag):
    seen = []
    rag = fake_rag()
    counting = type(rag)(**{**rag.__dict__, "search": lambda q, d: seen.append(q) or rag.search(q, d)})
    query = {"query": "수입신고 기한"}
    graph = agent_graph(
        agent_deps,
        say(("search_law", query)),
        say(("search_law", query)),
        say(),
        rag=counting,
        write=lambda p: CITING,
    )
    graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a3"))
    assert len(seen) == 1


def test_search_failure_is_recorded_and_loop_goes_on(agent_deps, fake_rag):
    rag = fake_rag(fail=httpx.ConnectError("연결 안 됨"))
    graph = agent_graph(agent_deps, say(("search_law", {"query": "수입신고 기한"})), say(), rag=rag)
    out = graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a4"))
    values = graph.get_state(cfg("a4")).values
    assert values["failed_tools"] == [{"tool": "search_law", "message": "ConnectError"}]
    assert "시험 답이에요." in out["answer"]


def test_deadlines_come_from_code_and_numbers_stay_masked(agent_deps):
    graph = agent_graph(agent_deps, say(("calc_deadlines", {})), say())
    out = graph.invoke({"text": "DEMO0001 언제까지 수입신고 해야 해요?"}, cfg("a5"))
    values = graph.get_state(cfg("a5")).values
    assert values["calc"]["deadlines"][0]["name"] == "수입신고 기한"
    assert "DEMO0001" not in all_text(values)  # 모델이 본 글과 도구 인자에는 토큰만 있다
    assert "DEMO0001" in out["answer"]  # 화면에 보낼 때만 되돌린다


def test_reimport_facts_go_straight_to_the_code_check(agent_deps):
    graph = agent_graph(agent_deps, say(("check_reimport", {"facts": CHILI})), say())
    graph.invoke({"text": "건고추를 다시 들여와요"}, cfg("a6"))
    values = graph.get_state(cfg("a6")).values
    assert values["calc"]["reimport"]["verdict"] == "서류검사 요건 충족"
    assert values["item"]["category"] == "농산물·임산물"


def test_two_reimport_checks_in_one_step_do_not_crash(agent_deps):
    # [왜] 병렬로 부른 두 도구가 같은 칸(item)에 쓰면 reducer가 있어야 한다
    other = CHILI | {"prior_precise": "안 받음"}
    graph = agent_graph(
        agent_deps, say(("check_reimport", {"facts": CHILI}), ("check_reimport", {"facts": other})), say()
    )
    graph.invoke({"text": "건고추 두 가지를 다시 들여와요"}, cfg("a6b"))
    values = graph.get_state(cfg("a6b")).values
    assert values["item"]["prior_precise"] in ("받음", "안 받음")


def test_lookup_cargo_tool_uses_tokens_only(agent_deps):
    # DEMO0001은 B/L 모양이라 토큰이 [BL1]이다
    graph = agent_graph(agent_deps, say(("lookup_cargo", {"tokens": ["[BL1]", "[BL9]"]})), say())
    graph.invoke({"text": "DEMO0001 다시 봐 줘"}, cfg("a7"))
    values = graph.get_state(cfg("a7")).values
    tool_text = [m.content for m in values["messages"] if m.type == "tool"][0]
    assert "[BL9]: 모르는 토큰이에요" in tool_text and "DEMO0001" not in tool_text
    assert "[BL1]: 반입신고" in tool_text
    assert [c["token"] for c in values["cargos"]] == ["[BL1]"]  # 같은 토큰은 바꾸고 늘리지 않는다


def test_llm_cap_is_kept_exactly_and_ends_in_partial_answer(agent_deps, fake_rag):
    seen = []
    rag = fake_rag()
    counting = type(rag)(**{**rag.__dict__, "search": lambda q, d: seen.append(q) or rag.search(q, d)})
    # [왜] 늘 새 질의로 검색하는 모델: 검색 상한과 LLM 호출 상한이 모두 닿는다
    endless = [say(("search_law", {"query": f"질의 {i}"})) for i in range(40)]
    graph = agent_graph(agent_deps, *endless, rag=counting)
    out = graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a8"))
    values = graph.get_state(cfg("a8")).values
    cap = load_rules("agent")["loop"]["max_llm_calls"]
    assert len(seen) == load_rules("agent")["loop"]["max_searches"]
    assert values["llm_calls"] == cap  # 상한을 넘지 않는다
    assert values["stopped"] == "llm_calls"
    assert "끝까지 확인하지 못했어요" in out["answer"] and f"LLM 호출 한도({cap}회)" in out["answer"]


def test_search_is_refused_when_the_budget_would_pass_the_cap(agent_deps, fake_rag):
    seen = []
    rag = fake_rag(sufficient=False)
    counting = type(rag)(**{**rag.__dict__, "search": lambda q, d: seen.append(q) or rag.search(q, d)})
    endless = [say(("search_law", {"query": f"질의 {i}"})) for i in range(40)]
    graph = agent_graph(agent_deps, *endless, rag=counting)
    graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a8b"))
    values = graph.get_state(cfg("a8b")).values
    cap = load_rules("agent")["loop"]["max_llm_calls"]
    # [왜] 검색 한 번의 최악은 2 + 2 × max_rewrites(=2)로 6. 두 번은 상한 안, 세 번째는 넘어서 거절된다
    # [주의] seen은 RAG 안 검색 호출 수(고쳐 쓰기 포함)다.
    #        한 번 찾기 = 초기 검색 + 고쳐 쓴 검색 2번이라 6 = 두 번 찾기
    assert len(seen) == 3 * 2
    assert values["llm_calls"] == cap
    assert any("LLM 호출 한도가 가까워" in str(m.content) for m in values["messages"] if m.type == "tool")


def test_parallel_searches_never_pass_the_cap(agent_deps, fake_rag):
    rag = fake_rag(sufficient=False)
    calls = tuple(("search_law", {"query": f"병렬 질의 {i}"}) for i in range(5))
    graph = agent_graph(agent_deps, say(*calls), say(), rag=rag)
    graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a8c"))
    values = graph.get_state(cfg("a8c")).values
    cap = load_rules("agent")["loop"]["max_llm_calls"]
    assert values["llm_calls"] <= cap


def test_llm_failure_in_loop_gives_partial_answer(agent_deps):
    deps = agent_deps(model=BrokenModel(messages=iter([])))
    graph = build_main_graph(deps, InMemorySaver(), loop="agent")
    out = graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a9"))
    assert "- agent: APIConnectionError" in out["answer"]
    assert graph.get_state(cfg("a9")).values["stopped"] == "llm_failed"


def test_stopped_turn_puts_in_progress_todo_back_to_pending(agent_deps):
    todos = {
        "todos": [
            {"content": "기한 계산", "status": "in_progress"},
            {"content": "조문 찾기", "status": "pending"},
        ]
    }
    deps = agent_deps(model=FailsAfter(messages=iter([say(("write_todos", todos))])))
    graph = build_main_graph(deps, InMemorySaver(), loop="agent")
    out = graph.invoke({"text": "DEMO0001 언제까지 신고해요?"}, cfg("a9b"))
    values = graph.get_state(cfg("a9b")).values
    assert "끝까지 확인하지 못했어요" in out["answer"]
    assert [t["status"] for t in values["todos"]] == ["pending", "pending"]


def test_todo_list_keeps_one_in_progress_and_ends_completed(agent_deps):
    bad = {
        "todos": [
            {"content": "기한 계산", "status": "in_progress"},
            {"content": "조문 찾기", "status": "in_progress"},
        ]
    }
    good = {
        "todos": [
            {"content": "기한 계산", "status": "in_progress"},
            {"content": "조문 찾기", "status": "pending"},
        ]
    }
    graph = agent_graph(agent_deps, say(("write_todos", bad)), say(("write_todos", good)), say())
    graph.invoke({"text": "DEMO0001 언제까지 신고해요?"}, cfg("a10"))
    values = graph.get_state(cfg("a10")).values
    errors = [m for m in values["messages"] if m.type == "tool" and m.status == "error"]
    assert len(errors) == 1  # 진행 중이 둘인 목록은 오류로 돌려준다
    assert errors[0].content == ONE_IN_PROGRESS
    assert [t["status"] for t in values["todos"]] == [
        "completed",
        "pending",
    ]  # 답이 나오면 진행 중은 끝낸다


def test_malformed_todo_args_do_not_crash_the_turn(agent_deps):
    graph = agent_graph(agent_deps, say(("write_todos", {"todos": None})), say())
    out = graph.invoke({"text": "DEMO0001 언제?"}, cfg("a10b"))
    errors = [
        m for m in graph.get_state(cfg("a10b")).values["messages"] if m.type == "tool" and m.status == "error"
    ]
    assert "answer" in out and len(errors) == 1


def test_todo_updates_are_streamed(agent_deps):
    todos = {"todos": [{"content": "기한 계산", "status": "in_progress"}]}
    graph = agent_graph(agent_deps, say(("write_todos", todos)), say())
    # [왜] subgraphs=True: 루프(서브그래프) 안의 갱신도 (이름표, 갱신)으로 흘려보낸다.
    #      화면은 이 갱신으로 할 일 목록을 그린다. start 노드의 빈 todos와 섞이지 않게 루프 안의 갱신만 본다
    stream = graph.stream({"text": "DEMO0001 언제?"}, cfg("a11"), stream_mode="updates", subgraphs=True)
    inside = [update for ns, chunk in stream if ns for update in chunk.values() if update]
    assert any(update.get("todos") == todos["todos"] for update in inside)


def test_question_waits_for_a_choice(agent_deps):
    ask = say(("ask_user", {"question": "어느 항구 기준으로 볼까요?", "options": TWO}))
    graph = agent_graph(agent_deps, ask, say())
    out = graph.invoke({"text": "장치기간이 궁금해요"}, cfg("a12"))
    question = out["__interrupt__"][0].value
    assert question["kind"] == "choice" and question["recommended"] == 0 and len(question["options"]) == 2
    out = graph.invoke(Command(resume={"selected": 1}), cfg("a12"))
    values = graph.get_state(cfg("a12")).values
    assert "사용자 답: 인천" in all_text(values) and values["assumptions"] == []


def test_question_needs_two_or_three_options(agent_deps):
    one = say(("ask_user", {"question": "어느 항구?", "options": TWO[:1]}))
    graph = agent_graph(agent_deps, one, say())
    out = graph.invoke({"text": "장치기간이 궁금해요"}, cfg("a12b"))
    errors = [
        m for m in graph.get_state(cfg("a12b")).values["messages"] if m.type == "tool" and m.status == "error"
    ]
    assert "__interrupt__" not in out and len(errors) == 1  # 선택지 하나는 모델에게 오류로 돌려준다


def test_non_dict_resume_counts_as_no_answer(agent_deps):
    ask = say(("ask_user", {"question": "어느 항구 기준으로 볼까요?", "options": TWO}))
    graph = agent_graph(agent_deps, ask, say())
    graph.invoke({"text": "장치기간이 궁금해요"}, cfg("a13b"))
    out = graph.invoke(Command(resume="1"), cfg("a13b"))
    assert "권장안 '부산'" in out["answer"]


def test_no_answer_proceeds_with_the_recommended_option(agent_deps):
    ask = say(("ask_user", {"question": "어느 항구 기준으로 볼까요?", "options": TWO}))
    graph = agent_graph(agent_deps, ask, say())
    graph.invoke({"text": "장치기간이 궁금해요"}, cfg("a13"))
    # [왜] 시간 제한은 서버·화면이 잰다. 시간이 지나면 {"timeout": true}로 재개한다
    out = graph.invoke(Command(resume={"timeout": True}), cfg("a13"))
    assert "가정:" in out["answer"] and "권장안 '부산'" in out["answer"]


def test_typed_answer_with_a_number_is_masked(agent_deps):
    ask = say(("ask_user", {"question": "B/L 번호를 알려 주세요", "options": TWO}))
    # DEMO0002는 B/L 모양이라 [BL1]이 된다
    graph = agent_graph(agent_deps, ask, say(("lookup_cargo", {"tokens": ["[BL1]"]})), say())
    graph.invoke({"text": "내 화물 어디야?"}, cfg("a14"))
    graph.invoke(Command(resume={"custom": "DEMO0002로 봐 주세요"}), cfg("a14"))
    values = graph.get_state(cfg("a14")).values
    assert values["mask_map"] == {"[BL1]": "DEMO0002"} and "DEMO0002" not in all_text(values)
    assert [c["token"] for c in values["cargos"]] == ["[BL1]"]  # 가린 토큰으로 조회했다


def test_typed_answer_extends_this_turns_mask_table(agent_deps):
    ask = say(("ask_user", {"question": "다른 B/L도 있나요?", "options": TWO}))
    graph = agent_graph(agent_deps, ask, say())
    graph.invoke({"text": "DEMO0001 어디야?"}, cfg("a14b"))
    graph.invoke(Command(resume={"custom": "DEMO0002도 있어요"}), cfg("a14b"))
    values = graph.get_state(cfg("a14b")).values
    assert values["mask_map"] == {"[BL1]": "DEMO0001", "[BL2]": "DEMO0002"}  # 앞 번호를 덮어쓰지 않는다


def test_question_must_be_alone(agent_deps):
    mixed = say(
        ("ask_user", {"question": "어느 항구?", "options": TWO}), ("search_law", {"query": "장치기간"})
    )
    graph = agent_graph(agent_deps, mixed, say())
    out = graph.invoke({"text": "장치기간이 궁금해요"}, cfg("a15"))
    assert "__interrupt__" not in out  # 섞어 부르면 묻지 않고 오류로 돌려준다
    errors = [
        m for m in graph.get_state(cfg("a15")).values["messages"] if m.type == "tool" and m.status == "error"
    ]
    assert len(errors) == 2
    assert graph.get_state(cfg("a15")).values.get("evidence", []) == []  # 섞인 search_law는 돌지 않았다


def _card_graph(agent_deps, store, permission_mode="ask", name="건고추"):
    steps = (say(("check_reimport", {"facts": CHILI})), say(("save_item_card", {"name": name})), say())
    return agent_graph(agent_deps, *steps, store=store, permission_mode=permission_mode)


def test_saving_an_item_card_waits_for_approval(agent_deps):
    store = InMemoryStore()
    graph = _card_graph(agent_deps, store)
    out = graph.invoke({"text": "건고추 카드로 기억해 줘"}, cfg("a16"))
    request = out["__interrupt__"][0].value
    assert request["action_requests"][0]["name"] == "save_item_card"
    assert "농산물·임산물" in request["action_requests"][0]["description"]  # 카드에 저장될 사실이 보인다
    assert store.get(("users", "local", "items"), "건고추") is None  # 승인 전에는 저장하지 않는다
    graph.invoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg("a16"))
    assert store.get(("users", "local", "items"), "건고추").value["facts"]["category"] == "농산물·임산물"


def test_rejected_item_card_is_not_saved(agent_deps):
    store = InMemoryStore()
    graph = _card_graph(agent_deps, store)
    graph.invoke({"text": "건고추 카드로 기억해 줘"}, cfg("a17"))
    graph.invoke(Command(resume={"decisions": [{"type": "reject", "message": "저장하지 마"}]}), cfg("a17"))
    assert store.search(("users", "local", "items")) == []


def test_auto_mode_saves_without_asking(agent_deps):
    store = InMemoryStore()
    graph = _card_graph(agent_deps, store, permission_mode="auto")
    out = graph.invoke({"text": "건고추 카드로 기억해 줘"}, cfg("a18"))
    assert "__interrupt__" not in out and store.get(("users", "local", "items"), "건고추") is not None


def test_unknown_permission_mode_still_asks(agent_deps):
    store = InMemoryStore()
    graph = _card_graph(agent_deps, store, permission_mode="Auto")
    out = graph.invoke({"text": "건고추 카드로 기억해 줘"}, cfg("a18b"))
    assert "__interrupt__" in out and store.search(("users", "local", "items")) == []


def test_item_card_name_with_a_cargo_token_is_refused(agent_deps):
    store = InMemoryStore()
    graph = _card_graph(agent_deps, store, permission_mode="auto", name="[CARGO1] 건고추")
    graph.invoke({"text": "건고추 카드로 기억해 줘"}, cfg("a19"))
    assert store.search(("users", "local", "items")) == []


def test_out_of_domain_question_is_declined_by_code(agent_deps):
    def never(prompt):
        raise AssertionError("거절할 때는 작성자를 부르지 않는다")

    graph = agent_graph(agent_deps, say(("decline", {"reason": "날씨 질문"})), write=never)
    out = graph.invoke({"text": "내일 서울 날씨 어때?"}, cfg("a20"))
    assert out["answer"].startswith("이 질문은 Marvia가 도울 수 있는 범위 밖이에요.")
    assert "Marvia가 할 수 있는 일:" in out["answer"]
