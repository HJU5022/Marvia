from marvia.identify.parse import check_digit, is_container, read_numbers, read_token


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


def test_container_check_digit_follows_iso_6346():
    # [왜] 표준 설명에 실린 예시 번호(CSQU3054383)로 남이 계산한 값과 맞춰 본다. 나머지는 가공 번호다
    assert check_digit("CSQU305438") == 3
    assert check_digit("DEMU123456") == 0  # 합 5532를 11로 나눈 나머지가 10이면 0
    for good in ("CSQU3054383", "DEMU1234560", "DEMU2345676", "TESU0000013", "NOPU1234560"):
        assert is_container(good), good
    assert not is_container("DEMU1234565")  # 확인 숫자가 틀렸다
    assert not is_container("DEMO1234560")  # 넷째 글자가 U·J·Z가 아니다


def test_container_is_its_own_kind_and_a_wrong_check_digit_reads_as_before():
    assert [(n.value, n.kind) for n in read_token("demu-123456-0").numbers] == [("DEMU1234560", "container")]
    # [왜] 확인 숫자가 틀리면 전처럼 B/L로 읽는다. 오타인지는 식별 단계가 묻는다 (계획 6a)
    assert [(n.value, n.kind) for n in read_token("DEMU1234565").numbers] == [("DEMU1234565", "bl")]


def test_two_containers_of_one_owner_glued_together_split():
    r = read_token("DEMU1234560DEMU2345676")
    assert [(n.value, n.kind) for n in r.numbers] == [
        ("DEMU1234560", "container"),
        ("DEMU2345676", "container"),
    ]
