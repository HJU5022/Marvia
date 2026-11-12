"""배 위치·입항 일정의 모양과, 그 값으로 정하는 믿을 ETA와 여유 일수 (계획 8a, 설계 7.1).

하지 않는 일: 바깥 조회(tools/mof.py, tools/shipfinder.py), 신호(tools/signals.py), 등급(tools/verdict.py).
외부 호출이 없는 순수 함수라 같은 입력이면 같은 값이 나온다.
[주의] Position.dest는 선원이 손으로 넣는 자유 글이다. 모델 입력, 화면 글, 신호 값에 넣지 않는다(신뢰 경계).
       코드가 쓰는 것은 항구 코드로 읽은 dest_code뿐이다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone

from pydantic import BaseModel, Field

from marvia.tools.rules import load_rules

KST = timezone(timedelta(hours=9))  # 판매 예정일과 세관 입항일은 한국 날짜다
# 위도와 경도의 범위는 기준값이 아니라 좌표의 정의다. NaN과 무한대도 받지 않는다.
# [왜] 지구 밖 좌표나 NaN으로 거리를 재면 항구 앞 정지가 "꺼짐"으로 나오고 확신이 내려가지 않는다.
#      그런 값은 위치로 담지 않는다(조회 쪽은 bad_response, 판정은 위치 없음으로 본다)
Latitude = Field(ge=-90, le=90, allow_inf_nan=False)
Longitude = Field(ge=-180, le=180, allow_inf_nan=False)


class Position(BaseModel):
    """배 한 척의 지금 위치(ShipFinder). API의 무효 표시값은 None으로 바꿔 담는다."""

    mmsi: int
    lat: float = Latitude
    lng: float = Longitude
    sog: float | None = None  # 속도(노트)
    navstat: int | None = None  # AIS 항해상태 코드
    dest: str | None = None  # [주의] 자유 글. 코드 밖으로 내보내지 않는다
    dest_code: str | None = None  # 목적지를 항구 코드(UN/LOCODE)로 읽은 값
    ais_eta: datetime | None = None
    last_time: datetime | None = None  # 마지막 수신 시각
    fetched_at: datetime


class SailingPlan(BaseModel):
    """해수부 선박운항정보의 입항 신고 한 건."""

    call_sign: str | None = None
    ship_name: str = ""
    previous_port: str | None = None  # 직전 기항지
    planned_arrival: datetime | None = None
    revision: str | None = None  # 신고 단계: 최초·변경·최종
    facility: str | None = None  # 접안 예정 시설
    mrn: str | None = (
        None  # [주의] 화물관리번호 앞 11자리와 같다. 화물 번호처럼 다룬다(모델·로그에 넣지 않는다)
    )


class PortSchedule(BaseModel):
    """배 한 척의 입항 일정(해수부). planned_arrival에는 최종 신고의 시각을 넣지 않는다."""

    planned_arrival: datetime | None = None  # 아직 믿을 수 있는 입항 예정(최초·변경 신고)
    actual_arrival: datetime | None = None  # 관제 실적의 입항·접안 가운데 가장 이른 시각
    facility: str | None = None
    fetched_at: datetime


class TrackPoint(BaseModel):
    """지난 위치 한 점. 항구 앞에 얼마나 오래 멈춰 있었는지 잴 때 쓴다."""

    at: datetime
    lat: float = Latitude
    lng: float = Longitude
    sog: float | None = None


def as_utc(moment: datetime) -> datetime:
    """시간대가 없는 값은 UTC로 본다. [왜] 시간대 있는 값과 견주다 예외가 나는 것을 막는다"""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def is_port_code(code: str | None) -> bool:
    """UN/LOCODE 모양인가: 나라 영문 2 + 항구 3(영문 또는 숫자 2~9)."""
    text = (code or "").strip().upper()
    return (
        len(text) == 5
        and text.isascii()
        and text[:2].isalpha()
        and all(ch.isalpha() or ch in "23456789" for ch in text[2:])
    )


def other_port(position: Position | None, port_code: str | None) -> str | None:
    """배 신호의 목적지가 이 화물의 양륙항이 아닌 다른 항구면 그 코드. 같거나, 깨졌거나, 모르면 None."""
    code = ((position.dest_code if position else None) or "").strip().upper()
    mine = (port_code or "").strip().upper()
    return code if mine and is_port_code(code) and code != mine else None


def trusted_eta(
    position: Position | None,
    schedule: PortSchedule | None,
    port_code: str | None,
    forwarder_eta: date | None = None,
    now: datetime | None = None,
) -> tuple[datetime | None, str | None]:
    """믿을 도착 예정 시각과 그 출처 이름. 순서는 rules/verdict.yaml eta_priority다.

    now를 주면 이미 지난 배 신호 ETA는 출처로 치지 않는다(허용 오차는 rules/verdict.yaml clock_skew_minutes).
    """
    # [왜] 배 신호의 ETA는 그 배가 적어 둔 목적지의 도착 시각이다. 목적지가 다른 항구거나 양륙항을 모르면
    #      이 화물의 도착 시각으로 쓰지 않는다 (v1 평가 문항 B09: 다른 항구 ETA를 부산 예정과 견줬다)
    rules = load_rules("verdict")
    ais_ok = position is not None and bool(port_code) and other_port(position, port_code) is None
    if ais_ok and position is not None and rules["ais_eta_requires_port_match"]:
        # [왜] 목적지가 비었거나 깨졌으면 "다른 항구가 아님"일 뿐 이 항만이라는 근거는 없다.
        #      목적지 코드가 양륙항 코드와 같을 때만 그 ETA를 이 화물의 도착 시각으로 쓴다
        # [주의] 공백뿐인 코드는 빈 글이 된다. 빈 글끼리는 같다고 보지 않는다
        mine = (port_code or "").strip().upper()
        ais_ok = bool(mine) and (position.dest_code or "").strip().upper() == mine
    if ais_ok and now is not None and position is not None and position.ais_eta is not None:
        # [왜] 지난 시각의 배 신호 ETA는 고치지 않은 옛 입력이다. 그것으로 여유 일수를 세면 아직 먼 배가
        #      순항이 된다. 해수부의 실제 입항은 지난 시각이 맞으므로 이 검사는 배 신호 ETA에만 건다
        slack = timedelta(minutes=rules["clock_skew_minutes"])
        ais_ok = as_utc(position.ais_eta) >= as_utc(now) - slack
    values = {
        "mof_actual": schedule.actual_arrival if schedule else None,
        "mof_planned": schedule.planned_arrival if schedule else None,
        "ais_eta": position.ais_eta if position and ais_ok else None,
        # [왜] 포워더가 알려 준 날은 날짜뿐이다. 한국 날짜의 0시로 본다
        "forwarder_eta": datetime.combine(forwarder_eta, time.min, tzinfo=KST) if forwarder_eta else None,
    }
    for name in rules["eta_priority"]:
        value = values[name]
        if value is not None:
            return as_utc(value), name
    return None, None


def days_margin(trusted: datetime | None, sale_due: date | None) -> int | None:
    """판매 예정일까지 남은 일수(한국 날짜). 음수면 판매 예정일보다 늦게 도착한다. 하나라도 모르면 None."""
    if trusted is None or sale_due is None:
        return None
    return (sale_due - as_utc(trusted).astimezone(KST).date()).days
