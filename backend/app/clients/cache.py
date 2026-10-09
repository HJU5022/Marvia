"""외부 API 응답 캐시 (작업 B8).

ShipFinder 스타터 키는 호출 빈도 제한이 있다(status 23, 29). 제한에 걸렸을 때
아무 값도 못 주면 판정 자체가 막히므로, 마지막으로 성공한 응답을 TTL 안에서 돌려준다.
값이 오래됐다는 사실은 응답에 담긴 fetched_at으로 드러난다.

지금은 프로세스 메모리에 둔다. SDD 3.9의 api_cache 테이블(Postgres)은 DB 계층이
생긴 뒤 이 클래스의 get·set만 바꿔 끼우면 된다. TTL 기본값은 skills/ais-reliability/rules.md api_cache_ttl_hours다
(SDD 5.2의 6시간: 코드 숫자를 rules.md로 옮김).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.services.judge.rules import rule


def default_ttl() -> timedelta:
    """캐시 TTL 기본값. rules.md api_cache_ttl_hours를 읽는다 (C6). 만들 때마다 읽어서 테스트가 값을 바꿔 끼울 수 있다."""
    return timedelta(hours=rule("api_cache_ttl_hours"))


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    cached_at: datetime

    def is_fresh(self, ttl: timedelta, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) - self.cached_at <= ttl


class ResponseCache:
    """키 하나에 마지막 성공 응답 하나. 예: shipfinder:pos:440999001"""

    def __init__(self, ttl: timedelta | None = None):
        self._ttl = ttl if ttl is not None else default_ttl()
        self._store: dict[str, CacheEntry] = {}

    def set(self, key: str, value: Any, cached_at: datetime | None = None) -> None:
        """cached_at을 안 주면 지금 시각. 평가 실행기는 평가셋에 적힌 담긴 시각을 그대로 넣는다 (F02)."""
        self._store[key] = CacheEntry(value=value, cached_at=cached_at or datetime.now(timezone.utc))

    def get(self, key: str) -> Any | None:
        """TTL 안이면 값을, 지났거나 없으면 None을 돌려준다."""
        entry = self.entry(key)
        return entry.value if entry else None

    def entry(self, key: str, ignore_ttl: bool = False) -> CacheEntry | None:
        """값과 함께 언제 담겼는지도 알아야 할 때 쓴다. 근거 카드에 캐시 시각을 적는다 (SDD 8절).

        TTL이 지난 값은 None으로 돌려주되 지우지는 않는다. ignore_ttl이면 지난 값도 돌려준다.
        ShipFinder 시간 초과는 오래된 위치라도 "마지막 수신 위치"로 쓰기로 해서 남겨 둬야 한다.
        같은 키에 새 값이 들어오면 덮이므로 키마다 하나만 남는다.
        """
        entry = self._store.get(key)
        if entry is None:
            return None
        if not ignore_ttl and not entry.is_fresh(self._ttl):
            return None
        return entry

    def clear(self) -> None:
        self._store.clear()
