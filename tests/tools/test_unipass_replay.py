from marvia.identify.models import CargoFacts, ToolError
from marvia.tools.unipass_replay import lookup_cargo


def test_found():
    facts = lookup_cargo("DEMO0001")
    assert isinstance(facts, CargoFacts)
    assert (facts.stage, facts.port, facts.mrn) == ("반입신고", "부산", "26DEMO0001I")


def test_not_found_is_error_not_exception():
    err = lookup_cargo("NOPE00000")
    assert isinstance(err, ToolError)
    assert err.code == "not_found" and err.retryable is False


def test_error_message_has_no_number():
    err = lookup_cargo("NOPE00000")
    assert isinstance(err, ToolError)
    assert "NOPE00000" not in err.message
