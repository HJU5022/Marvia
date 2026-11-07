from marvia.identify.parse import check_digit, container_typo, is_container, read_numbers, read_token


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


def test_a_spaced_container_is_one_number_only_when_its_check_digit_holds():
    assert values("컨테이너 DEMU 123456 0, TESU 0000013") == [["DEMU1234560"], ["TESU0000013"]]
    assert values("DEMU 123456-0 도착") == [["DEMU1234560"]]  # 조각 123456-0이 따로 잡히지 않는다
    # [왜] 확인 숫자가 틀려도 한 덩어리다. 붙여 쓴 꼴(DEMU1234565)처럼 B/L로 읽혀 식별 단계가 오타를 묻는다
    assert [(n.value, n.kind) for r in read_numbers("ABCU 1234567 같은 글") for n in r[1].numbers] == [
        ("ABCU1234567", "bl")
    ]


def test_a_number_hyphen_joined_to_a_spaced_container_is_still_read():
    # [왜] 컨테이너 조각과 겹친다고 옆에 하이픈으로 붙은 번호까지 버리면 가리지 않은 채 LLM에 간다
    assert values("HASL0001-DEMU 123456 0 어디?") == [["HASL0001"], ["DEMU1234560"]]
    assert values("DEMU 123456 0-HASL0001 어디?") == [["DEMU1234560"], ["HASL0001"]]


def test_container_typo_is_the_container_shape_with_a_wrong_check_digit():
    assert container_typo("DEMU1234565")
    assert not container_typo("DEMU1234560")  # 맞는 컨테이너 번호
    assert not container_typo("MOCK1234567")  # 넷째 글자가 U·J·Z가 아니면 컨테이너 모양이 아니다


def test_every_container_shaped_spaced_form_is_one_chunk():
    forms = {
        "DEMU 123456 (0)": ("DEMU1234560", "container"),  # 컨테이너 문에 적는 꼴
        "demu 123456 [0]": ("DEMU1234560", "container"),
        "DEMU 123 456 0": ("DEMU1234560", "container"),
        "DEMU  123456  0": ("DEMU1234560", "container"),
        "DEMU\t1234560": ("DEMU1234560", "container"),
        "DEMU\u00a0123456\u00a00": ("DEMU1234560", "container"),
        "DEMU 123456 1": ("DEMU1234561", "bl"),
        "DEMU 1234561": ("DEMU1234561", "bl"),
    }
    for form, want in forms.items():
        found = [(n.value, n.kind) for _, r in read_numbers(f"앞 {form} 뒤") for n in r.numbers]
        assert found == [want], form


def test_a_wrong_spaced_digit_count_is_not_a_container():
    assert values("DEMU 12345 0 도착") == []  # 일련번호가 모자라면 이 모양이 아니다
