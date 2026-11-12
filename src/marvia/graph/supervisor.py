"""수퍼바이저 길: 수퍼바이저가 일을 서브에이전트에 나눠 맡긴다 (계획 7b, MARVIA_LOOP=supervisor).

수퍼바이저는 할 일 목록, 사용자 질문(ask_user), 도메인 밖 거절(decline)만 가진 create_agent 루프다.
하지 않는 일: 답 쓰기와 검증. 에이전트 길과 같이 루프가 끝나면 메인 그래프의 작성자와 검증자가 한다.
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
from langchain_core.language_models import BaseChatModel

from marvia.graph.agent import Guards
from marvia.graph.state import LoopState
from marvia.prompts import render
from marvia.tools.rules import load_rules


def supervisor_tools(tools: list) -> list:
    """에이전트 도구 목록에서 수퍼바이저가 직접 부르는 도구만 고른다 (rules/agent.yaml supervisor.tools)."""
    by_name = {tool.name: tool for tool in tools}
    return [by_name[name] for name in load_rules("agent")["supervisor"]["tools"]]


def build_supervisor(model: BaseChatModel, tools: list):
    """수퍼바이저 루프를 만든다. 상한과 혼자 부를 도구 규칙은 에이전트 길과 같은 Guards가 지킨다."""
    cfg = load_rules("agent")
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        TodoListMiddleware(system_prompt=render("todos_system"), tool_description=render("todos_tool")),
        # [왜] label은 실패 기록(failed_tools)에 남는 이름이다. 어느 루프가 상한에 닿았는지 보인다
        Guards(cfg["loop"]["max_llm_calls"], label="supervisor"),
    ]
    return create_agent(
        model,
        supervisor_tools(tools),
        system_prompt=render("supervisor"),
        middleware=middleware,
        state_schema=LoopState,
        name="supervisor",
    )
