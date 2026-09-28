"""C-8 여유 일수와 신뢰 ETA 테스트. 라우터와 신호 계산이 같은 함수를 쓰므로 여기서 한 번 확인한다."""
from datetime import date, datetime, timezone

from backend.app.services.evidence import days_margin
from backend.app.services.signals import trusted_eta


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
