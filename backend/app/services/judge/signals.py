"""1층 신호 판정 (작업 C-4).

도구가 가져온 원본 값을 보고 신호 7종을 triggered·clear·unknown으로 가른다.
외부 호출이 없는 순수 함수라 같은 입력이면 항상 같은 결과가 나온다 (SDD 5.4).

여기서 판정하는 것은 "사실이 어떤가"까지다. "그래서 괜찮은가"(등급)는 services/judge/verdict.py가
skills/cargo-verdict/rules.md 판정 표로 정한다.
임계값은 코드에 적지 않고 skills/*/rules.md 프론트매터에서 읽는다 (C6, services/judge/rules.py가 합쳐 읽는다).

unknown과 clear를 구분한다. clear는 확인했고 문제가 없다는 뜻이고,
unknown은 확인할 값 자체가 없다는 뜻이다. act를 가르는 신호(cargo-verdict/rules.md gray_signals)가 unknown이면
회색 지대라 LLM이 표 등급 이상에서 고른다 (services/judge/verdict.py).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from backend.app.schemas.customs import CustomsRecord
from backend.app.schemas.signals import Freshness, Signal, SignalSet
from backend.app.services.judge.evidence import KST, days_margin
from backend.app.services.judge.rules import is_listed_stage, rule

# 부산 항구 코드(UN/LOCODE)는 skills/port-busan/rules.md busan_port_code에서 읽는다 (코드 상수였다)
# dest_changed 값 가운데 "배의 실제 목적지가 아니라 입력 오류일 수 있다"는 뜻인 둘.
# 판정 표의 세지 않는 목적지(cargo-verdict/rules.md ignore_dest_values, services/judge/verdict.py)와 평가 베이스라인이 같이 쓴다
DEST_BROKEN = "항구 코드로 읽을 수 없는 목적지 (깨진 목적지)"
DEST_EMPTY = "비어 있음"
# 판매일을 안 넣었을 때 sales_date_exceeded 값. 라우터와 베이스라인이 이 값으로 "판매일 없음"을 알아본다
SALE_DATE_MISSING = "판매 예정일 입력 없음"
EARTH_RADIUS_NM = 3440.065

# 항해상태(navistat) 코드. 1=정박, 5=계류, 0=항해 중(엔진 사용)
NAVSTAT_MOORED = (1, 5)
NAVSTAT_UNDERWAY = 0
# 항해상태 불일치 속도 기준(navstat_moored_max_kn, navstat_underway_min_kn)과
# 통관 보류 낱말(customs_hold_words)은 rules.md에서 읽는다 (판정 기준은 rules.md 한 곳)


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
    history: list[dict] | None = None,
    forwarder_eta=None,
) -> SignalSet:
    """도구 응답과 통관 정보를 받아 신호 7종을 판정한다.

    Args:
        position: get_live_position 결과. 없거나 error면 위치 관련 신호는 unknown
        schedule: get_port_schedule 결과
        distance: estimate_distance 결과
        customs: UNI-PASS 정제본
        sale_due_date: 판매 예정일. 신뢰 ETA가 이 날을 넘기면 sales_date_exceeded
        now: 기준 시각. 테스트에서 고정하려고 받는다
        history: 워커가 6시간마다 모은 같은 배의 위치 이력 [{"at", "lat", "lng", "sog"}]. anchor_wait의
            정지 지속 시간을 잰다 (결정 "위치 이력 + 24시간"). 없으면 지속 시간은 unknown
        forwarder_eta: 사용자가 되묻기에 답한 포워더 도착 통지서(A/N) 입항 예정일. 신뢰 ETA의 마지막 근거 (trusted_eta)
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
    elsewhere = _other_port(position)
    if ais_eta and mof_eta and elsewhere:
        # AIS ETA는 AIS 목적지 항구의 도착 시각이다. 목적지가 다른 항구면 부산 예정과 비교하지 않는다.
        # 전에는 오사카 ETA를 부산 예정과 비교해 "48시간 차이"라는 가짜 충돌을 냈다 (평가셋 B09 판정 방식)
        signals.append(_signal("eta_conflict", "unknown", f"AIS ETA는 {elsewhere} 도착 시각이라 비교 안 함",
                               f"{conflict_hours}시간", "shipfinder+mof"))
    elif ais_eta and mof_eta:
        eta_gap_hours, date_only = _eta_gap(ais_eta, mof_eta)
        state = "triggered" if eta_gap_hours > conflict_hours else "clear"
        value = f"{eta_gap_hours}시간 차이" + (" (해수부는 날짜만 신고)" if date_only else "")
        signals.append(_signal("eta_conflict", state, value, f"{conflict_hours}시간", "shipfinder+mof"))
    else:
        missing = "AIS ETA 없음" if not ais_eta else "해수부 입항예정 없음"
        signals.append(_signal("eta_conflict", "unknown", missing, f"{conflict_hours}시간", "shipfinder+mof"))

    # 3. anchor_wait: 부산 인근에서 오래 서 있나
    signals.append(_anchor_wait(position, last_time, now, history))

    # 4. dest_changed: 목적지가 부산이 아니거나 깨졌나
    if position is None:
        signals.append(_signal("dest_changed", "unknown", "위치 없음", rule("busan_port_code"), "shipfinder"))
    else:
        signals.append(_dest_changed(position))

    # 5. navstat_mismatch: 항해상태와 속도가 서로 안 맞나
    signals.append(_navstat_mismatch(position))

    # 6. customs_hold: 통관이 검사·보류로 잡혔나
    signals.append(_customs_hold(customs))

    # 7. sales_date_exceeded: 신뢰 ETA가 판매 예정일을 넘기나
    signals.append(_sales_date(trusted_eta(position, schedule, forwarder_eta), sale_due_date))

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


def _anchor_wait(position: dict | None, last_time: datetime | None, now: datetime,
                 history: list[dict] | None = None) -> Signal:
    """부산 반경 안에서 느린 속도로 서 있는지, 서 있다면 얼마나 오래인지 (SDD 5.4, 결정 "위치 이력 + 24시간").

    지금 위치가 멈춤이 아니면 clear. 멈춤이면 위치 이력(워커 6시간 간격)을 최신부터 거슬러 올라가
    멈춘 점이 이어진 구간의 길이(가장 오래된 멈춘 점 ~ 가장 최근 멈춘 점)를 잰다.
      - 구간이 anchor_wait_hours 이상 → triggered (평가셋 B08: 30시간)
      - 그보다 짧고, 그 앞에 움직이던 점이 있다 → clear. 멈추기 시작한 때를 봤다 (평가셋 B04: 18시간, N03)
      - 그보다 짧고, 이력이 멈춘 채로 시작한다 → unknown. 언제부터 멈췄는지 모른다
    전에는 이력을 받는 자리가 없어서 멈춰 있으면 늘 unknown이었고, B08(30시간 정박)을 놓쳤다.
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

    # 부산 반경 안에서 멈춰 있다. 얼마나 오래인지는 위치 이력으로 잰다
    here = f"{distance_nm:.1f}해리에서 {position['sog']}노트"

    def stopped(point: dict) -> bool | None:
        """이 점이 부산 반경 안 멈춤인가. 속도가 없으면 None(판단 불가)."""
        if point.get("sog") is None:
            return None
        near = _great_circle_nm((point["lat"], point["lng"]), (ref["lat"], ref["lng"])) <= radius
        return near and point["sog"] <= speed_limit

    points = sorted(
        ({**p, "at": _as_utc(_parse_dt(p.get("at")))} for p in (history or [])),
        key=lambda p: p["at"] or datetime.min.replace(tzinfo=timezone.utc),
    )
    points = [p for p in points if p["at"] is not None]
    # 지금 위치도 한 점으로 넣는다. 이력의 마지막 점보다 새로울 때만 (같은 보고를 두 번 세지 않게)
    if last_time and (not points or last_time > points[-1]["at"]):
        points.append({"at": last_time, "lat": position["lat"], "lng": position["lng"], "sog": position["sog"]})

    run: list[dict] = []  # 최신부터 이어진 멈춘 점들
    saw_moving = False
    for point in reversed(points):
        state = stopped(point)
        if state is None:
            break  # 속도를 모르는 점에서 멈춘다. 그 앞은 이어졌는지 모른다
        if not state:
            saw_moving = True
            break
        run.append(point)

    if not run:
        return _signal("anchor_wait", "unknown", f"{here}, 위치 이력 없음", threshold, "shipfinder")
    span = _hours_between(run[0]["at"], run[-1]["at"])
    value = f"{here}, 이력 {len(run)}회 연속 정지 {span:.0f}시간"
    if span >= wait_hours:
        return _signal("anchor_wait", "triggered", value, threshold, "shipfinder")
    if saw_moving:
        return _signal("anchor_wait", "clear", value, threshold, "shipfinder")
    return _signal("anchor_wait", "unknown", f"{value}, 지속 시간 미확인", threshold, "shipfinder")


def _is_port_code(code: str) -> bool:
    """UN/LOCODE 모양인가: 나라 2글자 + 항구 3글자(영문 또는 숫자 2~9). 예: KRPUS, JPOSA.

    ShipFinder destcode는 AIS 목적지 글자를 항구 코드로 읽은 값이다. 이 모양이 아니면(비었거나 깨짐)
    배가 어디로 간다고 말할 근거가 못 된다 (skills/ais-reliability "깨진 목적지").
    """
    return len(code) == 5 and code[:2].isalpha() and code[:2].isascii() \
        and all(ch.isascii() and (ch.isalpha() or ch in "23456789") for ch in code[2:])


def _other_port(position: dict | None) -> str | None:
    """AIS 목적지가 부산이 아닌 '진짜' 다른 항구 코드면 그 코드. 부산이거나 깨졌거나 없으면 None."""
    code = ((position or {}).get("destcode") or "").strip().upper()
    return code if _is_port_code(code) and code != rule("busan_port_code") else None


def _dest_changed(position: dict) -> Signal:
    """목적지가 부산이 아니면 triggered. 값에는 '다른 항구'인지 '깨짐'인지를 나눠 적는다.

    둘 다 triggered지만 뜻이 다르다. 다른 항구(예: JPOSA)는 경로 변경 가능성이라 확인이 필요하고,
    깨진 글자는 선원 입력 오류일 수 있어 다른 근거가 정상이면 근거로 쓰지 않는다 (SKILL.md 오류 사례 표).
    전에는 둘 다 코드 그대로 또는 "비어 있음"으로만 넘겨 LLM이 구분하지 못했다 (평가셋 B03·B09).
    AIS 목적지 원문은 값에 넣지 않는다. 지시문이 섞일 수 있는 자유 입력이라서다 (SDD 7절, 평가셋 주입 문항).
    """
    code = (position.get("destcode") or "").strip().upper()
    busan = rule("busan_port_code")  # port-busan/rules.md
    if code == busan:
        return _signal("dest_changed", "clear", code, busan, "shipfinder")
    if _is_port_code(code):
        value = f"다른 항구 {code}"
    elif code or (position.get("dest") or "").strip():
        value = DEST_BROKEN
    else:
        value = DEST_EMPTY
    return _signal("dest_changed", "triggered", value, busan, "shipfinder")


def _navstat_mismatch(position: dict | None) -> Signal:
    moored_max, underway_min = rule("navstat_moored_max_kn"), rule("navstat_underway_min_kn")
    threshold = f"정박·계류면 {moored_max}노트 이하, 항해 중이면 {underway_min}노트 이상"
    if position is None or position.get("navistat") is None or position.get("sog") is None:
        return _signal("navstat_mismatch", "unknown", "항해상태·속도 없음", threshold, "shipfinder")

    navistat, sog = position["navistat"], position["sog"]
    value = f"상태 {navistat}, {sog}노트"
    if navistat in NAVSTAT_MOORED and sog > moored_max:
        return _signal("navstat_mismatch", "triggered", f"{value} (정박인데 움직임)", threshold, "shipfinder")
    if navistat == NAVSTAT_UNDERWAY and sog < underway_min:
        return _signal("navstat_mismatch", "triggered", f"{value} (항해 중인데 멈춤)", threshold, "shipfinder")
    return _signal("navstat_mismatch", "clear", value, threshold, "shipfinder")


def _customs_hold(customs: CustomsRecord | None) -> Signal:
    hold_words = rule("customs_hold_words")
    threshold = "·".join(hold_words)
    if customs is None or not customs.stage_name:
        return _signal("customs_hold", "unknown", "통관 정보 없음", threshold, "unipass")

    stage = customs.stage_name
    if any(word in stage for word in hold_words):
        return _signal("customs_hold", "triggered", stage, threshold, "unipass")
    return _signal("customs_hold", "clear", stage, threshold, "unipass")


def needs_broker(stage_name: str) -> bool:
    """관세사가 봐야 하는 단계인가. 전에는 LLM이 정했고 프롬프트와 Skill에 조건이 따로 적혀 어긋났다.
    결정은 코드 한 곳이 한다. LLM은 이 값을 입력으로 받아 설명만 한다.

    true: customs-stages/rules.md customs_hold_words(검사·보류 등) 낱말이 들어간 단계(customs_hold 신호와 같은 기준),
          또는 같은 파일 customs_stages 목록에 없는 단계
    false: 목록에 있는 정상 단계. 그 단계의 todo(사용자가 할 일)에 관세사가 나와도 정상 단계면 false다
    """
    if any(word in stage_name for word in rule("customs_hold_words")):
        return True
    return not is_listed_stage(stage_name)


def _eta_gap(ais_eta: datetime, mof_eta: datetime) -> tuple[float, bool]:
    """AIS ETA와 해수부 입항 예정의 차이(시간)와, 해수부 값이 날짜만인지를 돌려준다.

    해수부 예정이 한국 시각 정확히 00:00이면 날짜만 신고하고 시각을 00:00으로 채운 값으로 본다.
    부산 입항 신고 838건 실측에서 2~9%가 00:00이었고, 00:00이 다른 정각보다 몰려 있었다.
    이때는 그날 하루(00:00~24:00)를 범위로 보고, AIS ETA가 범위 밖으로 벗어난 만큼만 차이로 센다.
    00:00을 그대로 시각으로 쓰면 같은 날 오후 도착도 12시간 넘게 어긋난 것으로 잡혀 eta_conflict가 가짜로 켜진다.
    """
    local = mof_eta.astimezone(KST)
    if (local.hour, local.minute) != (0, 0):
        return round(_hours_between(ais_eta, mof_eta), 1), False

    day_start, day_end = mof_eta, mof_eta + timedelta(days=1)
    if day_start <= ais_eta <= day_end:
        return 0.0, True
    edge = day_start if ais_eta < day_start else day_end
    return round(_hours_between(ais_eta, edge), 1), True


def trusted_eta(position: dict | None, schedule: dict | None, forwarder_eta=None) -> datetime | None:
    """믿을 만한 도착 예정 시각. rules.md priority 순서로 첫 유효값을 쓴다 (SDD 5.8).

    해수부 실제 입항(actual_arrival) > 해수부 입항 예정(planned_arrival) > AIS ETA.
    AIS 목적지 문자열은 시각이 아니라서 여기엔 없다. 라우터도 이 함수를 불러 days_margin을 계산한다.
    AIS 목적지가 다른 항구면 AIS ETA는 그 항구 도착 시각이라 부산 도착으로 쓰지 않는다 (eta_conflict와 같은 이유, 평가셋 B09).
    마지막 근거는 사용자가 알려 준 포워더 A/N 입항 예정일(날짜만, 한국 날짜 0시로 본다). 도착일을 몰라 되물었으면
    받은 날짜로 여유 일수를 세야 되묻기가 쓸모 있다 (결정 D6. 전에는 받고도 쓰지 않았다)
    """
    position = position if position and "error" not in position else None
    schedule = schedule if schedule and "error" not in schedule else None
    for value in (
        (schedule or {}).get("actual_arrival"),
        (schedule or {}).get("planned_arrival"),
        None if _other_port(position) else (position or {}).get("ais_eta"),
        datetime.combine(forwarder_eta, datetime.min.time(), tzinfo=KST) if forwarder_eta else None,
    ):
        found = _as_utc(_parse_dt(value))
        if found:
            return found
    return None


def _sales_date(trusted: datetime | None, sale_due_date) -> Signal:
    threshold = "판매 예정일"
    margin_days = days_margin(trusted, sale_due_date)  # 한국 날짜로 센다. 라우터와 같은 함수 (evidence.py)
    if margin_days is None:
        # 판매일은 선택 입력이다. 없으면 이 신호는 판정에 쓰지 않는다 (routers/agent.py _judged)
        missing = SALE_DATE_MISSING if sale_due_date is None else "신뢰 ETA 없음"
        return _signal("sales_date_exceeded", "unknown", missing, threshold, "rule")

    value = f"여유 {margin_days}일"
    return _signal("sales_date_exceeded", "triggered" if margin_days < 0 else "clear", value, threshold, "rule")
