"""서류 사진 응답 계약 (docs/specs/document-extract.md "How"). 계약 C1~C8 밖의 새 파일이다.

책임: POST /api/document가 돌려주는 모양을 고정한다. 프론트 확인 화면이 이 모양을 그대로 그린다.
판정 요청(AgentRequest)으로 바로 넘기지 않는다. 사용자가 확인·수정한 값만 /api/agent로 간다 (SDD 비전 울타리).
필드를 바꾸면 프론트가 같이 깨지므로 PR 리뷰를 거친다 (CLAUDE.md 계약 파일 규칙).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# 검사 이름은 services/doc_ocr.check_fields와 같다. 빈 목록이면 통과
Check = Literal["missing", "not_in_text", "format", "ambiguous"]  # ambiguous: 같은 칸 이름표가 두 번 이상 (09-30)


class FieldResult(BaseModel):
    value: str | None = Field(description="서류에서 읽은 값. 못 읽었으면 null")
    checks: list[Check] = Field(description="걸린 검사. 비어 있으면 통과")


class DocumentFields(BaseModel):
    bl_no: FieldResult    # 코드가 이름표 근처에서 뽑는다. LLM은 보지 않는다
    vessel: FieldResult
    voyage: FieldResult
    eta: FieldResult      # YYYY-MM-DD
    pol: FieldResult      # 선적항
    pod: FieldResult      # 양하항
    item: FieldResult     # 품명. 사용자 서류에서 읽은 값이며 저장하지 않는다 (Spec "규칙과의 관계")


class OcrInfo(BaseModel):
    lines: int            # 읽은 글자 줄 수. 0에 가까우면 사진이 글자를 담지 못한 것
    rotation: Literal[0, 180, 270]
    runs: int             # OCR을 몇 번 돌렸나 (보통 1, 누운·뒤집힌 사진 3)
    ocr_ms: int


class DocumentResponse(BaseModel):
    # partial: LLM이 실패해서 B/L만 채웠다 (Spec EC-05). 사진 자체가 문제면 400이다
    status: Literal["ok", "partial"]
    needs_review: bool = Field(description="검사에 걸린 칸이 하나라도 있으면 true. 확인 화면에서 강조한다")
    fields: DocumentFields
    ocr: OcrInfo
    trace_id: str
