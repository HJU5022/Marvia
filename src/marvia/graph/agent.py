"""에이전트 루프: 모델이 도메인 도구를 골라 부르고, 더 부를 도구가 없으면 끝난다 (계획 3c, 설계 6.1).

루프 자체(모델 호출, 병렬 도구 실행, 할 일 목록, 승인 멈춤, 도구별 호출 상한)는 LangChain create_agent와
기본 미들웨어가 하고, 도메인 규칙은 이 파일의 Guards가 지킨다.
하지 않는 일: 답 쓰기와 검증. 루프가 끝나면 메인 그래프의 작성자 → 검증자가
공책 칸(evidence, calc)으로 답을 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anthropic
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
    TodoListMiddleware,
    ToolCallLimitMiddleware,
    hook_config,
)
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from marvia.graph.state import LoopState
from marvia.prompts import render
from marvia.tools.rules import load_rules

ONE_IN_PROGRESS = (
    "할 일 목록에는 끝나지 않은 일이 있으면 in_progress가 정확히 하나여야 해요. 목록을 고쳐 다시 부르세요."
)


class Guards(AgentMiddleware[LoopState]):
    """도메인 규칙 미들웨어: LLM 호출 상한, LLM 실패 기록, 진행 중 할 일 하나."""

    # [왜] 이 미들웨어가 읽고 쓰는 칸(llm_calls, stopped, failed_tools)을 루프 공책에 더한다
    state_schema = LoopState

    def __init__(self, max_llm_calls: int):
        super().__init__()
        self.max_llm_calls = max_llm_calls

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: LoopState, runtime: Any) -> dict[str, Any] | None:
        """모델을 부르기 전: 이번 차례 LLM 호출 수(RAG 안의 호출 포함)가 상한이면 루프를 끝낸다 (설계 6.4)."""
        if state.get("llm_calls", 0) < self.max_llm_calls:
            return None
        failed = [{"tool": "agent", "message": f"LLM 호출 한도({self.max_llm_calls}회)에 닿았어요"}]
        # [왜] jump_to="end": 모델을 부르지 않고 루프를 끝낸다. 메인 그래프가 stopped를 보고 부분 답으로 간다
        return {"stopped": "llm_calls", "failed_tools": failed, "jump_to": "end"}

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse | AIMessage | ExtendedModelResponse:
        """모델 호출 한 번을 감싼다: 호출 수를 세고, API 오류·모양 오류면 기록하고 루프를 끝낸다."""
        try:
            response = handler(request)
        except (anthropic.APIError, OutputParserException) as error:
            # [주의] 오류 종류 이름과 상태 코드만 남긴다. 오류 글에는 요청 내용이 섞일 수 있다
            #        (llm.structured와 같은 규칙)
            status = getattr(error, "status_code", None)
            name = f"{type(error).__name__}({status})" if status else type(error).__name__
            update = {
                "llm_calls": 1,
                "stopped": "llm_failed",
                "failed_tools": [{"tool": "agent", "message": name}],
            }
            # [왜] 도구 호출이 없는 빈 답을 돌려주면 루프가 끝난다. 상태 칸은 Command로 함께 쓴다
            return ExtendedModelResponse(
                model_response=ModelResponse(result=[AIMessage(content="")]), command=Command(update=update)
            )
        return ExtendedModelResponse(model_response=response, command=Command(update={"llm_calls": 1}))

    def wrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]
    ) -> ToolMessage | Command:
        """할 일 목록을 쓸 때 끝나지 않은 일이 있으면 in_progress가 정확히 하나인지 본다 (설계 6.2)."""
        call = request.tool_call
        if call["name"] == "write_todos":
            todos = call["args"].get("todos", [])
            open_items = [todo for todo in todos if todo.get("status") != "completed"]
            in_progress = sum(todo.get("status") == "in_progress" for todo in todos)
            # [왜] TodoListMiddleware는 진행 중 개수를 검사하지 않는다 (11-06 소스 확인).
            #      화면이 "지금 하는 일"을 하나로 보여 준다
            if open_items and in_progress != 1:
                return ToolMessage(ONE_IN_PROGRESS, tool_call_id=call["id"], status="error")
        return handler(request)


def build_agent(model: BaseChatModel, tools: list):
    """에이전트 루프를 만든다."""
    cfg = load_rules("agent")
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        TodoListMiddleware(),
        # [왜] 같은 차례에 법령 검색은 이 횟수까지. 넘는 호출은 오류 결과를 받고 모델이 다음 일을 고른다
        ToolCallLimitMiddleware(
            tool_name="search_law", run_limit=cfg["loop"]["max_searches"], exit_behavior="continue"
        ),
        Guards(cfg["loop"]["max_llm_calls"]),
    ]
    return create_agent(
        model,
        tools,
        system_prompt=render("agent"),
        middleware=middleware,
        state_schema=LoopState,
        name="agent",
    )
