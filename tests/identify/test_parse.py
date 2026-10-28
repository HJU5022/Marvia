from marvia.identify.parse import read_numbers, read_token


def values(text: str) -> list[list[str]]:
    return [[n.value for n in r.numbers] for _, r in read_numbers(text)]


def test_split_repeated_prefix():
    r = read_token("HASL0001HASL0002")
    assert [n.value for n in r.numbers] == ["HASL0001", "HASL0002"]
    assert not r.ambiguous


def test_lowercase_and_space():
    assert values("hasl0001 hasl0002") == [["HASL0001"], ["HASL0002"]]


def test_hyphen_removed():
    assert values("B/L: HASL-0001-23") == [["HASL000123"]]


def test_number_inside_korean_sentence():
    assert values("B/L 번호는 KMTC1234567890 입니다") == [["KMTC1234567890"]]


def test_cargo_management_number():
    r = read_token("26ABCD1234I00010002")
    assert [(n.value, n.kind) for n in r.numbers] == [("26ABCD1234I00010002", "cargo_no")]


def test_long_token_without_repeat_is_ambiguous():
    r = read_token("ABCD12345678EFGH87654321")
    assert r.ambiguous and r.numbers == []
    assert r.alternatives == [["ABCD12345678", "EFGH87654321"], ["ABCD12345678EFGH87654321"]]


def test_date_is_not_a_number():
    assert values("입항 20261028 예정") == []
