"""서류 사진 응답 계약 (docs/specs/document-extract.md "How"). 계약 C1~C8 밖의 새 파일이다.

책임: POST /api/document가 돌려주는 모양을 고정한다. 프론트 확인 화면이 이 모양을 그대로 그린다.
판정 요청(AgentRequest)으로 바로 넘기지 않는다. 사용자가 확인·수정한 값만 /api/agent로 간다 (SDD 비전 울타리).
필드를 바꾸면 프론트가 같이 깨지므로 PR 리뷰를 거친다 (CLAUDE.md 계약 파일 규칙).
10-02 (정운 승인, 결정 6): B/L 조건 세 칸 + 인코텀즈와 화물 인도 연락처(회사·역할·회사 전화) 칸을 더했다.
이 칸들은 서류에 없는 경우가 흔해서(도착 통지서엔 운임 조건이 없기도 하다) 비어도 missing을 걸지 않는다.
값이 있을 때만 검사(not_in_text, format, ambiguous)를 건다. 사용자가 확인 화면에서 고른 값만 저장된다 (POST /api/memory/document-facts).
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
    # 10-06: 출항일 YYYY-MM-DD. 도착 통지서의 E.T.D. 또는 B/L의 Shipped/Laden on board 날짜를 서류에서 옮긴 값이다
    # (계산하지 않는다). 화물 시트 출항 칸에 채운다. 서류에 없는 경우가 흔해서 비어도 missing을 걸지 않고, 값이 있을 때만
    # 날짜 검사를 건다. 입항일(eta)보다 늦으면 format (services/doc_ocr.check_fields). 기본값을 둬서 etd 이전 모양의 응답도 읽힌다
    etd: FieldResult = Field(default_factory=lambda: FieldResult(value=None, checks=[]),
                             description="출항일 YYYY-MM-DD. 서류에 적힌 날짜만, 없으면 null")
    # 10-02 결정 6. 판정 등급에는 쓰지 않는다. 비서가 짚을 거리(원본 B/L·은행 L/G, 착불 운임)로만 쓴다
    original_bl: FieldResult = Field(default_factory=lambda: FieldResult(value=None, checks=[]),
                                     description="required(원본 필요) / surrendered(서렌더, 원본 불필요)")
    to_order_bank: FieldResult = Field(default_factory=lambda: FieldResult(value=None, checks=[]),
                                       description='"true" / "false": 수하인이 TO ORDER OF ... BANK(은행 지시식)인가')
    freight_term: FieldResult = Field(default_factory=lambda: FieldResult(value=None, checks=[]),
                                      description="prepaid(선불) / collect(착불)")
    incoterm: FieldResult = Field(default_factory=lambda: FieldResult(value=None, checks=[]),
                                  description="CIF / FOB / CFR")
    # 화물 인도 연락처 (B/L "Party to contact for cargo release", A/N). 회사 단위만. 개인 이름·휴대폰·이메일은 받지 않는다
    contact_company: FieldResult = Field(default_factory=lambda: FieldResult(value=None, checks=[]))
    contact_role: FieldResult = Field(default_factory=lambda: FieldResult(value=None, checks=[]),
                                      description="포워더 / 관세사 / 수출자 / 판매처")
    contact_phone: FieldResult = Field(default_factory=lambda: FieldResult(value=None, checks=[]),
                                       description="회사·부서 전화, 숫자와 하이픈. 개인 휴대폰이면 비우고 format")


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
    # 적하목록 관리번호. "MRN" 이름표 옆 값을 코드가 뽑는다(LLM 아님). 세관에 아직 없는 화물의 대체 조회용 (docs/specs/mrn-fallback.md, 10-01)
    mrn: str | None = None
    # 서류 종류 (LLM이 고름, 10-02). 거래처를 메모장에 저장할 때 출처(B/L·A/N)로 쓴다. 모르면 null이고 거래처는 저장하지 않는다
    doc_kind: Literal["B/L", "A/N"] | None = None
