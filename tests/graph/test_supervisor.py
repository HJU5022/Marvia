"""수퍼바이저 길(계획 7b) 시험. 가짜 도구 호출 모델로 키 없이 돈다.

[주의] 가짜 대본의 AIMessage와 tool_call id는 호출마다 새로 만든다. 같은 id를 다시 쓰면 대화 기록의
       add_messages가 덧붙이지 않고 바꿔서 루프가 일찍 끝난 것처럼 보인다 (11-12 사본 확인).
"""

import pytest
from conftest import UNIT
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from test_agent import CHILI, CITING, TWO, FailsAfter, FakeWatch, Inputs, ToolModel, cfg

from marvia.graph.main import build_main_graph
from marvia.tools.rules import load_rules


def call(name: str, args: dict, id: str) -> AIMessage:
    """도구 하나를 부르는 AIMessage. id는 대본 안에서 겹치지 않게 준다."""
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": id}])


def done(text: str = "") -> AIMessage:
    """도구 없이 루프를 끝내는 답."""
    return AIMessage(text)


def sup_graph(agent_deps, *messages: AIMessage, store=None, permission_mode="ask", **changes):
    """수퍼바이저 길 그래프. 수퍼바이저와 서브에이전트가 같은 가짜 모델을 쓴다.

    [왜] 한 단계에 한 노드만 모델을 부르므로 대본을 부르는 순서대로 한 줄로 적으면 된다.
    """
    deps = agent_deps(model=ToolModel(messages=iter(messages)), **changes)
    return build_main_graph(
        deps, InMemorySaver(), loop="supervisor", store=store, permission_mode=permission_mode
    )


def test_an_unknown_loop_name_is_refused(agent_deps):
    # [왜] 오타(superviser)가 조용히 계획자 길로 떨어지면 다른 길을 잰 줄 모른다
    with pytest.raises(ValueError, match="loop"):
        build_main_graph(agent_deps(), InMemorySaver(), loop="superviser")


def test_supervisor_path_needs_a_model(agent_deps):
    with pytest.raises(ValueError, match="AgentDeps.model"):
        build_main_graph(agent_deps(), InMemorySaver(), loop="supervisor")


def test_supervisor_that_calls_no_tool_goes_to_the_writer(agent_deps):
    graph = sup_graph(agent_deps, done())
    out = graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("s1"))
    values = graph.get_state(cfg("s1")).values
    assert out["answer"].startswith("시험 답이에요.")
    assert values["llm_calls"] == 2  # 수퍼바이저 1 + 작성자 1
    assert graph.config["recursion_limit"] == load_rules("agent")["loop"]["agent_recursion_limit"]


def test_supervisor_declines_an_out_of_scope_question_with_the_code_written_text(agent_deps):
    graph = sup_graph(agent_deps, call("decline", {"reason": "날씨 질문"}, "d1"))
    out = graph.invoke({"text": "내일 서울 날씨 어때요?"}, cfg("s2"))
    assert out["answer"].startswith(load_rules("agent")["scope"]["decline"])
    assert graph.get_state(cfg("s2")).values["llm_calls"] == 1  # 작성자를 부르지 않는다


def test_supervisor_asks_the_user_and_keeps_the_todo_list(agent_deps):
    todos = [{"content": "항구 확인", "status": "in_progress"}, {"content": "기한 정리", "status": "pending"}]
    script = [
        call("write_todos", {"todos": todos}, "t1"),
        call("ask_user", {"question": "어느 항구인가요?", "options": TWO}, "q1"),
        done(),
    ]
    graph = sup_graph(agent_deps, *script)
    out = graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("s3"))
    assert out["__interrupt__"][0].value["question"] == "어느 항구인가요?"
    out = graph.invoke(Command(resume={"selected": 1}), cfg("s3"))
    values = graph.get_state(cfg("s3")).values
    assert "answer" in out
    assert values["clarifications"] == ["어느 항구인가요? → 인천"]
    assert [t["content"] for t in values["todos"]] == ["항구 확인", "기한 정리"]


def test_supervisor_has_only_its_own_tools(agent_deps):
    from marvia.graph.supervisor import supervisor_tools

    names = [t.name for t in supervisor_tools(_all_tools(agent_deps))]
    assert names == load_rules("agent")["supervisor"]["tools"] == ["ask_user", "decline"]


def _all_tools(agent_deps):
    from marvia.graph.rag import build_rag_graph
    from marvia.graph.tools import make_tools

    deps = agent_deps()
    return make_tools(build_rag_graph(deps.rag), deps.today, deps.provision)


# --- 넘기기: handoff 도구, router, 서브에이전트 (계획 7b Task 2) ---


def hand(to: str, task: str, id: str) -> AIMessage:
    return call("handoff", {"to": to, "task": task}, id)


def shape(values: dict) -> list[tuple[str, str]]:
    """대화 기록의 (종류, 글 앞부분 또는 부른 도구 이름) 목록."""
    return [
        (m.type, ",".join(c["name"] for c in m.tool_calls) if getattr(m, "tool_calls", None) else m.text[:12])
        for m in values["messages"]
    ]


def test_handoff_runs_one_subagent_and_brings_back_its_keys_and_a_result_text(agent_deps):
    graph = sup_graph(
        agent_deps,
        hand("cargo", "[BL1]의 수입신고 기한을 계산", "h1"),
        call("calc_deadlines", {}, "c1"),  # 화물·기한 서브에이전트
        done("[BL1] 수입신고 기한은 2026-11-26이에요."),  # 서브에이전트의 결과 글
        done(),  # 수퍼바이저가 끝낸다
    )
    graph.invoke({"text": "DEMO0001 언제까지 수입신고 해야 해요?"}, cfg("h1"))
    values = graph.get_state(cfg("h1")).values
    assert values["calc"]["deadlines"][0]["due"] == "2026-11-26"
    # [왜] 서브에이전트 안의 도구 호출과 결과는 부모 기록에 들어오지 않는다.
    #      넘김 확인 글 자리에 결과 글만 남는다
    assert [kind for kind, _ in shape(values)] == ["human", "ai", "tool", "ai", "ai"]
    result = values["messages"][2]
    assert result.name == "handoff" and result.tool_call_id == "h1"
    assert result.text == "화물·기한 결과: [BL1] 수입신고 기한은 2026-11-26이에요."
    assert values["route"] == "" and values["task"] == ""


def test_a_subagent_sees_the_task_and_this_turns_message_but_not_the_earlier_conversation(agent_deps):
    inputs = Inputs()
    graph = sup_graph(
        agent_deps,
        done(),  # 첫 차례: 수퍼바이저가 바로 끝낸다
        hand("cargo", "[BL1]의 수입신고 기한을 계산", "h1"),  # 둘째 차례
        done("끝"),
        done(),
    )
    config = cfg("h2") | {"callbacks": [inputs]}
    graph.invoke({"text": "지난달 수입한 건고추 얘기예요"}, config)
    graph.invoke({"text": "DEMO0001 언제까지 수입신고 해야 해요?"}, config)
    _, supervisor_input, sub_input, _ = inputs.calls
    assert "지난달 수입한 건고추 얘기예요" in supervisor_input  # 수퍼바이저는 앞 차례를 본다
    assert "[BL1]의 수입신고 기한을 계산" in sub_input and "[BL1]: 반입신고" in sub_input
    # [왜] 이번 차례의 가린 글은 데이터로 준다. 사용자가 말한 사실을 넘김 문장에 옮기다 빠뜨리지 않게
    assert "<user_message>\n[BL1] 언제까지 수입신고 해야 해요?" in sub_input
    assert "DEMO0001" not in sub_input
    # 앞 차례의 대화와 수퍼바이저의 지시문은 넘기지 않는다
    assert "지난달 수입한 건고추" not in sub_input and "You are the supervisor" not in sub_input


def test_a_long_task_sentence_is_cut_to_the_rule(agent_deps):
    cap = load_rules("agent")["supervisor"]["max_task"]
    inputs = Inputs()
    graph = sup_graph(agent_deps, hand("cargo", "가" * (cap + 50), "h1"), done("끝"), done())
    graph.invoke({"text": "DEMO0001 어디쯤이에요?"}, cfg("h8") | {"callbacks": [inputs]})
    assert "가" * cap in inputs.calls[1] and "가" * (cap + 1) not in inputs.calls[1]


def test_two_subagents_in_one_turn_fill_the_same_notebook(agent_deps):
    graph = sup_graph(
        agent_deps,
        hand("cargo", "[BL1]의 수입신고 기한을 계산", "h1"),
        call("calc_deadlines", {}, "c1"),
        done("기한은 2026-11-26이에요."),
        hand("law", "수입신고 기한의 근거 조문", "h2"),
        call("search_law", {"query": "수입신고 기한"}, "s1"),
        done("관세법 제241조제3항이 30일을 정해요."),
        done(),
        write=lambda prompt: CITING,
    )
    out = graph.invoke({"text": "DEMO0001 언제까지 수입신고 해야 해요?"}, cfg("h3"))
    values = graph.get_state(cfg("h3")).values
    assert "관세법 > 제9장 통관 > 제241조" in out["answer"]
    assert values["calc"]["deadlines"] and [e["unit_id"] for e in values["evidence"]] == [UNIT.unit_id]
    # [왜] 법령 서브에이전트가 새로 찾은 조문은 결과 글 아래에 unit_id와 제목으로 붙는다 (조사 도구와 같다)
    assert values["messages"][4].text == (
        f"법령 조사 결과: 관세법 제241조제3항이 30일을 정해요.\n[{UNIT.unit_id}] {UNIT.heading}"
    )


def test_every_subagent_can_fetch_a_basis_label_itself(agent_deps):
    # [왜] 계산 도구가 낸 근거 이름표를 넘김 문장에 옮겨 적지 않아도 되게 한다 (경계 결정 11-12)
    groups = load_rules("agent")["supervisor"]["subagents"]
    assert list(groups) == ["cargo", "law", "item"]
    assert all("get_provision" in group["tools"] for group in groups.values())
    graph = sup_graph(
        agent_deps,
        hand("item", "수입신고 기한 근거 조문 확인", "h1"),
        call("get_provision", {"label": "관세법 제241조제3항"}, "p1"),
        done("찾았어요."),
        done(),
    )
    graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("h4"))
    assert [e["unit_id"] for e in graph.get_state(cfg("h4")).values["evidence"]] == [UNIT.unit_id]


def test_handoff_called_with_another_tool_is_refused_and_asked_again(agent_deps):
    both = AIMessage(
        "",
        tool_calls=[
            {"name": "handoff", "args": {"to": "cargo", "task": "조회"}, "id": "x1"},
            {"name": "decline", "args": {"reason": "날씨"}, "id": "x2"},
        ],
    )
    graph = sup_graph(agent_deps, both, hand("cargo", "[BL1] 기한 계산", "h1"), done("끝"), done())
    out = graph.invoke({"text": "DEMO0001 언제까지 수입신고 해야 해요?"}, cfg("h5"))
    values = graph.get_state(cfg("h5")).values
    assert "answer" in out and not values["out_of_scope"]  # 함께 부른 decline은 돌지 않았다
    assert [m.status for m in values["messages"] if m.type == "tool"] == ["error", "error", "success"]


def test_an_unknown_subagent_name_goes_back_to_the_supervisor(agent_deps):
    graph = sup_graph(
        agent_deps, hand("customs", "조회", "h0"), hand("cargo", "[BL1] 기한 계산", "h1"), done("끝"), done()
    )
    graph.invoke({"text": "DEMO0001 언제까지 수입신고 해야 해요?"}, cfg("h6"))
    tools = [m for m in graph.get_state(cfg("h6")).values["messages"] if m.type == "tool"]
    assert tools[0].status == "error" and "cargo, law, item" in tools[0].text
    assert tools[1].text == "화물·기한 결과: 끝"


def test_a_long_result_text_is_cut_to_the_rule(agent_deps):
    cap = load_rules("agent")["supervisor"]["max_result"]
    graph = sup_graph(agent_deps, hand("cargo", "조회", "h1"), done("가" * (cap + 50)), done())
    graph.invoke({"text": "DEMO0001 어디쯤이에요?"}, cfg("h7"))
    result = graph.get_state(cfg("h7")).values["messages"][2]
    assert result.text == "화물·기한 결과: " + "가" * cap


# --- 상한 공유: 수퍼바이저와 서브에이전트가 같은 호출 수와 검색 기록을 쓴다 (계획 7b Task 3) ---

CAP = load_rules("agent")["loop"]["max_llm_calls"]
PROVISION = {"label": "관세법 제241조제3항"}


def test_supervisor_and_subagent_calls_stop_exactly_at_the_shared_cap(agent_deps):
    # 수퍼바이저 1 + 서브에이전트 1을 끝없이 되풀이하는 대본
    script = [m for i in range(CAP) for m in (hand("cargo", "조회", f"h{i}"), done(f"끝{i}"))]
    inputs = Inputs()
    graph = sup_graph(agent_deps, *script)
    out = graph.invoke({"text": "DEMO0001 어디쯤이에요?"}, cfg("c1") | {"callbacks": [inputs]})
    values = graph.get_state(cfg("c1")).values
    assert len(inputs.calls) == CAP  # 실제로 모델을 부른 횟수도 상한과 같다
    assert values["llm_calls"] == CAP and values["stopped"] == "llm_calls"
    assert values["failed_tools"] == [{"tool": "supervisor", "message": f"LLM 호출 한도({CAP}회)에 닿았어요"}]
    assert "끝까지 확인하지 못했어요" in out["answer"]  # 부분 답


def test_a_subagent_that_hits_the_cap_ends_the_turn_without_another_supervisor_call(agent_deps):
    # 수퍼바이저 1 + 화물 서브에이전트 19에서 상한.
    # 대본이 거기서 끝나므로 수퍼바이저를 또 부르면 시험이 죽는다
    script = [hand("cargo", "기한 계산", "h1")] + [
        call("calc_deadlines", {}, f"k{i}") for i in range(CAP - 1)
    ]
    graph = sup_graph(agent_deps, *script)
    out = graph.invoke({"text": "DEMO0001 어디쯤이에요?"}, cfg("c2"))
    values = graph.get_state(cfg("c2")).values
    assert values["llm_calls"] == CAP and values["stopped"] == "llm_calls"
    assert values["failed_tools"] == [{"tool": "cargo", "message": f"LLM 호출 한도({CAP}회)에 닿았어요"}]
    assert "끝까지 확인하지 못했어요" in out["answer"]


@pytest.mark.parametrize("before, searched", [(10, 2), (11, 0)])
def test_the_search_refusal_boundary_holds_inside_the_law_subagent(agent_deps, before, searched):
    # 수퍼바이저 1 + 법령 모델 before번 뒤, 다음 법령 모델 호출이 검색 둘을 한꺼번에 부른다.
    # 그 호출까지 1 + before + 1번. 검색 둘의 최악(4 x 2)을 더해 상한을 넘으면 둘 다 거절한다
    # (에이전트 길과 같다)
    two = AIMessage(
        "",
        tool_calls=[
            {"name": "search_law", "args": {"query": "수입신고 기한"}, "id": "s1"},
            {"name": "search_law", "args": {"query": "반입신고"}, "id": "s2"},
        ],
    )
    law = [call("get_provision", PROVISION, f"p{i}") for i in range(before)] + [two, done("끝")]
    graph = sup_graph(agent_deps, hand("law", "수입신고 기한 근거", "h1"), *law, done())
    graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg(f"c3-{before}"))
    values = graph.get_state(cfg(f"c3-{before}")).values
    assert len(values["searched"]) == searched
    assert values["llm_calls"] <= CAP + load_rules("agent")["answer"]["max_write_attempts"]


def test_the_search_cap_and_seen_queries_carry_across_subagent_runs(agent_deps):
    limit = load_rules("agent")["loop"]["max_searches"]
    script = []
    for i in range(limit + 1):  # 법령 서브에이전트를 네 번 부르고 매번 새 질의 하나를 찾는다
        script += [
            hand("law", f"질의 {i}", f"h{i}"),
            call("search_law", {"query": f"질의 {i}"}, f"s{i}"),
            done(f"끝{i}"),
        ]
    graph = sup_graph(agent_deps, *script, done())
    graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("c4"))
    values = graph.get_state(cfg("c4")).values
    assert values["searched"] == [f"질의 {i}" for i in range(limit)]  # 넷째 검색은 거절됐다


def test_a_model_failure_inside_a_subagent_ends_in_a_partial_answer(agent_deps):
    model = FailsAfter(messages=iter([hand("cargo", "조회", "h1")]))
    graph = build_main_graph(agent_deps(model=model), InMemorySaver(), loop="supervisor")
    out = graph.invoke({"text": "DEMO0001 어디쯤이에요?"}, cfg("c5"))
    values = graph.get_state(cfg("c5")).values
    assert values["stopped"] == "llm_failed"
    assert values["failed_tools"] == [{"tool": "cargo", "message": "APIConnectionError"}]
    assert "끝까지 확인하지 못했어요" in out["answer"]


# --- 승인: 부작용 도구는 서브에이전트 안에서도 승인 뒤 한 번만 돈다 (계획 7b Task 4) ---

APPROVE = Command(resume={"decisions": [{"type": "approve"}]})
REJECT = Command(resume={"decisions": [{"type": "reject"}]})


def card_script() -> list[AIMessage]:
    """품목 서브에이전트가 재수입 판정 뒤 품목 카드를 저장하는 대본 (모델 호출 다섯 번)."""
    return [
        hand("item", "건고추 재수입 검사 판정 뒤 품목 카드로 저장", "h1"),
        call("check_reimport", {"facts": CHILI}, "r1"),
        call("save_item_card", {"name": "건고추"}, "v1"),
        done("저장했어요."),
        done(),
    ]


@pytest.mark.parametrize("resume, saved", [(APPROVE, True), (REJECT, False)])
def test_an_approval_inside_a_subagent_reaches_the_user_and_runs_once(agent_deps, monkeypatch, resume, saved):
    from marvia.graph import tools

    checks = []  # check_reimport가 계산 코드를 부른 횟수
    real = tools.reimport_check
    monkeypatch.setattr(tools, "reimport_check", lambda *a, **k: checks.append(1) or real(*a, **k))
    inputs = Inputs()
    store = InMemoryStore()
    graph = sup_graph(agent_deps, *card_script(), store=store)
    config = cfg(f"p1-{saved}") | {"callbacks": [inputs]}
    out = graph.invoke({"text": "건고추 카드로 기억해 줘"}, config)
    requests = out["__interrupt__"][0].value["action_requests"]
    assert len(out["__interrupt__"]) == 1 and [r["name"] for r in requests] == ["save_item_card"]
    assert store.get(("users", "local", "items"), "건고추") is None  # 승인 전에는 저장하지 않는다
    out = graph.invoke(resume, config)
    values = graph.get_state(config).values
    assert "answer" in out and "__interrupt__" not in out
    assert (store.get(("users", "local", "items"), "건고추") is not None) is saved
    assert values["actions"] == (["품목 카드 '건고추' 저장"] if saved else [])
    # [왜] 이어 갈 때 앞에서 끝난 도구와 모델 호출이 다시 돌지 않는다
    assert len(checks) == 1 and len(inputs.calls) == 5 and values["llm_calls"] == 5 + 1  # + 작성자


def test_an_edited_card_name_is_saved_from_inside_the_subagent(agent_deps):
    store = InMemoryStore()
    graph = sup_graph(agent_deps, *card_script(), store=store)
    graph.invoke({"text": "건고추 카드로 기억해 줘"}, cfg("p2"))
    edit = {"type": "edit", "edited_action": {"name": "save_item_card", "args": {"name": "고추"}}}
    graph.invoke(Command(resume={"decisions": [edit]}), cfg("p2"))
    assert store.get(("users", "local", "items"), "건고추") is None
    assert store.get(("users", "local", "items"), "고추").value["facts"]["category"] == "농산물·임산물"


class Watch(FakeWatch):
    """감시 목록 가짜에 지우기를 더한다 (unwatch_cargo 도구가 생긴다)."""

    def __init__(self):
        super().__init__()
        self.removed: list[tuple[str, str]] = []

    def deps(self):
        from dataclasses import replace

        return replace(
            super().deps(), remove=lambda user, number: self.removed.append((user, number)) or True
        )


SIDE_EFFECTS = {
    # 도구 → (서브에이전트, 그 도구를 부르기 전의 대본, 인자)
    "save_item_card": ("item", [call("check_reimport", {"facts": CHILI}, "r1")], {"name": "건고추"}),
    "save_preference": ("item", [], {"depth": "짧게"}),
    "watch_cargo": ("cargo", [], {"token": "[BL1]"}),
    "unwatch_cargo": ("cargo", [], {"token": "[BL1]"}),
}


def done_things(store, watch) -> list:
    """부작용이 실제로 일어난 흔적: 저장한 품목 카드와 설정, 감시 목록에 넣은 것과 뺀 것."""
    return [
        *store.search(("users", "local", "items")),
        *store.search(("users", "local", "prefs")),
        *watch.added,
        *watch.removed,
    ]


@pytest.mark.parametrize("mode", ["ask", "auto"])
@pytest.mark.parametrize("name", list(SIDE_EFFECTS))
def test_no_side_effect_tool_runs_without_approval_on_the_supervisor_path(agent_deps, name, mode):
    # [왜] rules/agent.yaml approval.always_ask의 도구는 어느 승인 모드에서도, 어느 서브에이전트 안에서도
    #      승인 전에 돌면 안 된다 (설계 8절·12절). 사전 등록 비교의 "승인 없는 부작용 0"은 이 시험이 본다
    assert sorted(SIDE_EFFECTS) == sorted(load_rules("agent")["approval"]["always_ask"])
    sub, before, args = SIDE_EFFECTS[name]
    store, watch = InMemoryStore(), Watch()
    script = [hand(sub, "사용자가 부탁한 일", "h1"), *before, call(name, args, "x1"), done("했어요."), done()]
    graph = sup_graph(agent_deps, *script, store=store, permission_mode=mode, watch=watch.deps())
    config = cfg(f"p3-{name}-{mode}")
    out = graph.invoke({"text": "DEMO0001 부탁해요"}, config)
    assert [r["name"] for r in out["__interrupt__"][0].value["action_requests"]] == [name]
    assert done_things(store, watch) == []  # 승인 전
    graph.invoke(REJECT, config)
    assert done_things(store, watch) == []  # 거절하면 끝까지 돌지 않는다
    assert graph.get_state(config).values["actions"] == []


def test_the_approval_card_of_a_subagent_shows_tokens_only(agent_deps):
    watch = Watch()
    script = [hand("cargo", "[BL1] 감시 등록", "h1"), call("watch_cargo", {"token": "[BL1]"}, "w1")]
    graph = sup_graph(agent_deps, *script, done("넣었어요."), done(), watch=watch.deps())
    out = graph.invoke({"text": "DEMO0001 계속 지켜봐 줘"}, cfg("p4"))
    assert "DEMO0001" not in str(out["__interrupt__"][0].value)
    graph.invoke(APPROVE, cfg("p4"))
    assert watch.added == [("local", "DEMO0001", "반입신고")]  # 한 번만 넣었다


# --- 방문 기록: 어느 서브에이전트가 어떤 도구를 불렀나 (계획 7b Task 7, 평가 실행기가 읽는다) ---


def test_each_subagent_run_is_recorded_with_the_tools_it_called(agent_deps):
    graph = sup_graph(
        agent_deps,
        hand("cargo", "[BL1]의 수입신고 기한을 계산", "h1"),
        call("calc_deadlines", {}, "c1"),
        call("get_provision", PROVISION, "p1"),
        done("기한은 2026-11-26이에요."),
        hand("law", "수입신고 기한의 근거 조문", "h2"),
        done("이미 찾은 조문이 있어요."),  # 도구 없이 끝낸 방문도 남는다
        done(),
        done(),  # 둘째 차례의 수퍼바이저
    )
    graph.invoke({"text": "DEMO0001 언제까지 수입신고 해야 해요?"}, cfg("v1"))
    # [왜] 서브에이전트 안의 도구 호출은 부모 대화 기록에 없다. 이 칸이 없으면 평가가 도구 순서를 못 본다
    assert graph.get_state(cfg("v1")).values["visits"] == [
        {"sub": "cargo", "tools": ["calc_deadlines", "get_provision"]},
        {"sub": "law", "tools": []},
    ]
    graph.invoke({"text": "고마워요"}, cfg("v1"))
    assert graph.get_state(cfg("v1")).values["visits"] == []  # 차례마다 비운다
