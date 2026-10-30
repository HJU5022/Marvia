"""Claude Haiku 5.5를 한 번 불러 구조화 출력이 도는지 본다 (계획 2 Task 1). 키 필요, 비용 약 $0.001.

실행: uv run python scripts/try_llm.py
"""

from pydantic import BaseModel, Field

from marvia.config import Settings
from marvia.llm import chat_model, structured


class Keywords(BaseModel):
    keywords: list[str] = Field(description="법령 검색에 쓸 핵심 낱말")


ask = structured(chat_model(Settings()), Keywords)
print(
    ask(
        "다음 질문에서 법령 검색에 쓸 낱말을 뽑아라: 실리콘 주방매트를 처음 수입할 때 식약처 신고가 필요한가?"
    )
)
