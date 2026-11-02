"""RAG 노드에서 LLM이 채울 답의 모양 (설계 5.4의 1·5·6번). llm.structured가 이 모양으로 답을 받는다.

하지 않는 일: 프롬프트(prompts/rag_*.md), 흐름(graph/rag.py).
[왜] Field의 description은 JSON 스키마에 들어가 LLM이 각 칸에 무엇을 쓸지 보는 설명이 된다.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class QueryAnalysis(BaseModel):
    """질의 분석 결과."""

    question_type: Literal["문구 해석", "위임 사슬", "다단계 요건", "화물 결합"] = Field(
        description=(
            "문구 해석: 조문 뜻 / 위임 사슬: 아래 규정으로 넘긴 내용 / "
            "다단계 요건: 여러 법의 요건 / 화물 결합: 내 화물 상태와 조문"
        )
    )
    as_of: date | None = Field(description="질문이 묻는 기준 날짜. 질문에 날짜가 없으면 null")
    search_query: str = Field(description="법령 검색에 넣을 한국어 문장")


class Grade(BaseModel):
    """근거 채점 결과."""

    sufficient: bool = Field(description="근거에 질문에 답하는 조문 글이 있으면 true")
    reason: str = Field(description="판단 이유 한 문장")
    missing: str = Field(description="부족하면 빠진 조문이나 사실 한 문장. 충분하면 빈 글")


class Rewrite(BaseModel):
    """고쳐 쓴 검색 질의."""

    search_query: str = Field(description="법령 검색에 넣을 새 한국어 문장")
