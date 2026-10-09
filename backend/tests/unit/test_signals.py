"""C-4 1층 신호 판정 테스트. 신호 7종 × triggered·clear·unknown (SDD 9절)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.app.schemas.customs import CustomsRecord
from backend.app.services.judge.signals import compute, trusted_eta

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _position(**over) -> dict:
    base = {
        "mmsi": 440999001,
        "lat": 35.12,
        "lng": 129.05,
        "sog": 10.0,
        "cog": 180.0,
        "navistat": 0,
        "dest": "BUSAN, KR",
        "destcode": "KRPUS",
        "ais_eta": None,
        "last_time": (NOW - timedelta(hours=1)).isoformat(),
        "source": "shipfinder",
        "fetched_at": NOW.isoformat(),
    }
    return {**base, **over}


def _customs(stage_name: str = "입항보고") -> CustomsRecord:
    return CustomsRecord(stage_name=stage_name, bl_masked="TEST****0001", fetched_at=NOW)


def _state(result, signal_id: str) -> str:
    return next(s.state for s in result.signals if s.id == signal_id)


def test_all_seven_signals_present():
    result = compute(_position(), None, None, None, now=NOW)
    assert len(result.signals) == 7
    assert len({s.id for s in result.signals}) == 7


@pytest.mark.parametrize(
    "hours_ago, expected, freshness",
    [(1, "clear", "fresh"), (7, "triggered", "stale")],
)
def test_position_stale_uses_rules_threshold(hours_ago, expected, freshness):
    result = compute(_position(last_time=(NOW - timedelta(hours=hours_ago)).isoformat()), None, None, None, now=NOW)
    assert _state(result, "position_stale") == expected
    assert result.freshness == freshness


def test_position_stale_unknown_without_position():
    result = compute(None, None, None, None, now=NOW)
    assert _state(result, "position_stale") == "unknown" and result.freshness == "unknown"


def test_tool_error_is_treated_as_missing():
    """도구가 error를 돌려주면 값이 없는 것으로 본다."""
    result = compute({"error": {"code": "rate_limited"}}, None, None, None, now=NOW)
    assert _state(result, "position_stale") == "unknown"


@pytest.mark.parametrize("gap_hours, expected", [(6, "clear"), (20, "triggered")])
def test_eta_conflict(gap_hours, expected):
    ais = NOW + timedelta(hours=24)
    schedule = {"planned_arrival": (ais + timedelta(hours=gap_hours)).isoformat(), "actual_arrival": None}
    result = compute(_position(ais_eta=ais.isoformat()), schedule, None, None, now=NOW)
    assert _state(result, "eta_conflict") == expected
    assert result.eta_gap_hours == gap_hours


KST = timezone(timedelta(hours=9))


@pytest.mark.parametrize(
    "ais_kst, expected, gap",
    [
        (datetime(2026, 9, 25, 14, 0, tzinfo=KST), "clear", 0.0),       # 신고한 날 안 → 차이 0 (옛 계산은 14시간이라 켜졌다)
        (datetime(2026, 9, 24, 23, 0, tzinfo=KST), "clear", 1.0),       # 전날 밤 23시 → 그날 시작까지 1시간
        (datetime(2026, 9, 26, 20, 0, tzinfo=KST), "triggered", 20.0),  # 다음 날 20시 → 그날 끝(24시)에서 20시간
    ],
)
def test_eta_conflict_date_only_plan(ais_kst, expected, gap):
    """해수부 입항 예정이 한국 시각 정확히 00:00이면 날짜만 신고한 값으로 보고 그날 하루를 범위로 비교한다.: 부산 입항 신고 838건 중 2~9%가 00:00. 00:00을 시각으로 보면 가짜로 켜진다."""
    schedule = {"planned_arrival": datetime(2026, 9, 25, 0, 0, tzinfo=KST).isoformat(), "actual_arrival": None}
    result = compute(_position(ais_eta=ais_kst.isoformat()), schedule, None, None, now=NOW)
    assert _state(result, "eta_conflict") == expected
    assert result.eta_gap_hours == gap


def test_eta_conflict_unknown_when_one_side_missing():
    result = compute(_position(ais_eta=(NOW + timedelta(hours=10)).isoformat()), None, None, None, now=NOW)
    assert _state(result, "eta_conflict") == "unknown" and result.eta_gap_hours is None


def test_anchor_wait_clear_when_moving_or_far():
    near_moving = compute(_position(sog=8.0), None, None, None, now=NOW)
    far_stopped = compute(_position(lat=33.0, lng=127.0, sog=0.0), None, None, None, now=NOW)
    assert _state(near_moving, "anchor_wait") == "clear"
    assert _state(far_stopped, "anchor_wait") == "clear"


def test_anchor_wait_unknown_when_stopped_near_busan():
    """위치 이력이 없으면 언제부터 멈췄는지 몰라 unknown이다."""
    result = compute(_position(sog=0.0), None, None, None, now=NOW)
    signal = next(s for s in result.signals if s.id == "anchor_wait")
    assert signal.state == "unknown" and "지속 시간 미확인" in signal.value


def _history(*points) -> list[dict]:
    """(몇 시간 전, 속도) 목록을 워커 위치 이력 모양으로. 위치는 부산 앞(평가셋 B08과 같은 35.0, 129.1)."""
    return [{"at": (NOW - timedelta(hours=h)).isoformat(), "lat": 35.0, "lng": 129.1, "sog": sog} for h, sog in points]


def test_anchor_wait_triggered_after_long_stop():
    """평가셋 B08: 움직이다가 6시간 간격 6번 연속 정지, 30시간 → triggered."""
    history = _history((37, 10.0), (31, 0.2), (25, 0.2), (19, 0.2), (13, 0.2), (7, 0.2), (1, 0.2))
    result = compute(_position(lat=35.0, lng=129.1, sog=0.2), None, None, None, now=NOW, history=history)
    signal = next(s for s in result.signals if s.id == "anchor_wait")
    assert signal.state == "triggered" and "30시간" in signal.value


def test_anchor_wait_clear_after_short_stop_seen_from_start():
    """평가셋 B04: 움직이다가 18시간 정지. 멈추기 시작한 때를 봤고 기준(24시간) 미만 → clear."""
    history = _history((25, 10.0), (19, 0.2), (13, 0.2), (7, 0.2), (1, 0.2))
    result = compute(_position(lat=35.0, lng=129.1, sog=0.2), None, None, None, now=NOW, history=history)
    assert _state(result, "anchor_wait") == "clear"


def test_anchor_wait_unknown_when_history_starts_stopped():
    """이력이 처음부터 멈춰 있고 기준보다 짧으면 언제부터인지 몰라 unknown."""
    history = _history((13, 0.2), (7, 0.2), (1, 0.2))
    result = compute(_position(lat=35.0, lng=129.1, sog=0.2), None, None, None, now=NOW, history=history)
    assert _state(result, "anchor_wait") == "unknown"


def test_anchor_wait_stops_counting_at_unknown_speed():
    """속도가 없는 점에서 거슬러 오르기를 멈춘다. 그 앞 정지는 이어졌는지 모른다."""
    history = _history((40, 0.2), (31, None), (7, 0.2), (1, 0.2))
    result = compute(_position(lat=35.0, lng=129.1, sog=0.2), None, None, None, now=NOW, history=history)
    assert _state(result, "anchor_wait") == "unknown"


@pytest.mark.parametrize(
    "destcode, expected",
    [("KRPUS", "clear"), ("VNDQR", "triggered"), ("", "triggered")],
)
def test_dest_changed(destcode, expected):
    result = compute(_position(destcode=destcode), None, None, None, now=NOW)
    assert _state(result, "dest_changed") == expected


@pytest.mark.parametrize(
    "destcode, dest, words",
    [
        ("JPOSA", "OSAKA", "다른 항구 JPOSA"),                   # 평가셋 B09: 진짜 다른 항구
        (None, "XX QZQZZZZZ", "깨진 목적지"),                    # 평가셋 B03: 코드로 못 읽는 글자
        ("QZ Q", "QZ Q", "깨진 목적지"),                         # 코드 칸은 있는데 항구 코드 모양이 아님
        (None, None, "비어 있음"),
    ],
)
def test_dest_changed_tells_broken_from_other_port(destcode, dest, words):
    """깨진 목적지와 다른 항구를 값으로 나눠 LLM에 넘긴다. 둘 다 triggered (평가셋 B03 fixture 설명)."""
    result = compute(_position(destcode=destcode, dest=dest), None, None, None, now=NOW)
    signal = next(s for s in result.signals if s.id == "dest_changed")
    assert signal.state == "triggered" and words in signal.value
    assert "XX QZQZZZZZ" not in signal.value  # 목적지 원문은 넣지 않는다 (SDD 7절 신뢰 경계)


def test_eta_conflict_skips_eta_of_other_port():
    """AIS 목적지가 다른 항구면 AIS ETA는 그 항구 도착 시각이라 부산 예정과 비교하지 않는다 (평가셋 B09)."""
    osaka_eta = NOW + timedelta(hours=24)
    schedule = {"planned_arrival": (NOW + timedelta(hours=72)).isoformat()}
    result = compute(_position(destcode="JPOSA", ais_eta=osaka_eta.isoformat()), schedule, None, None, now=NOW)
    signal = next(s for s in result.signals if s.id == "eta_conflict")
    assert signal.state == "unknown" and "JPOSA" in signal.value
    assert result.eta_gap_hours is None


def test_trusted_eta_ignores_ais_eta_of_other_port():
    """부산 도착 시각을 믿을 값으로 고를 때 다른 항구의 AIS ETA는 건너뛴다. 해수부 예정이 있으면 그것."""
    osaka_eta = (NOW + timedelta(hours=24)).isoformat()
    busan_plan = NOW + timedelta(hours=72)
    position = _position(destcode="JPOSA", ais_eta=osaka_eta)
    assert trusted_eta(position, {"planned_arrival": busan_plan.isoformat()}) == busan_plan
    assert trusted_eta(position, None) is None  # 부산 도착을 말해 주는 값이 없다
    assert trusted_eta(_position(destcode="KRPUS", ais_eta=osaka_eta), None) is not None  # 부산행이면 그대로 쓴다


@pytest.mark.parametrize(
    "navistat, sog, expected",
    [(0, 10.0, "clear"), (1, 0.0, "clear"), (1, 12.0, "triggered"), (0, 0.0, "triggered")],
)
def test_navstat_mismatch(navistat, sog, expected):
    result = compute(_position(navistat=navistat, sog=sog), None, None, None, now=NOW)
    assert _state(result, "navstat_mismatch") == expected


def test_navstat_unknown_without_values():
    result = compute(_position(navistat=None), None, None, None, now=NOW)
    assert _state(result, "navstat_mismatch") == "unknown"


@pytest.mark.parametrize(
    "stage, expected",
    [("입항보고", "clear"), ("검사대상 지정", "triggered"), ("통관보류", "triggered")],
)
def test_customs_hold(stage, expected):
    result = compute(_position(), None, None, _customs(stage), now=NOW)
    assert _state(result, "customs_hold") == expected


def test_customs_unknown_without_record():
    assert _state(compute(_position(), None, None, None, now=NOW), "customs_hold") == "unknown"


@pytest.mark.parametrize(
    "eta_offset_days, due_offset_days, expected",
    [(1, 5, "clear"), (5, 1, "triggered")],
)
def test_sales_date_exceeded(eta_offset_days, due_offset_days, expected):
    schedule = {"planned_arrival": (NOW + timedelta(days=eta_offset_days)).isoformat(), "actual_arrival": None}
    due = (NOW + timedelta(days=due_offset_days)).date()
    result = compute(_position(), schedule, None, None, sale_due_date=due, now=NOW)
    assert _state(result, "sales_date_exceeded") == expected


def test_sales_date_unknown_without_due_date():
    assert _state(compute(_position(), None, None, None, now=NOW), "sales_date_exceeded") == "unknown"


def test_actual_arrival_wins_over_planned():
    """신뢰 ETA는 해수부 실적이 우선이다 (rules.md priority)."""
    schedule = {
        "actual_arrival": (NOW - timedelta(days=1)).isoformat(),
        "planned_arrival": (NOW + timedelta(days=10)).isoformat(),
    }
    due = (NOW + timedelta(days=2)).date()
    result = compute(_position(), schedule, None, None, sale_due_date=due, now=NOW)
    assert _state(result, "sales_date_exceeded") == "clear"  # 이미 들어왔으므로 여유가 있다


def test_distance_and_calc_eta_carried():
    distance = {"distance_nm": 120.0, "calc_hours_at_sog": 10.0, "source": "searoute", "fetched_at": NOW.isoformat()}
    result = compute(_position(), None, distance, None, now=NOW)
    assert result.distance_nm == 120.0
    assert result.calc_eta == NOW + timedelta(hours=10)


def test_trusted_eta_falls_back_to_forwarder_eta():
    """해수부·AIS 도착일이 없으면 사용자가 알려 준 포워더 A/N 입항 예정일(한국 날짜 0시)을 쓴다 (D6)."""
    found = trusted_eta(_position(ais_eta=None), None, date(2026, 10, 1))
    assert found is not None and found.astimezone(timezone(timedelta(hours=9))).date() == date(2026, 10, 1)
    assert trusted_eta(_position(ais_eta=None), {"planned_arrival": NOW.isoformat()}, date(2026, 10, 1)) == NOW  # 해수부가 먼저


def test_sales_date_signal_says_when_sale_date_missing():
    """판매일을 안 넣으면 판매일 초과 신호는 unknown, 값으로 이유를 알린다 (선택 입력)."""
    result = compute(_position(), {"planned_arrival": NOW.isoformat()}, None, None, None, now=NOW)
    signal = next(s for s in result.signals if s.id == "sales_date_exceeded")
    assert signal.state == "unknown" and signal.value == "판매 예정일 입력 없음"

