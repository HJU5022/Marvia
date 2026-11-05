from marvia.identify.mask import mask_text, token_for, unmask


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
    from marvia.identify.mask import LABELS, token_for

    assert set(LABELS) == {"BL", "CARGO", "NUM"}
    for kind in ("bl", "cargo_no", "unread"):
        assert TOKEN.fullmatch(token_for({}, "X", kind))
