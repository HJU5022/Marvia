import json

from marvia.identify.models import CargoFacts, ToolError
from marvia.identify.parse import is_container
from marvia.tools.unipass_replay import FIXTURES, lookup_cargo


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


def test_replay_facts_carry_valid_container_numbers():
    # [왜] 컨테이너 번호로 아는 화물을 찾는 시험의 바탕이다. 한 컨테이너에 화물 둘(DEMO0002·DEMO0003)도 있다
    facts = lookup_cargo("DEMO0002")
    assert isinstance(facts, CargoFacts) and facts.containers == ["DEMU2345676", "TESU0000013"]
    other = lookup_cargo("MOCK12345678")
    assert isinstance(other, CargoFacts) and other.containers == []  # 컨테이너를 모르는 화물
    for path in FIXTURES.glob("*.json"):
        for number in json.loads(path.read_text(encoding="utf-8")).get("containers", []):
            assert is_container(number), (path.name, number)  # 가공값도 확인 숫자가 맞아야 한다
