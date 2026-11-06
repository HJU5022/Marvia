"""에이전트 루프: 모델이 도메인 도구를 골라 부르고, 더 부를 도구가 없으면 끝난다 (계획 3c, 설계 6.1).

루프 자체(모델 호출, 병렬 도구 실행, 할 일 목록, 승인 멈춤, 도구별 호출 상한)는 LangChain create_agent와
기본 미들웨어가 하고, 도메인 규칙은 이 파일의 Guards가 지킨다.
하지 않는 일: 답 쓰기와 검증. 루프가 끝나면 메인 그래프의 작성자 → 검증자가
공책 칸(evidence, calc)으로 답을 쓴다.
긴 대화 요약기(build_summary)도 여기서 만들지만, 부르는 곳은 메인 그래프의 brief 노드다 (계획 3d).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import anthropic
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ExtendedModelResponse,
    HumanInTheLoopMiddleware,
    InterruptOnConfig,
    ModelRequest,
    ModelResponse,
    SummarizationMiddleware,
    TodoListMiddleware,
    ToolCallLimitMiddleware,
    hook_config,
)
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, ToolCall, ToolMessage, get_buffer_string
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from marvia.graph.state import LoopState
from marvia.prompts import render
from marvia.tools.rules import load_rules

# [왜] 모델 호출 실패로 보는 오류: API 오류와 구조화 출력 모양 오류
MODEL_ERRORS = (anthropic.APIError, OutputParserException)
ASK_ALONE = (
    "ask_user는 다른 도구 없이 혼자 불러야 해요. "
    "묻기 전에 할 일이 있으면 먼저 하고, 물을 때는 ask_user만 부르세요."
)
ONE_IN_PROGRESS = (
    "할 일 목록에는 끝나지 않은 일이 있으면 in_progress가 정확히 하나여야 해요. 목록을 고쳐 다시 부르세요."
)


class Guards(AgentMiddleware[LoopState]):
    """도메인 규칙 미들웨어: LLM 호출 상한, LLM 실패 기록, ask_user 혼자 부르기, 진행 중 할 일 하나."""

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

    @staticmethod
    def _failed(error: Exception) -> ExtendedModelResponse:
        """API 오류·모양 오류를 기록하고 루프를 끝내는 응답 (동기·비동기가 함께 쓴다)."""
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

    @staticmethod
    def _counted(response: Any) -> ExtendedModelResponse:
        """성공한 모델 호출에 호출 수 1을 붙인다."""
        return ExtendedModelResponse(model_response=response, command=Command(update={"llm_calls": 1}))

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse | AIMessage | ExtendedModelResponse:
        """모델 호출 한 번을 감싼다: 호출 수를 세고, API 오류·모양 오류면 기록하고 루프를 끝낸다."""
        try:
            return self._counted(handler(request))
        except MODEL_ERRORS as error:
            return self._failed(error)

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse | AIMessage | ExtendedModelResponse:
        """wrap_model_call의 비동기 짝. [왜] ainvoke에서는 이 이름만 불린다 (langchain 미들웨어 소스 확인)."""
        try:
            return self._counted(await handler(request))
        except MODEL_ERRORS as error:
            return self._failed(error)

    @hook_config(can_jump_to=["model"])
    def after_model(self, state: LoopState, runtime: Any) -> dict[str, Any] | None:
        """모델이 ask_user를 다른 도구와 함께 불렀으면 모두 오류로 돌려주고 다시 부른다."""
        # [왜] 다른 미들웨어가 오류 결과를 먼저 붙여도 마지막 모델 메시지를 본다
        last = next((m for m in reversed(state["messages"]) if m.type == "ai"), None)
        calls = getattr(last, "tool_calls", None) or []
        if len(calls) > 1 and any(call["name"] == "ask_user" for call in calls):
            # [왜] 질문(interrupt)과 다른 도구가 한 단계에 섞이면 재개할 때 다른 도구가 다시 돌 수 있다
            errors = [ToolMessage(ASK_ALONE, tool_call_id=call["id"], status="error") for call in calls]
            return {"messages": errors, "jump_to": "model"}
        return None

    @staticmethod
    def _todo_error(call: ToolCall) -> ToolMessage | None:
        """할 일 목록을 쓸 때 끝나지 않은 일이 있는데 in_progress가 하나가 아니면 오류 결과 (설계 6.2)."""
        if call["name"] != "write_todos":
            return None
        todos = call["args"].get("todos")
        # [왜] 모양이 틀린 인자는 handler의 스키마 검사가 오류 결과로 돌려준다.
        #      여기서 터지면 차례 전체가 멈춘다
        if isinstance(todos, list) and all(isinstance(todo, dict) for todo in todos):
            open_items = [todo for todo in todos if todo.get("status") != "completed"]
            in_progress = sum(todo.get("status") == "in_progress" for todo in todos)
            # [왜] TodoListMiddleware는 진행 중 개수를 검사하지 않는다 (11-06 소스 확인).
            #      화면이 "지금 하는 일"을 하나로 보여 준다
            if open_items and in_progress != 1:
                return ToolMessage(ONE_IN_PROGRESS, tool_call_id=call["id"], status="error")
        return None

    def wrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]
    ) -> ToolMessage | Command:
        """도구 호출 한 번을 감싼다: 할 일 목록의 진행 중 개수를 본다."""
        return self._todo_error(request.tool_call) or handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """wrap_tool_call의 비동기 짝."""
        return self._todo_error(request.tool_call) or await handler(request)


def describe_approval(tool_call: ToolCall, state: Any, runtime: Any) -> str:
    """승인 카드 글: 할 일과 인자, 저장이면 저장될 품목 사실 (설계 8절: 승인된 사실만 저장)."""
    args = json.dumps(tool_call["args"], ensure_ascii=False)
    text = f"{tool_call['name']} 실행을 승인할까요?\n인자: {args}"
    if tool_call["name"] == "save_item_card":
        if not state.get("item"):
            # [왜] 품목 사실이 없으면 도구가 저장하지 않고 돌아온다. 승인해도 저장되지 않는 것을 카드에 보인다
            text += "\n저장할 품목 사실이 아직 없어요. 승인해도 저장되지 않아요."
        else:
            facts = json.dumps(state["item"], ensure_ascii=False)
            text += f"\n저장할 품목 사실: {facts}"
    return text


def build_agent(model: BaseChatModel, tools: list, permission_mode: str):
    """에이전트 루프를 만든다. auto 모드만 ask 목록을 건너뛴다 (설계 6.3)."""
    cfg = load_rules("agent")
    approval = cfg["approval"]
    # [주의] auto가 아닌 값(오타 포함)은 모두 묻는 쪽으로 둔다. always_ask는 auto에서도 늘 묻는다 (설계 12절)
    gated = (approval["ask"] if permission_mode != "auto" else []) + approval["always_ask"]
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        # [왜] 라이브러리 기본 글은 진행 중 여러 개와 마지막 갱신 뒤 직접 답하기를 허용해 우리 규칙과 부딪친다
        TodoListMiddleware(system_prompt=render("todos_system"), tool_description=render("todos_tool")),
        # [왜] 같은 차례에 법령 검색은 이 횟수까지. 넘는 호출은 오류 결과를 받고 모델이 다음 일을 고른다
        ToolCallLimitMiddleware(
            tool_name="search_law", run_limit=cfg["loop"]["max_searches"], exit_behavior="continue"
        ),
    ]
    if gated:
        # [왜] batched: 한 단계의 승인 요청을 interrupt 하나로 묶는다. 화면은 한 번에 카드 하나만 받는다
        decisions = InterruptOnConfig(
            allowed_decisions=["approve", "edit", "reject"], description=describe_approval
        )
        middleware.append(
            HumanInTheLoopMiddleware(
                interrupt_on={name: decisions for name in gated}, interrupt_mode="batched"
            )
        )
    middleware.append(Guards(cfg["loop"]["max_llm_calls"]))
    return create_agent(
        model,
        tools,
        system_prompt=render("agent"),
        middleware=middleware,
        state_schema=LoopState,
        name="agent",
    )


def build_summary(model: BaseChatModel) -> SummarizationMiddleware:
    """긴 대화 요약기 (계획 3d). 언제·어디까지 요약할지는 라이브러리가, 요약 글은 우리 프롬프트가 쓴다."""
    memory = load_rules("agent")["memory"]

    def summarize(messages: list[AnyMessage]) -> str:
        """요약할 메시지(가린 글)를 우리 프롬프트로 모델에게 요약시킨다."""
        # [왜] summarizer 함수를 주면 라이브러리의 재시도(3회)를 건너뛴다.
        #      SDK가 이미 재시도한다(agent.yaml llm.max_retries)
        return str(model.invoke(render("summary", history=get_buffer_string(messages))).text)

    return SummarizationMiddleware(
        model,  # [왜] 토큰 어림셈에만 쓴다. 요약 글은 summarize가 쓴다
        trigger=("tokens", memory["summary_trigger_tokens"]),
        keep=("messages", memory["summary_keep_messages"]),
        summarizer=summarize,
    )
