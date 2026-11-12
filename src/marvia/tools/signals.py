"""신호 여섯 개를 켜짐·꺼짐·모름으로 가른다 (계획 8a, 설계 7.1). 등급은 tools/verdict.py가 이 신호로 정한다.

하지 않는 일: 바깥 조회, 등급·확신·일정. 외부 호출이 없는 순수 함수라 같은 입력이면 같은 결과가 나온다.
기준값은 rules/verdict.yaml signals에서, 항만 값(기준점, 반경)은 rules/ports.yaml에서 읽는다.
꺼짐(clear)과 모름(unknown)을 가른다: 꺼짐은 확인했고 문제가 없다는 뜻, 모름은 확인할 값이 없다는 뜻이다.
v1 backend/app/services/judge/signals.py(태그 v1-final)의 판단을 옮겼다. 달라진 것:
  - 부산 고정이 없다. 양륙항 코드와 항만 표로 본다. 항만 값이 없으면 그 신호는 모름이다.
  - 판매일 넘김 신호가 없다. 여유 일수로 등급이 정한다 (설계 2절 결정 13).
[주의] 배 신호의 목적지 원문(Position.dest)은 값에 넣지 않는다. 지시문이 섞일 수 있는 자유 글이다(설계 12절).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from marvia.identify.models import CargoFacts
from marvia.tools.ports import Port, port
from marvia.tools.rules import load_rules
from marvia.tools.verdict import Signal
from marvia.tools.vessel import KST, PortSchedule, Position, TrackPoint, as_utc, is_port_code, other_port

EARTH_RADIUS_NM = 3440.065  # 지구 반지름(해리). 기준값이 아니라 거리 공식의 상수다


def _nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    """두 점 사이 대권 거리(해리)."""
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(h))


def _hours(later: datetime, earlier: datetime) -> float:
    return abs((as_utc(later) - as_utc(earlier)).total_seconds()) / 3600


def _signal(signal_id: str, state: str, value: str) -> Signal:
    return Signal.model_validate({"id": signal_id, "state": state, "value": value})


def eta_gap_hours(ais_eta: datetime, planned: datetime) -> float:
    """배 신호 ETA와 해수부 입항 예정의 차이(시간)."""
    # [왜] 해수부 예정이 한국 시각 00:00이면 날짜만 신고하고 시각을 00:00으로 채운 값으로 본다(v1 부산 실측
    #      838건의 2~9%). 그날 하루를 범위로 보고 범위 밖으로 벗어난 만큼만 센다. 00:00을 시각으로 쓰면
    #      같은 날 오후 도착이 12시간 넘게 어긋난 것으로 잡힌다
    ais, plan = as_utc(ais_eta), as_utc(planned)
    local = plan.astimezone(KST)
    if (local.hour, local.minute) != (0, 0):
        return round(_hours(ais, plan), 1)
    end = plan + timedelta(days=1)
    if plan <= ais <= end:
        return 0.0
    return round(_hours(ais, plan if ais < plan else end), 1)


def _position_stale(position: Position | None, now: datetime, cuts: dict) -> Signal:
    if position is None or position.last_time is None:
        return _signal("position_stale", "unknown", "위치 없음")
    gap = _hours(now, position.last_time)
    return _signal(
        "position_stale", "triggered" if gap > cuts["position_stale_hours"] else "clear", f"{gap:.1f}시간 전"
    )


def _eta_conflict(
    position: Position | None, schedule: PortSchedule | None, port_code: str | None, cuts: dict
) -> Signal:
    ais_eta = position.ais_eta if position else None
    planned = schedule.planned_arrival if schedule else None
    if ais_eta is None or planned is None:
        return _signal(
            "eta_conflict", "unknown", "배 신호 ETA 없음" if ais_eta is None else "해수부 입항 예정 없음"
        )
    elsewhere = other_port(position, port_code)
    if elsewhere:
        # [왜] 배 신호 ETA는 그 배가 적은 목적지의 도착 시각이다. 다른 항구면 이 항만의 예정과 견주지 않는다
        return _signal("eta_conflict", "unknown", f"배 신호 ETA는 {elsewhere} 도착 시각")
    gap = eta_gap_hours(ais_eta, planned)
    return _signal(
        "eta_conflict", "triggered" if gap > cuts["eta_conflict_hours"] else "clear", f"{gap}시간 차이"
    )


def _anchor_wait(
    position: Position | None, row: Port | None, now: datetime, history: list[TrackPoint], cuts: dict
) -> Signal:
    """항만 기준점 반경 안에서 느린 속도로 서 있는지, 서 있다면 얼마나 오래인지."""
    if row is None or row.ref is None or row.stop_radius_nm is None:
        # [왜] 다른 항만의 기준점으로 재지 않는다. 표에 없거나 기준점을 확인하지 못한 항만은 모름이다
        return _signal("anchor_wait", "unknown", "항만 기준점 없음")
    if position is None or position.sog is None:
        return _signal("anchor_wait", "unknown", "위치·속도 없음")
    ref, radius, limit = (row.ref.lat, row.ref.lng), row.stop_radius_nm, cuts["stop_speed_kn"]

    def stopped(lat: float, lng: float, sog: float) -> bool:
        return _nm((lat, lng), ref) <= radius and sog <= limit

    if not stopped(position.lat, position.lng, position.sog):
        return _signal(
            "anchor_wait", "clear", f"{_nm((position.lat, position.lng), ref):.1f}해리, {position.sog}노트"
        )
    # 지금 멈춰 있다. 얼마나 오래인지는 지난 위치로 잰다: 최신부터 거슬러 올라가 멈춘 점이 이어진 구간의 길이
    points = sorted(history, key=lambda p: as_utc(p.at))
    last = position.last_time
    if last is not None and (not points or as_utc(last) > as_utc(points[-1].at)):
        points.append(TrackPoint(at=last, lat=position.lat, lng=position.lng, sog=position.sog))
    run: list[TrackPoint] = []
    saw_moving = False
    for point in reversed(points):
        if point.sog is None:
            break  # 속도를 모르는 점에서 멈춘다. 그 앞은 이어졌는지 모른다
        if not stopped(point.lat, point.lng, point.sog):
            saw_moving = True
            break
        run.append(point)
    if not run:
        return _signal("anchor_wait", "unknown", "지난 위치 없음")
    span = _hours(run[0].at, run[-1].at)
    value = f"{len(run)}회 연속 정지 {span:.0f}시간"
    if span >= cuts["stop_hours"]:
        return _signal("anchor_wait", "triggered", value)
    # [왜] 그보다 짧은데 그 앞에 움직이던 점이 있으면 멈추기 시작한 때를 본 것이라 꺼짐이다.
    #      멈춘 채로 시작하면 언제부터 멈췄는지 모른다
    return _signal("anchor_wait", "clear" if saw_moving else "unknown", value)


def _dest_changed(position: Position | None, port_code: str | None) -> Signal:
    """배 신호의 목적지가 이 화물의 양륙항이 아닌가. 값은 항구 코드나 broken·empty뿐이다(원문은 안 넣는다)."""
    if position is None:
        return _signal("dest_changed", "unknown", "위치 없음")
    mine = (port_code or "").strip().upper()
    if not mine:
        return _signal("dest_changed", "unknown", "양륙항 코드 없음")
    code = (position.dest_code or "").strip().upper()
    if code == mine:
        return _signal("dest_changed", "clear", code)
    if is_port_code(code):
        return _signal("dest_changed", "triggered", code)
    # [왜] 깨진 글자와 빈 값은 선원 입력 오류일 수 있다. 등급을 올리지 않고 확신을 낮춘다(verdict.yaml)
    broken = bool(code or (position.dest or "").strip())
    return _signal("dest_changed", "triggered", "broken" if broken else "empty")


def _navstat_mismatch(position: Position | None, cuts: dict) -> Signal:
    if position is None or position.navstat is None or position.sog is None:
        return _signal("navstat_mismatch", "unknown", "항해상태·속도 없음")
    value = f"상태 {position.navstat}, {position.sog}노트"
    moored = position.navstat in cuts["navstat_moored"] and position.sog > cuts["navstat_moored_max_kn"]
    underway = position.navstat in cuts["navstat_underway"] and position.sog < cuts["navstat_underway_min_kn"]
    return _signal("navstat_mismatch", "triggered" if moored or underway else "clear", value)


def _stage_key(name: str) -> str:
    """단계 이름 비교용: 띄어쓰기만 다른 이름("수입신고 수리", "수입신고수리")을 같게 본다."""
    return "".join(name.split())


def _customs_hold(facts: CargoFacts | None, cuts: dict) -> Signal:
    """통관이 멈춘 단계인가. 단계 이름을 목록과 정확히 맞춘다. 목록에 없는 이름은 모르는 단계다."""
    if facts is None or not facts.stage:
        return _signal("customs_hold", "unknown", "통관 정보 없음")
    key = _stage_key(facts.stage)
    if key in {_stage_key(name) for name in cuts["hold_stages"]}:
        return _signal("customs_hold", "triggered", facts.stage)
    if key in {_stage_key(name) for name in cuts["known_stages"]}:
        return _signal("customs_hold", "clear", facts.stage)
    # [왜] 낯선 이름을 멈춤으로도, 정상으로도 치지 않는다. 값에는 바깥에서 온 이름을 넣지 않는다
    return _signal("customs_hold", "unknown", "모르는 단계")


def compute(
    facts: CargoFacts | None,
    position: Position | None,
    schedule: PortSchedule | None,
    *,
    now: datetime,
    history: list[TrackPoint] | None = None,
) -> list[Signal]:
    """화물 사실, 배 위치, 입항 일정으로 신호 여섯 개를 낸다. 순서는 rules/verdict.yaml signal_ids다.

    history는 같은 배의 지난 위치다. 없으면 항구 앞 정지의 지속 시간을 잴 수 없어 그 신호는 모름이 된다.
    """
    rules = load_rules("verdict")
    cuts = rules["signals"]
    port_code = facts.port_code if facts else None
    made = {
        "customs_hold": _customs_hold(facts, cuts),
        "anchor_wait": _anchor_wait(position, port(port_code), now, list(history or []), cuts),
        "dest_changed": _dest_changed(position, port_code),
        "position_stale": _position_stale(position, now, cuts),
        "eta_conflict": _eta_conflict(position, schedule, port_code, cuts),
        "navstat_mismatch": _navstat_mismatch(position, cuts),
    }
    return [made[name] for name in rules["signal_ids"]]
