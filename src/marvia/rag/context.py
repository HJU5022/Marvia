"""맥락 문장(Contextual Retrieval): 단위마다 어디에 속하고 어떤 상황에 쓰이는지 한두 문장을 붙인다 (설계 5.3).

하지 않는 일: 켜기 전후 비교(계획 4 평가). 색인(index.py)이 이 함수를 받아 단위마다 부른다.
[왜] 원래 방법은 문서 전체를 함께 넣지만 관세법 하나가 10만 토큰을 넘어 Haiku 5.5 값이 5배가 되는 구간에 든다.
그래서 제목 경로와 조문 글만 넣는다.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field

from marvia.prompts import render
from marvia.rag.models import Unit


class Context(BaseModel):
    """LLM이 채울 맥락 문장."""

    sentence: str = Field(description="한국어 한두 문장")


def make_contextualizer(ask: Callable[[str], Context]) -> Callable[[Unit], str]:
    """ask(프롬프트 → Context)로 단위 → 맥락 문장 함수를 만든다."""

    def contextualize(unit: Unit) -> str:
        return ask(render("rag_context", heading=unit.heading, text=unit.text)).sentence

    return contextualize
