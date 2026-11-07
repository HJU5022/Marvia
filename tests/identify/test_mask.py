from marvia.identify.mask import LABELS, READ_LABELS, mask_text, token_for, unmask


def test_split_numbers_get_two_tokens():
    masked, mask_map = mask_text("hasl0001hasl0002 왜 멈췄어?")
    assert masked == "[BL1][BL2] 왜 멈췄어?"
    assert mask_map == {"[BL1]": "HASL0001", "[BL2]": "HASL0002"}


def test_same_number_same_token():
    masked, _ = mask_text("HASL0001 그리고 hasl-0001")
    assert masked == "[BL1] 그리고 [BL1]"


def test_cargo_number_token():
    masked, mask_map = mask_text("26ABCD1234I00010002 상태")
    assert masked == "[CARGO1] 상태"
    assert mask_map["[CARGO1]"] == "26ABCD1234I00010002"


def test_ambiguous_chunk_is_hidden_too():
    masked, mask_map = mask_text("ABCD12345678EFGH87654321")
    assert masked == "[NUM1]"
    assert mask_map["[NUM1]"] == "ABCD12345678EFGH87654321"


def test_token_for_reuses_and_adds():
    mask_map = {"[BL1]": "HASL0001"}
    assert token_for(mask_map, "HASL0001", "bl") == "[BL1]"
    assert token_for(mask_map, "HASL0002", "bl") == "[BL2]"
    assert mask_map["[BL2]"] == "HASL0002"


def test_unmask_round_trip():
    masked, mask_map = mask_text("HASL0001HASL0002")
    assert unmask(masked, mask_map) == "HASL0001HASL0002"


def test_cargo_token_pattern_matches_every_label():
    # [왜] 품목 이름 검사의 토큰 정규식은 mask의 이름표에서 만든다. 이름표가 늘면 정규식도 따라가야 한다
    from marvia.graph.tools import TOKEN
    from marvia.identify.mask import _LABEL, token_for

    for kind in _LABEL:
        assert TOKEN.fullmatch(token_for({}, "X", kind))


def test_a_container_gets_its_own_token_and_is_not_a_lookup_label():
    masked, mask_map = mask_text("컨테이너 DEMU1234560 어디쯤이에요")
    assert (masked, mask_map) == ("컨테이너 [CNTR1] 어디쯤이에요", {"[CNTR1]": "DEMU1234560"})
    # [왜] READ_LABELS는 UNI-PASS로 바로 조회할 수 있는 번호의 이름표다. 감시 목록이 이것으로 거른다
    assert "CNTR" in LABELS and "CNTR" not in READ_LABELS


def test_a_spaced_container_is_masked_whole():
    masked, mask_map = mask_text("DEMU 123456 0 어디쯤?")
    assert (masked, mask_map) == ("[CNTR1] 어디쯤?", {"[CNTR1]": "DEMU1234560"})


def test_every_container_shaped_spaced_form_is_masked_whole():
    for form, value in (
        ("DEMU 123456 (0)", "DEMU1234560"),
        ("DEMU 123 456 0", "DEMU1234560"),
        ("DEMU\t1234561", "DEMU1234561"),
    ):
        masked, mask_map = mask_text(f"{form} 어디쯤?")
        assert masked.endswith(" 어디쯤?") and "DEMU" not in masked and "123" not in masked, form
        assert list(mask_map.values()) == [value], form


def test_hyphen_only_numbers_are_masked_whole_and_an_outer_bracket_stays():
    for text in ("HDMU-1234567-001", "MAEU-1234567-89"):
        masked, mask_map = mask_text(f"{text} 도착")
        assert masked == "[BL1] 도착" and list(mask_map.values()) == [text.replace("-", "")], text
    assert mask_text("컨테이너(DEMU1234560)로")[0] == "컨테이너([CNTR1])로"
