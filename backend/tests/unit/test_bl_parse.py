"""bl_parse: 흐트러진 B/L 후보 만들기 + 세관 확인. exists는 가짜라 네트워크가 필요 없다."""
from backend.app.services.judge import bl_parse
from backend.app.services.judge.bl_parse import (NOTE_GLUED, NOTE_SPACE, NOTE_SYMBOL, repair_message, resolve,
                                           separator_candidates, split_candidates, split_not_found)


def _only(*real):
    """주어진 번호만 세관에 있다고 답하는 가짜 exists. 물어본 번호를 calls에 쌓는다."""
    calls = []

    def exists(bl):
        calls.append(bl)
        return bl in real

    exists.calls = calls
    return exists


def test_separator_candidates_hyphen_slash_space():
    assert ("test-bl-01", "TESTBL01") in separator_candidates("test-bl-01 화물")
    assert ("TEST-BL/01", "TESTBL01") in separator_candidates("TEST-BL/01")
    assert ("test bl01", "TESTBL01") in separator_candidates("test bl01 어디야")


def test_strong_join_before_space_join():
    pairs = separator_candidates("test-bl01 / ab 1234567")
    spans = [s for s, _ in pairs]
    assert spans.index("test-bl01") < min(i for i, s in enumerate(spans) if " " in s)


def test_no_join_across_korean_or_dates_or_short():
    assert separator_candidates("화물 test 조회 bl01") == []  # 한글이 끼면 안 붙인다
    assert separator_candidates("2026-10-05 에 도착") == []  # 날짜
    assert separator_candidates("010-1234-5678") == []  # 전화번호
    assert separator_candidates("ab-1") == []  # 너무 짧다
    assert separator_candidates("TESTBL01 TESTBL02 비교") == []  # 이미 B/L 모양인 조각 둘은 건드리지 않는다


def test_split_candidates_prefer_same_prefix():
    first = split_candidates("TESTBL01TESTBL02")[0]
    assert first == ("TESTBL01", "TESTBL02")
    assert split_candidates("ABCDEFGH1234") == []  # 16자 미만은 나누지 않는다
    assert len(split_candidates("A1" * 20)) <= bl_parse.MAX_CHECKS


def test_resolve_keeps_only_verified_and_stops_at_cap():
    exists = _only("TESTBL01")
    assert resolve([("TESTBL09",), ("TESTBL01",)], exists) == [("TESTBL01",)]
    many = [(f"TESTBL{i:02d}",) for i in range(10)]
    exists = _only()
    assert resolve(many, exists, max_checks=3) == [] and len(exists.calls) == 3


def test_repair_message_replaces_verified_only():
    text, notes = repair_message("test-bl-01 화물 괜찮아?", _only("TESTBL01"))
    assert text == "TESTBL01 화물 괜찮아?" and notes == [NOTE_SYMBOL]
    text, notes = repair_message("test bl01 화물", _only("TESTBL01"))
    assert text == "TESTBL01 화물" and notes == [NOTE_SPACE]
    text, notes = repair_message("TEST-BL/01 화물", _only("TESTBL01"))
    assert text == "TESTBL01 화물"


def test_repair_message_unverified_is_unchanged():
    msg = "test-bl-01 화물 괜찮아?"
    assert repair_message(msg, _only()) == (msg, [])


def test_notes_do_not_contain_bl_numbers():
    for note in (NOTE_SYMBOL, NOTE_SPACE, NOTE_GLUED):
        assert "TESTBL" not in note.upper()


def test_split_not_found():
    assert split_not_found("TESTBL01TESTBL02", _only("TESTBL01", "TESTBL02")) == ["TESTBL01", "TESTBL02"]
    assert split_not_found("TESTBL01TESTBL02", _only("TESTBL01")) == []  # 한 조각만 있으면 받아들이지 않는다
    assert split_not_found("TESTBL01", _only("TESTBL01")) == []  # 짧은 토큰은 나누지 않는다
