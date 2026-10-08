"""evals/baseline_rules.py 판정 표 테스트. skills/cargo-verdict/rules.md 판정 표와 예외를 그대로 따르는지 본다. 키 없이 돈다."""
from datetime import datetime, timezone

import pytest

from backend.app.schemas.signals import Signal, SignalSet
from backend.app.services.judge.signals import DEST_BROKEN, DEST_EMPTY
from evals.baseline_rules import verdict_for

IDS = ["position_stale", "eta_conflict", "anchor_wait", "dest_changed",
       "navstat_mismatch", "customs_hold", "sales_date_exceeded"]


def _set(**on: str) -> SignalSet:
    """on에 준 신호만 triggered(값은 준 문자열), 나머지는 clear."""
    signals = [Signal(id=i, state="triggered" if i in on else "clear", value=on.get(i, "-"), threshold="-", source="test")
               for i in IDS]
    return SignalSet(signals=signals, freshness="fresh", distance_nm=None, calc_eta=None, eta_gap_hours=None,
                     computed_at=datetime(2026, 9, 22, tzinfo=timezone.utc))


@pytest.mark.parametrize("value", [DEST_BROKEN, DEST_EMPTY])
def test_broken_destination_alone_is_fine(value):
    """평가셋 B03: 깨진 목적지 하나만 켜졌으면 입력 오류로 보고 fine."""
    assert verdict_for(_set(dest_changed=value), margin=4) == "fine"


def test_other_port_is_still_watch():
    """다른 항구(예: JPOSA)는 예외가 아니다. 여유가 있으면 watch, 없으면 act (평가셋 B09 여유 1일)."""
    assert verdict_for(_set(dest_changed="다른 항구 JPOSA"), margin=4) == "watch"
    assert verdict_for(_set(dest_changed="다른 항구 JPOSA"), margin=1) == "act"


def test_navstat_mismatch_alone_is_fine():
    """평가셋 B06: 항해상태 불일치 하나만 켜졌으면 실제 상태는 다른 신호가 본다. fine."""
    assert verdict_for(_set(navstat_mismatch="상태 1, 12.0노트 (정박인데 움직임)"), margin=4) == "fine"


def test_act_signal_still_wins():
    """예외 신호가 있어도 act 신호가 켜지면 act."""
    assert verdict_for(_set(navstat_mismatch="-", anchor_wait="30시간"), margin=4) == "act"


def test_all_clear_but_tight_margin_is_watch():
    """D4: 켜진 신호가 없어도 여유가 margin_act_days(2) 미만이면 watch. 판매일이 없으면(None) fine."""
    assert verdict_for(_set(), margin=1) == "watch"
    assert verdict_for(_set(), margin=2) == "fine"
    assert verdict_for(_set(), margin=None) == "fine"

