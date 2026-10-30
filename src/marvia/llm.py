"""대화 LLM 연결 (설계 13절, 2절 결정 14: Anthropic API의 Claude Haiku 5.5).

하지 않는 일: 프롬프트 내용, 그래프 흐름. 노드는 여기서 만든 "프롬프트 → 정해진 모양의 답" 함수만 받는다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from marvia.config import Settings


def chat_model(settings: Settings) -> BaseChatModel:
    """설정의 모델 이름으로 대화 LLM 객체를 만든다. 만들기만 하고 부르지는 않는다."""
    key = settings.anthropic_api_key.get_secret_value()
    if not key:
        # [왜] 키 없이 만들면 첫 호출에서야 인증 오류가 난다. 만들 때 바로 알려 준다
        raise RuntimeError("MARVIA_ANTHROPIC_API_KEY가 비어 있습니다. .env를 확인하세요")
    # [왜] init_chat_model은 공급자 이름("anthropic")을 보고 ChatAnthropic 객체를 만들어 준다.
    # 공급자를 바꿀 때 model_provider만 바꾸면 된다 (설계 13절)
    return init_chat_model(settings.chat_model, model_provider="anthropic", api_key=key)


def structured[T: BaseModel](llm: BaseChatModel, schema: type[T]) -> Callable[[str], T]:
    """프롬프트를 받아 schema 모양으로 답하는 함수를 만든다."""
    # [왜] method="json_schema": Claude의 구조화 출력 기능으로 답의 모양을 강제한다.
    # 기본값 function_calling은 도구 호출을 강제하는 방식이라, 생각(thinking)이 켜진 모델에서는 다른 길로 돈다
    runnable = llm.with_structured_output(schema, method="json_schema")

    def call(prompt: str) -> T:
        # [왜] with_structured_output은 dict를 돌려줄 수도 있다고 적혀 있어 pyright가 모른다.
        # schema가 pydantic 클래스면 그 객체가 온다
        return cast(T, runnable.invoke(prompt))

    return call
