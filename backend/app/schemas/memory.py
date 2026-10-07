"""화물 비서 기억 API 계약 (docs/specs/memory.md "API", 10-02 결정 6·7). 계약 C1~C8 밖의 새 파일이다.

책임: GET·DELETE /api/memory, DELETE /api/memory/items/{id}, POST /api/memory/document-facts의 모양을 고정한다.
화면(web/lib/types.ts)이 이 모양을 그대로 쓴다. 필드를 바꾸면 프론트가 같이 깨지므로 PR 리뷰를 거친다 (CLAUDE.md 계약 파일 규칙).
원본 B/L과 화물 지문(cargo_key)은 응답에 넣지 않는다. 화면에는 가린 번호만 간다 (SDD 3.5).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.app.schemas.agent import _BL_PATTERN, Verdict

# 값 목록은 마이그레이션 015 CHECK, services/memory.py ROLES·SOURCES와 같다 (10-02 결정 5·6)
Role = Literal["포워더", "관세사", "수출자", "판매처"]
Kind = Literal["preference", "schedule", "contact", "worry", "todo"]
OriginalBl = Literal["required", "surrendered"]
FreightTerm = Literal["prepaid", "collect"]
Incoterm = Literal["CIF", "FOB", "CFR"]


class MemoryItem(BaseModel):
    """메모장 항목 하나. id는 지우기 버튼용이고 화면 글에는 쓰지 않는다 (Spec "번호 없는 마크다운")."""

    id: str
    section: Literal["about", "cargo"]
    kind: Kind
    fields: dict[str, str | bool | None]
    noted_at: str | None
    cargo_name: str | None = Field(description="화물별 항목이면 화물 이름(이름표 또는 가린 번호). 이 사람에 대해 항목은 null")


class PendingChange(BaseModel):
    """대화에서 나온 화물 값 변경. 바로 적용하지 않고 확인 대상으로만 둔다 (Spec 쓰기 흐름 4)."""

    field: Literal["sale_due_date", "forwarder_eta", "label"]
    value: str
    noted_at: str | None = None


class CargoSummary(BaseModel):
    """화물 표 한 줄 요약. 원본 B/L·지문·배 MMSI는 넣지 않는다."""

    bl_masked: str
    bl_type: Literal["MASTER", "HOUSE"]
    label: str | None
    status: Literal["active", "done"]
    sale_due_date: date | None
    forwarder_eta: date | None
    original_bl: OriginalBl | None
    to_order_bank: bool | None
    freight_term: FreightTerm | None
    incoterm: Incoterm | None
    last_verdict: Verdict | None
    last_checked_at: datetime | None
    last_days_margin: int | None
    last_eta: date | None
    last_stage: str | None
    pending: list[PendingChange]
    summary: str | None = Field(description="끝난 화물의 한 줄 요약 (코드가 만든다). 진행 중이면 null")


class MemoryResponse(BaseModel):
    markdown: str = Field(description="번호 없는 메모장 (Spec 템플릿)")
    items: list[MemoryItem]
    cargo: list[CargoSummary]
    full: bool = Field(description="상한을 넘어 새 기억을 저장하지 못했다 (EC-06). 정리하면 다시 false")
    available: bool = Field(default=True, description="DB를 못 읽었으면 false. 빈 기억과 구분한다")
    used_chars: int = Field(default=0, description="메모장 글자 수 (markdown 길이, 상한 판단과 같은 기준)")
    max_chars: int = Field(default=3000, description="메모장 글자 상한 (services/memory.MAX_CHARS)")


class MemoryDeleteResponse(BaseModel):
    deleted: int  # 지운 줄 수 (제36조 ②, 결과를 알린다)


class DocumentContact(BaseModel):
    """서류의 화물 인도 연락처 (B/L "Party to contact for cargo release", A/N). 회사 단위만 받는다 (10-02 결정 6)."""

    company: str = Field(min_length=1, max_length=40)
    role: Role
    phone: str | None = Field(default=None, max_length=20, description="회사·부서 전화. 숫자와 하이픈")


class DocumentFactsRequest(BaseModel):
    """사용자가 서류 확인 화면에서 "확인한 값으로 채우기"를 눌렀을 때의 값 (10-02 결정 7). 확인 안 한 OCR 값은 오지 않는다."""

    bl_no: str
    bl_type: Literal["MASTER", "HOUSE"] | None = None
    source: Literal["B/L", "A/N"] | None = Field(default=None, description="거래처 출처. 서류 종류를 모르면 거래처는 저장하지 않는다")
    original_bl: OriginalBl | None = None
    to_order_bank: bool | None = None
    freight_term: FreightTerm | None = None
    incoterm: Incoterm | None = None
    contact: DocumentContact | None = None

    @field_validator("bl_no")
    @classmethod
    def _normalize_bl(cls, v: str) -> str:
        """조회 요청(AgentRequest)과 같은 형식 검사. 공백 제거·대문자 (schemas/agent.py _BL_PATTERN)."""
        v = re.sub(r"\s+", "", v).upper()
        if not _BL_PATTERN.match(v):
            raise ValueError("bl_no는 영문+숫자 8~20자여야 합니다")
        return v


class DocumentFactsResponse(BaseModel):
    conditions_saved: bool = Field(description="B/L 조건을 화물 표에 적었다")
    contact: Literal["saved", "unchanged", "rejected", "skipped", "full", "conflict"] = Field(
        description="거래처 저장 결과. skipped: 거래처나 출처가 없어 저장하지 않음")
