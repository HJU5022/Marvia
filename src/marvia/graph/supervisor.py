"""수퍼바이저 길: 수퍼바이저가 일을 서브에이전트에 나눠 맡긴다 (계획 7b, MARVIA_LOOP=supervisor).

수퍼바이저는 할 일 목록, 사용자 질문(ask_user), 도메인 밖 거절(decline), 넘기기(handoff)만 가진
create_agent 루프다. handoff는 넘길 곳(route)과 일 문장(task)만 공책에 쓰고 루프를 끝낸다. 메인 그래프의
router 노드가 그 값을 보고 Command(goto)로 서브에이전트 노드에 보낸다. 서브에이전트 노드(sub_node)는
서브에이전트를 따로 불러 일 문장, 화물 줄, 이번 차례의 가린 사용자 글만 주고, 공책 칸과 짧은 결과 글만
돌려준다.
하지 않는 일: 답 쓰기와 검증. 에이전트 길과 같이 루프가 끝나면 메인 그래프의 작성자와 검증자가 한다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
from langchain.tools import ToolRuntime, tool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from marvia.graph.agent import Guards
from marvia.graph.answer import cargo_lines
from marvia.graph.state import LoopState, MarviaState
from marvia.prompts import render
from marvia.tools.rules import load_rules

# 수퍼바이저가 다른 도구와 함께 부를 수 없는 도구
# [왜] handoff는 넘길 곳을 공책 칸 하나(route)에 쓴다. 한 단계에 둘이면 하나가 사라진다.
#      ask_user는 에이전트 길과 같은 까닭이다(재개할 때 함께 부른 도구가 다시 돈다)
ALONE = ("ask_user", "handoff")
ASK_ALONE = (
    "ask_user와 handoff는 다른 도구 없이 혼자 불러야 해요. "
    "한 번에 서브에이전트 하나에게만 넘기고, 부를 때는 그 도구 하나만 부르세요."
)
# 서브에이전트에게 넘겨주고 돌려받는 공책 칸. 대화 기록(messages)은 넘기지 않는다
# [주의] 가림 표(mask_map)는 넘겨주기만 한다. 서브에이전트의 도구는 읽기만 하고, 쓰는 도구(ask_user)는
#        수퍼바이저에만 있다
HANDED = ("cargos", "evidence", "gaps", "calc", "item", "official", "actions", "failed_tools", "assumptions")


def subagents() -> dict[str, dict]:
    """서브에이전트 이름 → {label, tools} (rules/agent.yaml supervisor.subagents)."""
    return load_rules("agent")["supervisor"]["subagents"]


def supervisor_tools(tools: list) -> list:
    """에이전트 도구 목록에서 수퍼바이저가 직접 부르는 도구만 고른다 (rules/agent.yaml supervisor.tools)."""
    by_name = {tool.name: tool for tool in tools}
    return [by_name[name] for name in load_rules("agent")["supervisor"]["tools"]]


def handoff_tool():
    """넘기기 도구 handoff를 만든다. 서브에이전트를 부르지 않고 넘길 곳과 일 문장만 공책에 쓴다."""
    names = list(subagents())
    max_task = load_rules("agent")["supervisor"]["max_task"]

    # [왜] return_direct: 이 도구를 부르면 수퍼바이저 루프가 정상으로 끝나고, 그 뒤 router 노드가 보낸다.
    #      도구가 부모 그래프로 바로 건너뛰면(Command(goto, graph=PARENT)) 수퍼바이저의 메시지, 호출 수,
    #      할 일 목록이 부모 공책에 오지 않는다 (11-12 사본 확인)
    @tool(return_direct=True)
    def handoff(to: str, task: str, runtime: ToolRuntime) -> Command:
        """Hand one task to one helper and get its short result back. Call it alone.
        to: "cargo" (cargo status, deadlines, watch list), "law" (what the statutes say) or "item"
        (re-import inspection, remembered items and preferences).
        task: one Korean sentence that stands on its own, with cargo tokens such as [BL1] as they are.
        """
        if to not in names:
            # [왜] 모르는 이름이면 넘기지 않는다. route가 비어 router가 수퍼바이저를 다시 부르고,
            #      모델이 이 오류 글을 보고 고쳐 부른다
            text = f"모르는 서브에이전트예요: {to}. {', '.join(names)} 가운데 하나를 쓰세요."
            error = ToolMessage(text, tool_call_id=runtime.tool_call_id, status="error")
            return Command(update={"messages": [error]})
        ack = ToolMessage(f"{to}에게 넘김", tool_call_id=runtime.tool_call_id)
        return Command(update={"route": to, "task": task[:max_task], "messages": [ack]})

    return handoff


def build_supervisor(model: BaseChatModel, tools: list):
    """수퍼바이저 루프를 만든다. 상한과 혼자 부를 도구 규칙은 에이전트 길과 같은 Guards가 지킨다."""
    cfg = load_rules("agent")
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        TodoListMiddleware(system_prompt=render("todos_system"), tool_description=render("todos_tool")),
        # [왜] label은 실패 기록(failed_tools)에 남는 이름이다. 어느 루프가 상한에 닿았는지 보인다
        Guards(cfg["loop"]["max_llm_calls"], label="supervisor", alone=ALONE, alone_text=ASK_ALONE),
    ]
    return create_agent(
        model,
        [*supervisor_tools(tools), handoff_tool()],
        system_prompt=render("supervisor"),
        middleware=middleware,
        state_schema=LoopState,
        name="supervisor",
    )


def refused_handoff(state: MarviaState) -> bool:
    """수퍼바이저가 방금 handoff를 불렀는데 넘길 곳이 정해지지 않았나 (모르는 이름, 틀린 인자)."""
    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    return isinstance(last, ToolMessage) and last.name == "handoff" and not state.get("route")


def build_sub(model: BaseChatModel, tools: list, name: str):
    """서브에이전트 하나를 만든다: 자기 묶음의 도구만 가진 루프 (rules/agent.yaml supervisor.subagents)."""
    cfg = load_rules("agent")
    by_name = {tool.name: tool for tool in tools}
    # [주의] 승인이 필요한 도구는 승인 미들웨어를 붙이기 전에는 주지 않는다 (계획 7b Task 4에서 붙인다)
    gated = cfg["approval"]["ask"] + cfg["approval"]["always_ask"]
    # [왜] 바깥 기능이 없어 만들어지지 않은 도구(감시 목록, 공식 조회)는 건너뛴다. 에이전트 길과 같다
    own = [by_name[n] for n in subagents()[name]["tools"] if n in by_name and n not in gated]
    return create_agent(
        model,
        own,
        system_prompt=render(f"sub_{name}"),
        middleware=[Guards(cfg["loop"]["max_llm_calls"], label=name)],
        state_schema=LoopState,
        name=name,
    )


# [주의] 돌려주는 타입을 Callable로 적지 않는다. add_node 타입 검사가 거절한다 (main.py의 shown과 같다)
def sub_node(name: str, sub, today: Callable[[], date]):
    """서브에이전트를 메인 그래프의 노드 함수로 감싼다."""
    spec = load_rules("agent")["supervisor"]
    label, max_result = spec["subagents"][name]["label"], spec["max_result"]

    def run(state: MarviaState) -> dict:
        """서브에이전트를 따로 불러 일 문장과 이번 차례의 글만 주고, 공책 칸과 결과 글만 돌려준다."""
        # [주의] 승인으로 멈췄다 이어 가면 이 함수가 처음부터 다시 돈다.
        #        sub.invoke 앞에는 바깥 일을 두지 않는다
        turn = render(
            "sub_turn",
            today=today().isoformat(),
            cargos="\n".join(cargo_lines(state.get("cargos", []))),
            # [왜] 사용자가 말한 사실(날짜, 품목, 같은 칸)을 수퍼바이저가 한 문장으로 옮기다 빠뜨리지 않게
            #      이번 차례의 가린 글을 데이터로 함께 준다.
            #      앞 차례의 대화와 다른 서브에이전트의 결과는 주지 않는다
            question=state.get("masked_text", ""),
            task=state.get("task", ""),
        )
        values: dict[str, Any] = dict(state)
        start = {key: values[key] for key in HANDED if key in values}
        start |= {"mask_map": values.get("mask_map", {}), "messages": [HumanMessage(turn)]}
        out = sub.invoke(start)
        last = out["messages"][-1]
        text = str(last.text)[:max_result] if last.type == "ai" else ""
        had = {e["unit_id"] for e in state.get("evidence", [])}
        lines = [f"{label} 결과: {text or '결과 글이 없어요'}"]
        # [왜] 수퍼바이저에게는 새로 찾은 조문의 unit_id와 제목만 준다. 본문은 작성자가 evidence 칸에서 읽는다
        lines += [
            f"[{e['unit_id']}] {e['heading']}" for e in out.get("evidence", []) if e["unit_id"] not in had
        ]
        ack = next(m for m in reversed(values["messages"]) if m.type == "tool" and m.name == "handoff")
        # [왜] 넘김 확인 글과 같은 id로 돌려주면 add_messages가 그 글을 결과 글로 바꾼다. 수퍼바이저 기록에는
        #      "도구 호출 → 도구 결과" 짝만 남고, 서브에이전트 안의 메시지는 들어오지 않는다
        result = ToolMessage("\n".join(lines), tool_call_id=ack.tool_call_id, name="handoff", id=ack.id)
        # [왜] 부모 공책 칸은 덮어쓰기다. 서브에이전트는 받은 값에 자기 것을 합친 전체 값을 돌려주므로
        #      그대로 넣으면 된다(부모 칸에 더하기 reducer를 달면 받은 값이 두 번 더해진다, 11-12 사본 확인)
        update: dict[str, Any] = {key: out[key] for key in HANDED if key in out}
        return update | {"messages": [result], "route": "", "task": ""}

    return run
