from marvia.tools.verdict import Signal, table_verdict


def on(signal_id: str, value: str = "") -> Signal:
    return Signal(id=signal_id, state="triggered", value=value)


def test_no_signal_is_fine():
    assert table_verdict([], None) == "fine"


def test_short_margin_alone_is_watch():
    assert table_verdict([], 1) == "watch"


def test_act_signal_is_act():
    assert table_verdict([on("customs_hold")], 10) == "act"


def test_other_signal_is_watch():
    assert table_verdict([on("position_stale")], None) == "watch"


def test_other_signal_with_short_margin_is_act():
    assert table_verdict([on("position_stale")], 1) == "act"


def test_unknown_does_not_count():
    assert table_verdict([Signal(id="anchor_wait", state="unknown")], None) == "fine"


def test_navstat_mismatch_is_ignored():
    assert table_verdict([on("navstat_mismatch")], None) == "fine"


def test_broken_destination_is_ignored():
    assert table_verdict([on("dest_changed", "broken")], None) == "fine"
