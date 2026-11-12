"""수퍼바이저 길(계획 7b) 시험. 가짜 도구 호출 모델로 키 없이 돈다.

[주의] 가짜 대본의 AIMessage와 tool_call id는 호출마다 새로 만든다. 같은 id를 다시 쓰면 대화 기록의
       add_messages가 덧붙이지 않고 바꿔서 루프가 일찍 끝난 것처럼 보인다 (11-12 사본 확인).
"""

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from test_agent import TWO, ToolModel, cfg

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
