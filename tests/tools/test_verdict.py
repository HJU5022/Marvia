from datetime import datetime, timedelta

from marvia.tools.verdict import Signal, confidence, grade, schedule


def on(signal_id: str, value: str = "") -> Signal:
    return Signal(id=signal_id, state="triggered", value=value)


# 등급: 순항·주의·경계·긴급


def test_no_signal_is_fine():
    assert grade([], None) == "fine"


def test_one_watch_signal_is_watch():
    assert grade([on("position_stale")], None) == "watch"


def test_two_watch_signals_are_alert():
    assert grade([on("position_stale"), on("eta_conflict")], None) == "alert"


def test_anchor_wait_is_alert():
    assert grade([on("anchor_wait")], None) == "alert"


def test_real_destination_change_is_alert():
    assert grade([on("dest_changed", "JPTYO")], None) == "alert"


def test_short_margin_is_alert():
    assert grade([], 1) == "alert"


def test_customs_hold_is_act():
    assert grade([on("customs_hold")], 10) == "act"


def test_sales_date_passed_is_act():
    assert grade([], -1) == "act"


def test_unknown_does_not_raise_grade():
    assert grade([Signal(id="anchor_wait", state="unknown")], None) == "fine"


def test_input_errors_do_not_raise_grade():
    assert grade([on("navstat_mismatch"), on("dest_changed", "broken")], None) == "fine"


# 확신: 확실·부분·불명


def test_not_identified_is_unknown():
    assert confidence([], identified=False, has_source=True) == "unknown"


def test_no_source_is_unknown():
    assert confidence([], identified=True, has_source=False) == "unknown"


def test_unknown_signal_is_partial():
    assert confidence([Signal(id="anchor_wait", state="unknown")], True, True) == "partial"


def test_input_error_is_partial():
    assert confidence([on("navstat_mismatch")], True, True) == "partial"


def test_all_judged_is_sure():
    assert confidence([on("customs_hold")], True, True) == "sure"


# 일정: 정시·우려·지연·초과

FIRST = datetime(2026, 10, 30, 9, 0)


def test_sales_date_passed_is_overdue():
    assert schedule([], -1, FIRST, FIRST) == "overdue"


def test_one_day_later_is_delayed():
    assert schedule([], None, FIRST, FIRST + timedelta(days=1)) == "delayed"


def test_half_day_later_is_not_delayed():
    assert schedule([], None, FIRST, FIRST + timedelta(hours=12)) == "on_time"


def test_eta_conflict_is_concern():
    assert schedule([on("eta_conflict")], None, FIRST, FIRST) == "concern"


def test_nothing_is_on_time():
    assert schedule([], 5, None, None) == "on_time"
