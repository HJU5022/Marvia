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


# 신호 기준값 (계획 8a): 신호를 켜고 끄는 숫자는 코드가 아니라 rules/verdict.yaml에 있다


def test_signal_thresholds_live_in_the_rules_file():
    from marvia.tools.rules import load_rules

    rules = load_rules("verdict")
    cuts = rules["signals"]
    assert cuts["position_stale_hours"] == 6 and cuts["eta_conflict_hours"] == 12
    assert cuts["stop_speed_kn"] == 0.5 and cuts["stop_hours"] == 24
    assert cuts["navstat_moored"] == [1, 5] and cuts["navstat_underway"] == [0]
    assert cuts["navstat_moored_max_kn"] == 2.0 and cuts["navstat_underway_min_kn"] == 0.3
    # [왜] 통관 멈춤은 낱말이 아니라 단계 이름 목록으로 본다. 멈춤 목록과 아는 단계 목록이 겹치면 안 된다
    assert "검사지정" in cuts["hold_stages"] and "수입신고수리" in cuts["known_stages"]
    assert not set(cuts["hold_stages"]) & set(cuts["known_stages"])
    # [왜] 믿을 ETA의 순서도 규칙이다: 관제 실적, 최종 입항 신고, 입항 예정, 배 신호 ETA, 포워더 날짜
    assert rules["eta_priority"] == ["mof_actual", "mof_final", "mof_planned", "ais_eta", "forwarder_eta"]
    assert rules["margin_without_position"] == ["mof_actual", "mof_final", "mof_planned"]


def test_every_listed_signal_has_a_grade_or_a_confidence_role():
    from marvia.tools.rules import load_rules

    rules = load_rules("verdict")
    graded = set(rules["act_signals"]) | set(rules["alert_signals"]) | set(rules["watch_signals"])
    # [왜] 목록에 없는 신호는 켜져도 세지 않는다(grade의 주의 글). 계산하는 신호가 빠지면 조용히 사라진다
    assert set(rules["signal_ids"]) == graded | set(rules["input_error_signals"])
