"""에이전트 루프: 모델이 도메인 도구를 골라 부르고, 더 부를 도구가 없으면 끝난다 (계획 3c, 설계 6.1).

루프 자체(모델 호출, 병렬 도구 실행, 할 일 목록, 승인 멈춤, 도구별 호출 상한)는 LangChain create_agent와
기본 미들웨어가 하고, 도메인 규칙은 이 파일의 Guards가 지킨다.
하지 않는 일: 답 쓰기와 검증. 루프가 끝나면 메인 그래프의 작성자 → 검증자가
공책 칸(evidence, calc)으로 답을 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.types import Command

from marvia.graph.state import LoopState
from marvia.prompts import render


class Guards(AgentMiddleware[LoopState]):
    """도메인 규칙 미들웨어: LLM 호출 수 세기."""

    # [왜] 이 미들웨어가 읽고 쓰는 칸(llm_calls, stopped, failed_tools)을 루프 공책에 더한다
    state_schema = LoopState

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse | AIMessage | ExtendedModelResponse:
        """모델 호출 한 번을 감싼다: 호출 수를 센다."""
        response = handler(request)
        return ExtendedModelResponse(model_response=response, command=Command(update={"llm_calls": 1}))


def build_agent(model: BaseChatModel, tools: list):
    """에이전트 루프를 만든다."""
    middleware: list[AgentMiddleware[Any, Any, Any]] = [Guards()]
    return create_agent(
        model,
        tools,
        system_prompt=render("agent"),
        middleware=middleware,
        state_schema=LoopState,
        name="agent",
    )
