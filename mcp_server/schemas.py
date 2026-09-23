"""계약 C4(MCP 도구 4종 입출력). 근거: SDD 3.4, PRD 6.5.

책임: FastMCP 도구가 LLM에 돌려주는 값의 모양. 원본 값과 조회 시각(fetched_at)만 돌려주고 판정·freshness 계산은 하지 않는다.
실패는 예외 대신 ToolError를 돌려준다 (SDD 3.4). 모든 결과에 source와 fetched_at이 있어 evidence로 바로 옮길 수 있다.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# 부산항 기준점 (SDD 3.4). estimate_distance가 여기까지 해리를 계산한다.
BUSAN_REF_LAT = 35.10
BUSAN_REF_LNG = 129.05


class ToolError(BaseModel):
    """도구 실패. retryable이면 llm.py가 재시도 2회 뒤 partial로 간다 (SDD 8절)."""

    code: str
    message: str
    retryable: bool


class VesselCandidate(BaseModel):
    """get_vessel_candidates 결과 1건. 같은 IMO면 last_time 최신 1건만 남긴다 (B3)."""

    mmsi: int
    imo: int | None
    name: str
    call_sign: str | None = Field(default=None, description="해수부 조회 키. 선명은 한글·영문이 달라 매칭이 약하다")
    flag: str | None
    dest: str | None
    last_time: datetime | None
    ship_type: int | None
    similarity: float = Field(ge=0, le=1, description="선명 유사도 0~1")


class VesselCandidatesResult(BaseModel):
    candidates: list[VesselCandidate]
    source: str = "shipfinder"
    fetched_at: datetime


class LivePositionResult(BaseModel):
    """get_live_position. freshness 판정은 services/signals.py 몫이라 여기 없다 (B4 경계)."""

    mmsi: int
    lat: float
    lng: float
    sog: float | None
    cog: float | None
    navistat: int | None
    dest: str | None
    destcode: str | None
    ais_eta: datetime | None
    last_time: datetime | None
    source: str = "shipfinder"
    fetched_at: datetime


class ControlEvent(BaseModel):
    """해수부 관제 이벤트 1건 (입항 예정·실적 등)."""

    kind: str
    at: datetime | None
    facility: str | None


class PortScheduleResult(BaseModel):
    """get_port_schedule. 해수부 관제정보·선박운항정보 (B5·B6)."""

    planned_arrival: datetime | None
    actual_arrival: datetime | None
    facility: str | None = Field(default=None, description="fcltyNm")
    control_events: list[ControlEvent] = Field(default_factory=list)
    source: str = "mof"
    fetched_at: datetime


class DistanceResult(BaseModel):
    """estimate_distance. searoute로 부산 기준점까지 해리 (B7)."""

    distance_nm: float
    calc_hours_at_sog: float | None = None
    source: str = "searoute"
    fetched_at: datetime
