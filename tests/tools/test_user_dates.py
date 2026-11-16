"""사용자 글에서 절대 날짜만 읽는 함수 시험 (계획 8c T2, CC4의 바닥)."""

from datetime import date

import pytest

from marvia.tools.user_dates import absolute_dates

TODAY = date(2026, 9, 22)


@pytest.mark.parametrize(
    "text",
    [
        "판매는 2026-11-20에 해요",
        "판매는 2026.11.20에 해요",
        "판매는 2026/11/20에 해요",
        "판매는 2026년 11월 20일에 해요",
        "판매는 11월 20일에 해요",
        "판매는 11/20에 해요",
    ],
)
def test_each_written_form_is_read(text):
    assert absolute_dates(text, TODAY) == {date(2026, 11, 20)}


def test_a_year_less_date_is_this_year_or_next_when_it_is_more_than_a_week_past():
    assert absolute_dates("9월 25일", TODAY) == {date(2026, 9, 25)}
    assert absolute_dates("9월 15일", TODAY) == {date(2026, 9, 15)}  # 7일 지남: 올해
    assert absolute_dates("9월 14일", TODAY) == {date(2027, 9, 14)}  # 8일 지남: 내년
    assert absolute_dates("1월 3일", TODAY) == {date(2027, 1, 3)}


def test_an_impossible_date_is_dropped():
    assert absolute_dates("11월 31일, 2026-02-30, 13/40", TODAY) == set()
    assert absolute_dates("2월 29일", TODAY) == set()  # 2027년에도 없다


def test_relative_words_are_not_read():
    for text in ("내일", "모레", "다음 주 화요일", "이번 달 말", "오후 3시 30분"):
        assert absolute_dates(text, TODAY) == set(), text


def test_a_date_inside_a_number_is_not_read():
    assert absolute_dates("2026111999 번호", TODAY) == set()
    assert absolute_dates("3/4분기 실적", TODAY) == set()
    assert absolute_dates("금액 1,000/2", TODAY) == set()
    assert absolute_dates("[BL1] 화물 [NUM2]", TODAY) == set()


def test_two_dates_in_one_text_are_both_read():
    text = "판매는 11월 20일, 포워더는 2026-11-18이라고 했어요"
    assert absolute_dates(text, TODAY) == {date(2026, 11, 20), date(2026, 11, 18)}
