"""계약 C1(AgentResponse)·C2(AgentRequest). 근거: SDD 3.1, 3.2.

책임: 프론트와 백엔드가 주고받는 요청·응답의 모양을 고정한다.
- 첫 조회, 되묻기 답, 후속 질문이 전부 같은 AgentRequest 하나로 들어온다 (SDD 4.3).
- 응답은 성공·실패 모두 같은 AgentResponse 틀이고 status로 갈린다 (SDD 8절).
- 여기 필드를 바꾸면 평가셋(C7)·프론트·fixture가 같이 깨지므로 PR 리뷰를 거친다 (CLAUDE.md).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ---- 공용 열거값 (SDD 3.2) ----
Verdict = Literal["fine", "watch", "act"]
# unsupported: 지원 범위 밖 요청(부산 외 항만 등). 외부 조회 없이 끝낸다. failed(처리 실패)와 구분한다 (09-23 결정).
Status = Literal["ok", "partial", "insufficient", "failed", "unsupported"]
VesselMatch = Literal["confirmed", "uncertain", "none"]
Freshness = Literal["fresh", "stale", "unknown"]

# B/L 번호 형식: 영문 대문자+숫자 8~20자 (SDD 3.1). 공백은 검증 전에 제거한다.
_BL_PATTERN = re.compile(r"^[A-Z0-9]{8,20}$")


class AgentRequest(BaseModel):
    """C2. 필수 4개 + 선택 4개. 선택 칸이 채워졌는지로 첫 조회/되묻기 답/후속 질문을 구분한다."""

    bl_no: str = Field(description="B/L 번호. 영문+숫자 8~20자, 공백 제거")
    bl_type: Literal["MASTER", "HOUSE"]
    # 선택 입력 (09-29 결정). 필수는 B/L 하나다. 판매일이 정해진 경우가 많지만 품목에 따라 안 정하는 경우도 많다
    # (하정운 실무 경험). 없으면 여유 일수 없이 배 상태만으로 판정한다 (routers/agent.py, SKILL.md 판정 표)
    sale_due_date: date | None = Field(default=None, description="판매 예정일 (필요 입고일). 선택")
    session_id: str
    follow_up_question: str | None = Field(default=None, max_length=300, description="후속 질의. 300자 제한 (SDD 7절)")
    resolved_mmsi: int | None = Field(default=None, description="되묻기 후 사용자가 고른 선박")
    voyage_no: str | None = Field(default=None, description="되묻기 후 입력")
    forwarder_eta: date | None = None

    @field_validator("bl_no")
    @classmethod
    def _normalize_bl(cls, v: str) -> str:
        """공백 제거·대문자화 뒤 형식 검사. 형식 오류는 라우터가 400으로 돌려준다 (SDD 8절)."""
        v = re.sub(r"\s+", "", v).upper()
        if not _BL_PATTERN.match(v):
            raise ValueError("bl_no는 영문+숫자 8~20자여야 합니다")
        return v


class Evidence(BaseModel):
    """근거 카드 1장. 모든 판정 숫자는 여기 있는 값이어야 한다 (validate V3·V6·V7)."""

    source: Literal["shipfinder", "unipass", "mof", "searoute", "rule"]
    field: str
    value: str
    fetched_at: datetime


class Reason(BaseModel):
    """켜진 1층 규칙. rule은 rules.md의 규칙 id (SDD 3.3 Signal.id와 같은 집합)."""

    rule: str
    value: str
    triggered: bool


class Conflict(BaseModel):
    """신호가 어긋났을 때 어느 출처를 왜 골랐나. chosen은 evidence[].source에 있어야 한다 (V6)."""

    # 1개 이상 (09-29 변경, 전에는 2개 이상). eta_conflict처럼 신호 하나가 그 자체로 "AIS와 해수부가 다르다"는
    # 상충인 경우가 있다. 2개를 요구했더니 Gemini가 ["eta_conflict"]로 맞게 답하고도 형식 오류로 3번 탈락했다
    # (평가 B04·B09, Langfuse 확인). 구조화 출력(strict)은 minItems를 LLM에 전하지 못해 LLM은 이 조건을 알 수도 없었다
    signals: list[str] = Field(min_length=1, description="상충한 신호 id 1개 이상")
    chosen: str
    why: str


class VesselCandidate(BaseModel):
    """되묻기 때 사용자에게 보여줄 후보 1척."""

    mmsi: int
    imo: int | None
    name: str
    flag: str | None
    dest: str | None
    last_time: datetime
    ship_type: int | None
    match_reasons: list[str]


class VesselInfo(BaseModel):
    """식별이 끝난 배. 프론트 VesselCard가 그대로 그린다 (SDD 3.2, 09-22 D3에서 7필드로 확정)."""

    mmsi: int
    imo: int | None
    name: str
    call_sign: str | None = Field(description="해수부 실적 매칭 키")
    flag: str | None = Field(description="국적. UNI-PASS shipNat 우선, 없으면 ShipFinder")
    ship_type: int | None
    voyage_no: str | None = Field(description="UNI-PASS vydf 또는 사용자 입력")


class Position(BaseModel):
    """위치. freshness는 코드가 계산한다 (SDD 5.4). LLM 값은 덮어쓴다."""

    lat: float
    lng: float
    sog: float
    cog: float
    navistat: int
    last_time: datetime
    freshness: Freshness


class EtaInfo(BaseModel):
    """ETA 4종. trusted_eta는 rules.md priority 순서로 코드가 고른다 (SDD 5.8)."""

    ais_eta: datetime | None
    mof_eta: datetime | None
    calc_eta: datetime | None
    trusted_eta: datetime | None
    distance_nm: float | None


class CustomsInfo(BaseModel):
    """통관 단계와 해설. plain_explanation은 LLM이 쓰고 judge가 채점한다 (SDD 5.12)."""

    stage_code: str
    stage_name: str
    plain_explanation: str
    next_stage: str | None
    needs_broker: bool
    history: list[dict] = Field(default_factory=list, description="{code, name, at}")
    # 화물이 어디서 어디로 가나. UNI-PASS 값 그대로 (코드가 채움, LLM 아님). 10-01 추가, 없으면 null
    loading_port: str | None = Field(default=None, description="적재항 코드 ldprCd (예: CNTAO)")
    loading_port_name: str | None = Field(default=None, description="적재항 이름 ldprNm (예: Qingdao)")
    loading_country: str | None = Field(default=None, description="적출국 코드 lodCntyCd (예: CN)")
    discharge_port: str | None = Field(default=None, description="양륙항 코드 dsprCd (예: KRPUS)")
    discharge_port_name: str | None = Field(default=None, description="양륙항 이름 dsprNm (예: 부산항)")


class BerthInfo(BaseModel):
    facility: str | None = Field(default=None, description="해수부 fcltyNm")
    shed: str | None = Field(default=None, description="UNI-PASS shedNm")


class AgentResponse(BaseModel):
    """C1. 성공·실패 모두 같은 틀. status가 ok/partial/insufficient/failed/unsupported를 가른다 (SDD 8절, unsupported는 09-23 추가).

    - insufficient면 verdict는 None이고 missing_inputs 또는 vessel_candidates가 채워진다 (V4·V5).
    - days_margin은 코드 계산값. LLM이 다른 값을 내도 evidence.py가 덮어쓴다 (SDD 5.8).
    """

    status: Status
    verdict: Verdict | None
    vessel_match: VesselMatch
    vessel_candidates: list[VesselCandidate] = []
    missing_inputs: list[str] = []
    reasons: list[Reason] = []
    conflicts: list[Conflict] = []
    actions: list[str] = []
    days_margin: int | None
    decided_by: Literal["rule", "llm"] | None
    vessel: VesselInfo | None
    position: Position | None
    eta: EtaInfo | None
    customs: CustomsInfo | None
    berth: BerthInfo | None
    evidence: list[Evidence]
    answer: str
    trace_id: str
