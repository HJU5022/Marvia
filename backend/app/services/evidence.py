"""근거 조립과 여유 일수 계산 (작업 C-8, SDD 5.8).

지금 있는 것: days_margin() 하나. 판매 예정일까지 며칠 남았나를 코드가 계산한다.
LLM이 다른 값을 내도 이 값으로 덮어쓴다 (CLAUDE.md "days_margin을 LLM이 정하게 두지 않는다").
근거 카드(Evidence) 조립은 아직 없다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))  # 판매 예정일은 한국 날짜로 받으므로 ETA도 한국 날짜로 바꿔 센다 (SDD 5.8)


def days_margin(trusted_eta: datetime | None, sale_due_date: date | None) -> int | None:
    """판매 예정일 - 신뢰 ETA의 한국 날짜. 음수면 판매 예정일을 넘긴다.

    시간은 무시하고 날짜만 센다. 창고 입고·배송에 걸리는 시간은 넣지 않는다 (SDD 5.8).
    둘 중 하나라도 없으면 None. 판정은 이 값이 없음을 알고 한다.
    """
    if trusted_eta is None or sale_due_date is None:
        return None
    if trusted_eta.tzinfo is None:
        trusted_eta = trusted_eta.replace(tzinfo=timezone.utc)
    return (sale_due_date - trusted_eta.astimezone(KST).date()).days
