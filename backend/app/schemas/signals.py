"""계약 C3(SignalSet). 근거: SDD 3.3, 5.4.

책임: 1층(코드)이 계산한 신호 7종의 출력 형태. services/signals.py가 만들고 LLM 입력과 reasons에 쓰인다.
신호 id 7개는 skills/ais-reliability/rules.md "1층 신호 7종" 표의 id와 같아야 한다. 기준값은 skills/*/rules.md에 나뉘어 있다 (10-01).
sales_date_exceeded는 09-23 D4에서 추가: 배가 정상이어도 신뢰 ETA가 판매 예정일을 넘기면 act (PRD 6.2).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from .agent import Freshness

SignalId = Literal[
    "position_stale",       # 위치 갱신이 position_stale_hours(6h) 넘게 끊김
    "eta_conflict",         # AIS ETA와 해수부 입항예정이 eta_conflict_hours(12h) 넘게 다름
    "anchor_wait",          # 부산 반경 안에서 anchor_speed_kn 이하로 anchor_wait_hours(24h) 이상 정지
    "dest_changed",         # destcode가 비었거나 busan_port_code(KRPUS, port-busan/rules.md)가 아님
    "navstat_mismatch",     # 항해상태와 속도가 안 맞음
    "customs_hold",         # 통관 검사 지정·보류
    "sales_date_exceeded",  # days_margin < 0
]
SignalState = Literal["triggered", "clear", "unknown"]


class Signal(BaseModel):
    """신호 1개. value는 실제 관측값, threshold는 rules.md에서 읽은 기준값 (코드에 숫자 하드코딩 금지)."""

    id: SignalId
    state: SignalState
    value: str
    threshold: str
    source: str


class SignalSet(BaseModel):
    """신호 7개 묶음 + 코드가 같이 계산한 파생값. 순수 함수 출력이라 외부 호출 없음 (SDD 5.4)."""

    signals: list[Signal]
    freshness: Freshness
    distance_nm: float | None
    calc_eta: datetime | None
    eta_gap_hours: float | None
    computed_at: datetime
