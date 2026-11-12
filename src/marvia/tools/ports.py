"""항만 표(rules/ports.yaml)를 읽는다 (계획 8a, 설계 7.1 "항만별 값은 항만 데이터 표에").

하지 않는 일: 표에 없는 항만을 다른 항만 값으로 대신하기. 없는 항만은 None이고, 부르는 쪽이 "모름"으로 다룬다.
v1은 부산 값(항구 코드, 청코드, 기준점, 반경, 조회 기간)을 코드와 Skill에 고정했다. 여기서는 표에서만 받는다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from marvia.tools.rules import load_rules


class Ref(BaseModel):
    """항구 앞 정지를 재는 기준점."""

    model_config = ConfigDict(extra="forbid")
    lat: float
    lng: float


class Port(BaseModel):
    """항만 한 줄. 확인하지 못한 칸은 None이다."""

    model_config = ConfigDict(extra="forbid")
    code: str  # UNI-PASS 양륙항 코드(UN/LOCODE)
    name: str
    verified: bool = False  # 이 줄의 값을 그 항만의 실제 응답으로 확인했나
    mof_office: str | None = None  # 해수부 API의 청코드(prtAgCd)
    ref: Ref | None = None
    stop_radius_nm: float | None = None
    schedule_lookback_days: int | None = None
    schedule_lookahead_days: int | None = None
    mrn_search_days: int | None = None


def port(code: str | None) -> Port | None:
    """양륙항 코드의 항만 줄. 코드가 없거나 표에 없으면 None."""
    key = (code or "").strip().upper()
    row = load_rules("ports")["ports"].get(key)
    return Port(code=key, **row) if row else None
