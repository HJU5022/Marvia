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
from marvia.llm import CLIFailed
from marvia.prompts import render
from marvia.tools.rules import load_rules

# [왜] 모델 호출 실패로 보는 오류: API 오류, 구조화 출력 모양 오류, `claude -p` 실패(MARVIA_LLM_VIA=cli)
MODEL_ERRORS = (anthropic.APIError, OutputParserException, CLIFailed)
# 한 단계에 혼자 불러야 하는 도구: 질문(interrupt)과 조사 서브에이전트(LLM 호출 상한을 함께 쓴다)
ALONE = ("ask_user", "research")
ASK_ALONE = (
    "ask_user와 research는 다른 도구 없이 혼자 불러야 해요. "
    "그 전에 할 일이 있으면 먼저 하고, 부를 때는 그 도구 하나만 부르세요."
)
ONE_IN_PROGRESS = (
    "할 일 목록에는 끝나지 않은 일이 있으면 in_progress가 정확히 하나여야 해요. 목록을 고쳐 다시 부르세요."
)


class Guards(AgentMiddleware[LoopState]):
    """도메인 규칙 미들웨어: LLM 호출 상한, LLM 실패 기록, 혼자 부를 도구, 진행 중 할 일 하나."""

    # [왜] 이 미들웨어가 읽고 쓰는 칸(llm_calls, stopped, failed_tools)을 루프 공책에 더한다
    state_schema = LoopState

    def __init__(self, max_llm_calls: int, label: str = "agent"):
        super().__init__()
        self.max_llm_calls = max_llm_calls
        self.label = label  # 실패 기록(failed_tools)에 남길 루프 이름. 조사 서브에이전트는 "research"

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: LoopState, runtime: Any) -> dict[str, Any] | None:
        """모델을 부르기 전: 이번 차례 LLM 호출 수(RAG 안의 호출 포함)가 상한이면 루프를 끝낸다 (설계 6.4)."""
        # [왜] 도구(조사 서브에이전트)가 LLM 실패로 stopped를 써 두었으면 같은 모델을 다시 부르지 않고 끝낸다
        if state.get("stopped"):
            return {"jump_to": "end"}
        if state.get("llm_calls", 0) < self.max_llm_calls:
            return None
        failed = [{"tool": self.label, "message": f"LLM 호출 한도({self.max_llm_calls}회)에 닿았어요"}]
        # [왜] jump_to="end": 모델을 부르지 않고 루프를 끝낸다. 메인 그래프가 stopped를 보고 부분 답으로 간다
        return {"stopped": "llm_calls", "failed_tools": failed, "jump_to": "end"}

    def _failed(self, error: Exception) -> ExtendedModelResponse:
        """API 오류·모양 오류를 기록하고 루프를 끝내는 응답 (동기·비동기가 함께 쓴다)."""
        # [주의] 오류 종류 이름과 상태 코드만 남긴다. 오류 글에는 요청 내용이 섞일 수 있다
        #        (llm.structured와 같은 규칙)
        status = getattr(error, "status_code", None)
        name = f"{type(error).__name__}({status})" if status else type(error).__name__
        update = {
            "llm_calls": 1,
            "stopped": "llm_failed",
            "failed_tools": [{"tool": self.label, "message": name}],
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
        """모델이 혼자 부를 도구(ask_user, research)를 다른 도구와 함께 불렀으면 모두 오류로 돌려준다."""
        # [왜] 다른 미들웨어가 오류 결과를 먼저 붙여도 마지막 모델 메시지를 본다
        last = next((m for m in reversed(state["messages"]) if m.type == "ai"), None)
        calls = getattr(last, "tool_calls", None) or []
        if len(calls) > 1 and any(call["name"] in ALONE for call in calls):
            # [왜] 질문(interrupt)과 다른 도구가 한 단계에 섞이면 재개할 때 다른 도구가 다시 돌 수 있다.
            #      조사는 남은 LLM 호출을 모두 쓸 수 있어, 함께 도는 검색이 상한을 넘길 수 있다
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
    # [왜] 승인하는 사람에게는 영어 도구 이름보다 한국어 이름이 읽힌다. 모르는 도구는 이름 그대로 보인다
    label = load_rules("agent")["approval"].get("labels", {}).get(tool_call["name"], tool_call["name"])
    text = f"{label} 실행을 승인할까요?\n인자: {args}"
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
        history = summary_history(messages, memory["summary_max_input_chars"])
        return str(model.invoke(render("summary", history=history)).text)

    return SummarizationMiddleware(
        model,  # [왜] 토큰 어림셈에만 쓴다. 요약 글은 summarize가 쓴다
        trigger=("tokens", memory["summary_trigger_tokens"]),
        keep=("messages", memory["summary_keep_messages"]),
        summarizer=summarize,
        # [왜] 기본값(4000 토큰)은 요약할 메시지의 앞쪽을 잘라 버리고, 잘린 앞부분은 요약되지 않은 채 기록에서
        #      지워진다. 앞 요약이 기록의 첫 메시지라서 두 번째 요약부터 앞 요약이 사라진다.
        #      상한은 앞 요약을 지키는 summary_history가 대신 둔다
        trim_tokens_to_summarize=None,
    )


def summary_history(messages: list[AnyMessage], cap: int) -> str:
    """요약기에 줄 기록 글. 앞 요약은 늘 맨 앞에 두고, cap(글자 수)을 넘으면 그 뒤 기록의 앞쪽을 뺀다."""
    # [왜] 앞 요약은 기록의 첫 메시지이고 라이브러리가 lc_source 표시를 붙인다(brief가 그대로 둔다).
    #      빼면 그 앞의 대화가 기록에서 영영 사라진다
    earlier = bool(messages) and messages[0].additional_kwargs.get("lc_source") == "summarization"
    first = messages[:1] if earlier else []
    # [주의] 앞 요약도 cap 안에 자른다. 짧게 쓰라고 시켰지만 모델이 쓴 글이라 길이를 믿지 않는다
    head = get_buffer_string(first)[:cap]
    rest = get_buffer_string(messages[len(first) :])
    room = max(cap - len(head) - 1, 0)  # [왜] 1은 앞 요약과 나머지 사이 줄바꿈
    # [왜] 최근 부분(지금 묻는 일에 가까운 쪽)을 남긴다. 라이브러리의 문맥 넘침 재시도도 끝쪽을 남긴다
    tail = rest[len(rest) - room :] if len(rest) > room else rest
    return "\n".join(part for part in (head, tail) if part)


def build_researcher(model: BaseChatModel, tools: list):
    """조사 서브에이전트 (계획 3d): 법령 검색·조문 조회만 하는 두 번째 루프. 짧은 요약 글로 끝난다."""
    cfg = load_rules("agent")
    return create_agent(
        model,
        tools,
        system_prompt=render("research"),
        # [왜] 같은 Guards가 같은 상한을 지킨다. 부모가 넘긴 호출 수에서 이어 세므로 둘을 합쳐도 상한 안이다
        middleware=[Guards(cfg["loop"]["max_llm_calls"], label="research")],
        state_schema=LoopState,
        name="research",
    )
