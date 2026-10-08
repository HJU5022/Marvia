"""같은 호출부호로 여러 배가 나올 때 어느 배를 고를지 정하는 규칙 한 곳.

쓰는 곳: services/watch/vessel_watch.py resolve_mmsi(지켜보기 켤 때), services/watch/vessel_detail.py detail()(자세히 보기).
왜 한 곳인가: 전에는 자세히 보기는 후보 첫 번째 배를 보여 주는데 지켜보기는 "정확히 한 척"일 때만 받아서,
자세히 보기에서 보이는 배를 지켜보려고 하면 many_match로 실패했다. 두 화면이 같은 배를 가리키려면 규칙이 같아야 한다.

규칙 (판정이 아니라 어느 MMSI인지 고르는 식별 규칙이고, 임계값 숫자는 없다):
  1. 이름이 정확히 같은 배 먼저. 이름은 대문자로 맞추고 공백·하이픈을 지운 값끼리 비교한다
  2. 그다음은 마지막 신호(last_time)가 가장 최근인 배. 호출부호는 팔리거나 국적이 바뀌면 다른 배에 다시 배정되므로
     (get_vessel_candidates 실측), 지금 쓰는 배는 가장 최근에 신호를 보낸 쪽이다
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable, TypeVar

T = TypeVar("T")
_MIN = datetime.min.replace(tzinfo=timezone.utc)


def normalize_call_sign(value: str | None) -> str:
    """호출부호 비교용: 대문자, 공백·하이픈 제거. 양쪽(요청값, 검색 결과)에 같이 적용한다."""
    return re.sub(r"[\s\-]+", "", (value or "").upper())


def normalize_name(value: str | None) -> str:
    """선명 비교용. 호출부호와 같은 방식으로 맞춘다."""
    return normalize_call_sign(value)


def as_datetime(value) -> datetime:
    """datetime 또는 ISO 문자열을 UTC datetime으로. 없거나 못 읽으면 가장 오래된 값(순위 맨 뒤)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            then = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return _MIN
        return then if then.tzinfo else then.replace(tzinfo=timezone.utc)
    return _MIN


def rank(items: list[T], ship_name: str | None, name_of: Callable[[T], str | None],
         time_of: Callable[[T], object]) -> list[T]:
    """위 규칙대로 좋은 순서로 정렬한 새 목록. 이름을 모르면(ship_name 없음) 최근 신호 순서만 쓴다."""
    want = normalize_name(ship_name)

    def key(item: T):
        same = bool(want) and normalize_name(name_of(item)) == want
        return (same, as_datetime(time_of(item)))

    return sorted(items, key=key, reverse=True)
