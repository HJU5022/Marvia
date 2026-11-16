"""사용자 글에서 절대 날짜만 읽는다 (계획 8c, 결정 C5, C12).

[왜] 날짜를 읽는 일은 모델이 아니라 코드가 한다. 읽는 꼴을 좁게 두고 읽지 못하는 것(내일, 다음 주 화요일,
     시각)은 읽지 않는다. 지어내지 않는다.
읽는 꼴: YYYY-MM-DD, YYYY.MM.DD, YYYY/MM/DD, YYYY년 M월 D일, M월 D일, M/D.
"""

from __future__ import annotations

import re
from datetime import date

from marvia.tools.rules import load_rules

_YMD = re.compile(r"(?<!\d)(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})(?!\d)")
_KOREAN_YMD = re.compile(r"(?<!\d)(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_KOREAN_MD = re.compile(r"(?<![\d/])(\d{1,2})\s*월\s*(\d{1,2})\s*일")
# [왜] 숫자 덩어리 안의 M/D(2026/11/20의 뒷부분, 1,000/2 같은 금액)와 3/4분기는 날짜가 아니다
# shortcut: 1/2 같은 분수는 M/D로 읽힌다, 사용자가 분수를 쓰는 일이 보이면 막는다
_SLASH_MD = re.compile(r"(?<![\d/,.\-])(\d{1,2})/(\d{1,2})(?![\d/]|\s*분기)")


def _make(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _this_or_next_year(month: int, day: int, today: date) -> date | None:
    """연도 없는 날짜: 올해로 읽고, 오늘보다 past_grace_days일을 넘게 지났으면 내년으로 읽는다."""
    grace = load_rules("vessel")["dates"]["past_grace_days"]
    found = _make(today.year, month, day)
    if found is not None and (today - found).days > grace:
        return _make(today.year + 1, month, day)
    return found


def absolute_dates(text: str, today: date) -> set[date]:
    """글에 쓰인 절대 날짜들. 없는 날짜(11월 31일)와 상대 표현은 읽지 않는다."""
    found: set[date | None] = set()
    work = text
    for pattern in (_YMD, _KOREAN_YMD, _KOREAN_MD, _SLASH_MD):
        for match in pattern.finditer(work):
            n = [int(g) for g in match.groups()]
            found.add(_make(n[0], n[1], n[2]) if len(n) == 3 else _this_or_next_year(n[0], n[1], today))
        # [왜] 읽은 자리는 비운다. 뒤 꼴이 같은 글을 다시 읽지 않게 한다
        work = pattern.sub(lambda m: " " * len(m.group(0)), work)
    return {d for d in found if d is not None}
