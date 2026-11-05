"""대화 LLM 연결 (설계 13절, 2절 결정 14: Anthropic API의 Claude Haiku 5.5).

하지 않는 일: 프롬프트 내용, 그래프 흐름. 노드는 여기서 만든 "프롬프트 → 정해진 모양의 답" 함수만 받는다.
시간 제한·재시도 횟수는 rules/agent.yaml의 llm 칸에서 읽는다 (설계 6.4).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import anthropic
from langchain.chat_models import init_chat_model
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from marvia.config import Settings
from marvia.tools.rules import load_rules


class LLMFailed(Exception):
    """LLM 호출이 재시도 뒤에도 실패했다(API 오류·시간 초과·답 모양 오류). 그래프가 잡아 부분 답으로 간다."""


def chat_model(settings: Settings) -> BaseChatModel:
    """설정의 모델 이름으로 대화 LLM 객체를 만든다. 만들기만 하고 부르지는 않는다."""
    key = settings.anthropic_api_key.get_secret_value()
    if not key:
        # [왜] 키 없이 만들면 첫 호출에서야 인증 오류가 난다. 만들 때 바로 알려 준다
        raise RuntimeError("MARVIA_ANTHROPIC_API_KEY가 비어 있습니다. .env를 확인하세요")
    cfg = load_rules("agent")["llm"]
    # [왜] init_chat_model은 공급자 이름("anthropic")을 보고 ChatAnthropic 객체를 만들어 준다.
    # 공급자를 바꿀 때 model_provider만 바꾸면 된다 (설계 13절)
    # [주의] timeout을 넘기지 않으면 시간 제한이 없다(ChatAnthropic 기본값 None, 11-02 실측).
    #        재시도는 Anthropic SDK가 한다(429·5xx·연결 오류). 노드 재시도(RetryPolicy)는 겹쳐 두지 않는다
    return init_chat_model(
        settings.chat_model,
        model_provider="anthropic",
        api_key=key,
        timeout=cfg["timeout_s"],
        max_retries=cfg["max_retries"],
    )


def structured[T: BaseModel](llm: BaseChatModel, schema: type[T]) -> Callable[[str], T]:
    """프롬프트를 받아 schema 모양으로 답하는 함수를 만든다. 실패하면 LLMFailed를 던진다."""
    # [왜] method="json_schema": Claude의 구조화 출력(output_config.format)으로 답의 모양을 강제한다.
    # 기본값 function_calling은 도구 호출을 강제하는데, 생각(thinking)을 켰거나
    # 강제 도구 선택을 받지 않는 모델(Sonnet 5.5·Opus 5.5·Fable 5.1)이면 강제 없이 묶고,
    # 도구를 부르지 않으면 OutputParserException이 난다 (langchain-anthropic 1.7.7, 11-06 확인).
    # json_schema면 모델을 바꿔 비교해도 같은 길로 돈다
    runnable = llm.with_structured_output(schema, method="json_schema")

    def call(prompt: str) -> T:
        try:
            # [왜] with_structured_output은 dict를 돌려줄 수도 있다고 적혀 있어 pyright가 모른다.
            # schema가 pydantic 클래스면 그 객체가 온다
            return cast(T, runnable.invoke(prompt))
        except (anthropic.APIError, OutputParserException) as error:
            # [왜] API 오류(시간 초과·429·5xx·인증)와 답 모양 오류만 잡는다. 코드 버그는 그대로 올라간다
            # [주의] 오류 종류 이름과 HTTP 상태 코드만 남긴다. 오류 글에는 요청 내용이 섞일 수 있다
            # [왜] 429(잠시 뒤 다시)와 400(요청 모양 문제)은 다음 길이 달라 상태 코드는 남긴다
            status = getattr(error, "status_code", None)
            name = type(error).__name__
            raise LLMFailed(f"{name}({status})" if status else name) from error

    return call
