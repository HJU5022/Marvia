"""수입 기한 계산: 화물의 지금 단계와 그 날짜로 법정 기한을 셈한다 (설계 7.1 import_deadlines).

하지 않는 일: 인용 만들기(설계 5.6: basis는 조문 이름표일 뿐이고 인용은 근거 묶음의 unit_id만 쓴다),
장치기간(체화관리 고시가 코퍼스 밖이다), 식품 사전 수입신고 기간(도착 예정일이 필요하다),
납부기한의 예외(즉시반출·월별납부), 관세청장이 정하는 날(관세법 제8조제3항제4호),
전산 장애로 미뤄진 기한(제8조제4항).
기한 표·가산세율·공휴일은 rules/deadlines.yaml에서 읽는다.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel

from marvia.tools.rules import load_rules


class LateSurcharge(BaseModel):
    """신고 기한을 넘긴 화물을 오늘 신고하면 붙는 가산세율 (관세법 시행령 제247조)."""

    late_days: int  # 기한 다음 날부터 오늘까지 지난 날 수
    rate: float  # 과세가격에 곱하는 율
    cap_krw: int  # 가산세액 상한(원)
    applies: str  # 가산세가 붙는 물품의 범위. 코드는 대상인지 모르므로 늘 함께 보여 준다


class Deadline(BaseModel):
    """기한 하나."""

    name: str  # 수입신고 기한, 관세 납부기한
    start_stage: str  # 기한이 시작된 통관 단계
    start: date  # 그 단계가 된 날
    due: date  # 기한 (토·일·공휴일이면 넘긴 뒤의 날)
    days_left: int  # 오늘부터 기한까지 남은 날. 넘겼으면 음수
    basis: str  # 조문 이름표 (예: 관세법 제241조제3항). 인용이 아니다
    surcharge: LateSurcharge | None = None  # 기한을 넘겼고 가산세 표가 있는 기한만


def due_date(start: date, days: int, holidays: set[date]) -> date:
    """start부터 days일째 되는 날. 그날이 토·일·공휴일이면 쉬지 않는 날까지 넘긴다."""
    # [왜] 민법 제157조: 기간의 첫날(반입일)은 세지 않는다. 제159조: 마지막 날이 끝나야 기간이 끝난다.
    #      그래서 start + days가 기한이다
    # [주의] 오전 0시에 시작한 기간은 첫날을 센다(같은 조 단서). 단계 시각이 0시인 경우는 다루지 않는다
    due = start + timedelta(days=days)
    # [왜] 관세법 제8조제3항: 기한이 토·일, 공휴일·대체공휴일, 노동절이면 그 다음 날이 기한이다.
    #      다음 날도 쉬는 날이면 또 넘긴다 [추정: 되풀이 적용은 조사 보고서의 해석]
    while due.weekday() >= 5 or due in holidays:  # weekday(): 월 0 ~ 금 4, 토 5, 일 6
        due += timedelta(days=1)
    return due


def import_deadlines(stage: str, stage_on: date, today: date) -> list[Deadline]:
    """지금 단계에서 시작하는 법정 기한 목록.

    입력: stage=UNI-PASS 통관 단계 이름, stage_on=그 단계가 된 날, today=오늘.
    출력: 그 단계에서 시작하는 기한마다 Deadline. 해당하는 기한이 없으면 빈 목록.
    주의: 가산세율은 "오늘 신고하면"의 율이다. 가산세가 붙는 물품인지는 판단하지 않고 applies 글로 알린다.
    """
    rules = load_rules("deadlines")
    holidays = set(rules["holidays"])  # yaml이 2026-12-25를 date로 읽어 준다
    deadlines = []
    for row in rules["deadlines"]:
        if stage not in row["start_stages"]:
            continue
        due = due_date(stage_on, row["days"], holidays)
        days_left = (due - today).days
        surcharge = None
        late = row.get("late_surcharge")
        if late and days_left < 0:
            late_days = -days_left
            # [왜] 구간을 짧은 것부터 보고 처음 들어맞는 율을 쓴다. 어느 구간에도 없으면 그 밖의 율
            # [추정] "기한이 지난 날부터 20일내"의 첫날 셈은 확인하지 못했다. 기한 다음 날을 1일로 센다
            bands = late["bands"]
            rate = next((b["rate"] for b in bands if late_days <= b["within_days"]), late["else_rate"])
            surcharge = LateSurcharge(
                late_days=late_days, rate=rate, cap_krw=late["cap_krw"], applies=late["applies"]
            )
        deadlines.append(
            Deadline(
                name=row["name"],
                start_stage=stage,
                start=stage_on,
                due=due,
                days_left=days_left,
                basis=row["basis"],
                surcharge=surcharge,
            )
        )
    return deadlines
