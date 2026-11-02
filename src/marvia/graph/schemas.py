"""메인 그래프에서 LLM이 채울 답의 모양 (설계 6.1·6.5). llm.structured가 이 모양으로 답을 받는다.

하지 않는 일: 프롬프트(prompts/*.md), 흐름(graph/main.py), 검사(graph/verify.py).
[왜] 자유 키 dict 칸을 두지 않는다. Anthropic 구조화 출력은 dict[str, str]을 빈 {}로만 낼 수 있다(11-02 확인).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Draft(BaseModel):
    """작성자가 쓴 답 초안. 화물 번호는 가린 토큰 그대로다."""

    answer: str = Field(description="사용자에게 보낼 한국어 답. 화물 번호는 [BL1] 같은 토큰 그대로")
    citations: list[str] = Field(description="답이 기댄 근거의 unit_id. 근거 묶음의 대괄호 안 글 그대로")
    next_options: list[str] = Field(description="사용자가 다음에 할 수 있는 일 두세 개")
    forwarder_message: str = Field(description="포워더에게 번호를 물을 메시지. 필요 없으면 빈 글")
