from datetime import date

import pytest

from marvia.tools.deadlines import due_date, import_deadlines, kst_date
from marvia.tools.rules import load_rules

HOLIDAYS = set(load_rules("deadlines")["holidays"])
TODAY = date(2026, 11, 2)


def test_first_day_is_not_counted():
    # 민법 제157조: 반입일(10-27)은 세지 않는다. 30일째는 11-26(목)
    assert due_date(date(2026, 10, 27), 30, set()) == date(2026, 11, 26)


def test_weekend_moves_to_monday():
    # 10-29 + 30일 = 11-28(토) → 11-30(월)
    assert due_date(date(2026, 10, 29), 30, set()) == date(2026, 11, 30)


def test_holiday_then_weekend_moves_on():
    # 11-25 + 30일 = 12-25(금, 기독탄신일) → 토·일도 넘겨 12-28(월)
    assert due_date(date(2026, 11, 25), 30, HOLIDAYS) == date(2026, 12, 28)


def test_past_substitute_holiday_counts():
    # 09-05 + 30일 = 10-05(월, 개천절 대체공휴일) → 10-06(화). 기한을 넘긴 화물도 지난 공휴일로 센다
    assert due_date(date(2026, 9, 5), 30, HOLIDAYS) == date(2026, 10, 6)


def test_declaration_deadline_after_entry():
    [deadline] = import_deadlines("반입신고", date(2026, 10, 27), TODAY)
    assert deadline.name == "수입신고 기한" and deadline.basis == "관세법 제241조제3항"
    assert (deadline.due, deadline.days_left) == (date(2026, 11, 26), 24)
    assert deadline.surcharge is None  # 아직 기한 안


def test_duty_payment_deadline_after_acceptance():
    [deadline] = import_deadlines("수입신고수리", date(2026, 11, 2), TODAY)
    assert (deadline.name, deadline.due) == ("관세 납부기한", date(2026, 11, 17))


def test_stage_without_deadline():
    assert import_deadlines("입항", date(2026, 10, 26), TODAY) == []


# 09-01 반입 → 기한 10-01(목). 오늘에 따라 넘긴 날 수와 가산세율이 바뀐다 (시행령 제247조제1항)
@pytest.mark.parametrize(
    ("today", "late_days", "rate"),
    [
        (date(2026, 10, 21), 20, 0.005),
        (date(2026, 10, 22), 21, 0.010),
        (date(2026, 12, 20), 80, 0.015),
        # [왜] 80일째 12-20이 일요일이라 3호 구간이 12-21(월)까지 간다 (민법 제161조)
        (date(2026, 12, 21), 81, 0.015),
        (date(2026, 12, 22), 82, 0.020),
    ],
)
def test_late_surcharge_bands(today, late_days, rate):
    [deadline] = import_deadlines("반입신고", date(2026, 9, 1), today)
    assert deadline.due == date(2026, 10, 1) and deadline.days_left == -late_days
    assert deadline.surcharge is not None
    assert (deadline.surcharge.late_days, deadline.surcharge.rate) == (late_days, rate)
    assert deadline.surcharge.cap_krw == 5000000
    assert "별표 1" in deadline.surcharge.applies  # 대상 물품 범위를 늘 함께 낸다


@pytest.mark.parametrize(
    "moment",
    ["2026-10-27T09:00:00+09:00", "2026-10-26T15:30:00Z", "2026-10-27T00:30:00"],
)
def test_kst_date(moment):
    # [왜] 기한은 한국 날짜로 센다. UTC 15:30은 한국 다음 날 00:30이고, 시간대가 없으면 한국 시각으로 본다
    assert kst_date(moment) == date(2026, 10, 27)
