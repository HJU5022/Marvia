"""C-8 여유 일수와 신뢰 ETA 테스트. 라우터와 신호 계산이 같은 함수를 쓰므로 여기서 한 번 확인한다."""
from datetime import date, datetime, timezone

from backend.app.schemas.customs import CustomsRecord
from backend.app.services.judge.evidence import build, days_margin
from backend.app.services.judge.signals import trusted_eta


def test_days_margin_counts_days_to_sale():
    eta = datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc)  # 한국 10/5 12시
    assert days_margin(eta, date(2026, 10, 10)) == 5
    assert days_margin(eta, date(2026, 10, 3)) == -2  # 음수 = 판매 예정일을 넘김


def test_days_margin_uses_korean_date():
    """UTC 10/4 16시 = 한국 10/5 새벽 1시. 한국 날짜로 세야 하루가 어긋나지 않는다 (SDD 5.8)."""
    eta = datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc)
    assert days_margin(eta, date(2026, 10, 10)) == 5


def test_days_margin_is_none_without_input():
    assert days_margin(None, date(2026, 10, 10)) is None
    assert days_margin(datetime(2026, 10, 5, tzinfo=timezone.utc), None) is None


def test_trusted_eta_follows_priority():
    """rules.md priority: 해수부 실제 입항 > 해수부 입항 예정 > AIS ETA."""
    position = {"ais_eta": "2026-10-07T00:00:00+00:00"}
    planned = {"planned_arrival": "2026-10-06T00:00:00+00:00", "actual_arrival": None}
    actual = {"planned_arrival": "2026-10-06T00:00:00+00:00", "actual_arrival": "2026-10-05T00:00:00+00:00"}

    assert trusted_eta(position, None).day == 7
    assert trusted_eta(position, planned).day == 6
    assert trusted_eta(position, actual).day == 5


def test_trusted_eta_ignores_tool_errors():
    """도구가 실패하면 {error: ...}가 온다. 그 값은 건너뛴다."""
    assert trusted_eta({"error": {"code": "timeout"}}, {"error": {"code": "timeout"}}) is None


# ── 근거 카드 조립 (SDD 5.8 "도구 응답마다 Evidence 1건 이상") ──

NOW = datetime(2026, 9, 28, 3, 0, tzinfo=timezone.utc)
CUSTOMS = CustomsRecord(ship_name="TEST STAR", stage_name="반입신고", entry_date=datetime(2026, 10, 1),
                        bl_masked="TEST****0001", fetched_at=NOW)
POSITION = {"mmsi": 440999001, "lat": 35.1, "lng": 129.05, "sog": 0.0, "cog": 10.0, "navistat": 1,
            "dest": "BUSAN, KR", "destcode": "KRPUS", "ais_eta": "2026-09-30T23:00:00+00:00",
            "last_time": "2026-09-28T02:50:00+00:00", "fetched_at": NOW.isoformat()}
SCHEDULE = {"planned_arrival": "2026-10-01T00:00:00+00:00", "actual_arrival": None, "facility": "TEST부두",
            "control_events": [], "fetched_at": NOW.isoformat()}
DISTANCE = {"distance_nm": 120.5, "calc_hours_at_sog": None, "fetched_at": NOW.isoformat()}


def _by_source(cards):
    out = {}
    for c in cards:
        out.setdefault(c.source, {})[c.field] = c.value
    return out


def test_every_tool_answer_leaves_evidence():
    cards = build(CUSTOMS, POSITION, SCHEDULE, DISTANCE, trusted=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
                  margin=4, now=NOW)
    got = _by_source(cards)
    assert set(got) == {"unipass", "shipfinder", "mof", "searoute", "rule"}
    assert got["unipass"]["stage_name"] == "반입신고"
    assert got["shipfinder"]["dest"] == "BUSAN, KR"
    assert got["mof"]["facility"] == "TEST부두"
    assert got["searoute"]["distance_nm"] == "120.5"
    assert got["rule"]["days_margin"] == "4"


def test_times_are_korean_time_strings():
    """화면과 answer가 한국 시각으로 말하므로 근거 값도 한국 시각으로 적는다 (V7이 answer 숫자와 대조한다)."""
    got = _by_source(build(CUSTOMS, POSITION, SCHEDULE, None, trusted=None, margin=None, now=NOW))
    assert got["shipfinder"]["ais_eta"] == "2026-10-01 08:00"  # UTC 9/30 23시 = 한국 10/1 8시
    assert got["mof"]["planned_arrival"] == "2026-10-01 09:00"


def test_missing_or_failed_tools_leave_no_card():
    """값이 없거나 도구가 실패한 곳은 카드를 만들지 않는다. 없는 값을 근거로 쓰지 못하게."""
    cards = build(CUSTOMS, {"error": {"code": "timeout"}}, None, None, trusted=None, margin=None, now=NOW)
    got = _by_source(cards)
    assert set(got) == {"unipass"}
    assert "shed_name" not in got["unipass"]  # 값이 None이면 카드 없음


def test_signal_values_and_customs_history_are_evidence():
    """LLM은 신호 값과 통관 이력을 보고 답한다. 그 값도 근거 카드에 있어야 answer의 숫자를 대조할 수 있다 (V7)."""
    from backend.app.schemas.customs import CustomsStage
    from backend.app.schemas.signals import Signal, SignalSet

    customs = CUSTOMS.model_copy(update={"stage_history": [CustomsStage(code="", name="반입신고", at=datetime(2026, 9, 26, 7, 0))]})
    signal_set = SignalSet(signals=[Signal(id="anchor_wait", state="triggered", value="18.0시간 정지", threshold="24h", source="rule"),
                                    Signal(id="customs_hold", state="unknown", value="통관 정보 없음", threshold="-", source="unipass")],
                           freshness="fresh", distance_nm=None, calc_eta=None, eta_gap_hours=None, computed_at=NOW)
    got = _by_source(build(customs, None, None, None, trusted=None, margin=None, now=NOW, signals=signal_set))
    assert got["rule"]["anchor_wait"] == "18.0시간 정지"
    assert "customs_hold" not in got["rule"]  # unknown 신호는 근거가 아니다
    assert got["unipass"]["stage:반입신고"] == "2026-09-26 07:00"  # UNI-PASS 처리일시는 한국 시각으로 온다
