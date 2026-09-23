"""1층 신호 판정 (작업 C-4).

도구가 가져온 원본 값을 보고 신호 7종을 triggered·clear·unknown으로 가른다.
외부 호출이 없는 순수 함수라 같은 입력이면 항상 같은 결과가 나온다 (SDD 5.4).

여기서 판정하는 것은 "사실이 어떤가"까지다. "그래서 괜찮은가"는 2층 LLM이 정한다.
임계값은 코드에 적지 않고 skills/ais-reliability/rules.md에서 읽는다 (C6).

unknown과 clear를 구분한다. clear는 확인했고 문제가 없다는 뜻이고,
unknown은 확인할 값 자체가 없다는 뜻이다. 결정적 신호가 unknown이면 2층은 판정하지 않고 되묻는다.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from backend.app.schemas.customs import CustomsRecord
from backend.app.schemas.signals import Freshness, Signal, SignalSet
from backend.app.services.rules import rule

BUSAN_PORT_CODE = "KRPUS"
EARTH_RADIUS_NM = 3440.065

# 항해상태(navistat) 코드. 1=정박, 5=계류, 0=항해 중(엔진 사용)
NAVSTAT_MOORED = (1, 5)
NAVSTAT_UNDERWAY = 0
MOORED_SPEED_KN = 2.0  # 정박·계류라면서 이보다 빠르면 값이 안 맞는다
UNDERWAY_SPEED_KN = 0.3  # 항해 중이라면서 이보다 느리면 값이 안 맞는다

# 통관 단계가 검사·보류로 잡혔는지 본다. 단계 코드 목록은 C-2에서 확정되므로
# 지금은 단계명에 이 낱말이 있는지로 가린다.
CUSTOMS_HOLD_WORDS = ("검사", "보류", "정지", "반송", "폐기")


def _great_circle_nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(h))


def _hours_between(later: datetime, earlier: datetime) -> float:
    return abs((later - earlier).total_seconds()) / 3600


def _as_utc(value: datetime | None) -> datetime | None:
    """시간대가 없는 값은 UTC로 본다. 비교하다 터지는 것을 막는다."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _signal(signal_id: str, state: str, value: str, threshold: str, source: str) -> Signal:
    return Signal(id=signal_id, state=state, value=value, threshold=threshold, source=source)


def compute(
    position: dict | None,
    schedule: dict | None,
    distance: dict | None,
    customs: CustomsRecord | None,
    sale_due_date=None,
    now: datetime | None = None,
) -> SignalSet:
    """도구 응답과 통관 정보를 받아 신호 7종을 판정한다.

    Args:
        position: get_live_position 결과. 없거나 error면 위치 관련 신호는 unknown
        schedule: get_port_schedule 결과
        distance: estimate_distance 결과
        customs: UNI-PASS 정제본
        sale_due_date: 판매 예정일. 신뢰 ETA가 이 날을 넘기면 sales_date_exceeded
        now: 기준 시각. 테스트에서 고정하려고 받는다
    """
    now = _as_utc(now) or datetime.now(timezone.utc)
    position = position if position and "error" not in position else None
    schedule = schedule if schedule and "error" not in schedule else None
    distance = distance if distance and "error" not in distance else None

    signals: list[Signal] = []
    stale_hours = rule("position_stale_hours")
    last_time = _as_utc(_parse_dt(position.get("last_time") if position else None))

    # 1. position_stale: 마지막 수신이 오래됐나
    if last_time is None:
        freshness: Freshness = "unknown"
        signals.append(_signal("position_stale", "unknown", "위치 없음", f"{stale_hours}시간", "shipfinder"))
    else:
        gap = _hours_between(now, last_time)
        triggered = gap > stale_hours
        freshness = "stale" if triggered else "fresh"
        signals.append(
            _signal("position_stale", "triggered" if triggered else "clear", f"{gap:.1f}시간 전", f"{stale_hours}시간", "shipfinder")
        )

    # 2. eta_conflict: AIS ETA와 해수부 입항 예정이 어긋나나
    ais_eta = _as_utc(_parse_dt(position.get("ais_eta") if position else None))
    mof_eta = _as_utc(_parse_dt((schedule or {}).get("planned_arrival")))
    eta_gap_hours = None
    conflict_hours = rule("eta_conflict_hours")
    if ais_eta and mof_eta:
        eta_gap_hours = round(_hours_between(ais_eta, mof_eta), 1)
        state = "triggered" if eta_gap_hours > conflict_hours else "clear"
        signals.append(_signal("eta_conflict", state, f"{eta_gap_hours}시간 차이", f"{conflict_hours}시간", "shipfinder+mof"))
    else:
        missing = "AIS ETA 없음" if not ais_eta else "해수부 입항예정 없음"
        signals.append(_signal("eta_conflict", "unknown", missing, f"{conflict_hours}시간", "shipfinder+mof"))

    # 3. anchor_wait: 부산 인근에서 오래 서 있나
    signals.append(_anchor_wait(position, last_time, now))

    # 4. dest_changed: 목적지가 부산이 아니거나 깨졌나
    if position is None:
        signals.append(_signal("dest_changed", "unknown", "위치 없음", BUSAN_PORT_CODE, "shipfinder"))
    else:
        destcode = (position.get("destcode") or "").strip().upper()
        state = "clear" if destcode == BUSAN_PORT_CODE else "triggered"
        signals.append(_signal("dest_changed", state, destcode or "비어 있음", BUSAN_PORT_CODE, "shipfinder"))

    # 5. navstat_mismatch: 항해상태와 속도가 서로 안 맞나
    signals.append(_navstat_mismatch(position))

    # 6. customs_hold: 통관이 검사·보류로 잡혔나
    signals.append(_customs_hold(customs))

    # 7. sales_date_exceeded: 신뢰 ETA가 판매 예정일을 넘기나
    trusted_eta = _as_utc(_parse_dt((schedule or {}).get("actual_arrival"))) or mof_eta or ais_eta
    signals.append(_sales_date(trusted_eta, sale_due_date))

    return SignalSet(
        signals=signals,
        freshness=freshness,
        distance_nm=(distance or {}).get("distance_nm"),
        calc_eta=_calc_eta(distance, now),
        eta_gap_hours=eta_gap_hours,
        computed_at=now,
    )


def _parse_dt(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _calc_eta(distance: dict | None, now: datetime) -> datetime | None:
    """남은 거리와 현재 속력으로 계산한 도착 시각. 근거리에서 크게 나오는 값이라 참고용이다."""
    hours = (distance or {}).get("calc_hours_at_sog")
    return now + timedelta(hours=hours) if hours else None


def _anchor_wait(position: dict | None, last_time: datetime | None, now: datetime) -> Signal:
    """부산 반경 안에서 느린 속도로 서 있는지. 지속 시간은 수집 이력이 있어야 알 수 있다 (D1).

    지금은 이력이 없어서, 조건에 맞으면 '정지 중'으로만 알리고 지속 시간 판정은 unknown으로 둔다.
    """
    speed_limit = rule("anchor_speed_kn")
    wait_hours = rule("anchor_wait_hours")
    radius = rule("busan_radius_nm")
    ref = rule("busan_ref")
    threshold = f"{radius}해리 안 {speed_limit}노트 이하 {wait_hours}시간"

    if position is None or position.get("sog") is None:
        return _signal("anchor_wait", "unknown", "위치·속도 없음", threshold, "shipfinder")

    distance_nm = _great_circle_nm((position["lat"], position["lng"]), (ref["lat"], ref["lng"]))
    if distance_nm > radius or position["sog"] > speed_limit:
        return _signal("anchor_wait", "clear", f"{distance_nm:.1f}해리, {position['sog']}노트", threshold, "shipfinder")

    # 부산 반경 안에서 멈춰 있다. 얼마나 오래인지는 수집 이력(D1)이 있어야 안다
    return _signal("anchor_wait", "unknown", f"{distance_nm:.1f}해리에서 {position['sog']}노트, 지속 시간 미확인", threshold, "shipfinder")


def _navstat_mismatch(position: dict | None) -> Signal:
    threshold = f"정박·계류면 {MOORED_SPEED_KN}노트 이하, 항해 중이면 {UNDERWAY_SPEED_KN}노트 이상"
    if position is None or position.get("navistat") is None or position.get("sog") is None:
        return _signal("navstat_mismatch", "unknown", "항해상태·속도 없음", threshold, "shipfinder")

    navistat, sog = position["navistat"], position["sog"]
    value = f"상태 {navistat}, {sog}노트"
    if navistat in NAVSTAT_MOORED and sog > MOORED_SPEED_KN:
        return _signal("navstat_mismatch", "triggered", f"{value} (정박인데 움직임)", threshold, "shipfinder")
    if navistat == NAVSTAT_UNDERWAY and sog < UNDERWAY_SPEED_KN:
        return _signal("navstat_mismatch", "triggered", f"{value} (항해 중인데 멈춤)", threshold, "shipfinder")
    return _signal("navstat_mismatch", "clear", value, threshold, "shipfinder")


def _customs_hold(customs: CustomsRecord | None) -> Signal:
    threshold = "·".join(CUSTOMS_HOLD_WORDS)
    if customs is None or not customs.stage_name:
        return _signal("customs_hold", "unknown", "통관 정보 없음", threshold, "unipass")

    stage = customs.stage_name
    if any(word in stage for word in CUSTOMS_HOLD_WORDS):
        return _signal("customs_hold", "triggered", stage, threshold, "unipass")
    return _signal("customs_hold", "clear", stage, threshold, "unipass")


def _sales_date(trusted_eta: datetime | None, sale_due_date) -> Signal:
    threshold = "판매 예정일"
    if trusted_eta is None or sale_due_date is None:
        return _signal("sales_date_exceeded", "unknown", "신뢰 ETA 또는 판매 예정일 없음", threshold, "rule")

    margin_days = (sale_due_date - trusted_eta.date()).days
    value = f"여유 {margin_days}일"
    return _signal("sales_date_exceeded", "triggered" if margin_days < 0 else "clear", value, threshold, "rule")
