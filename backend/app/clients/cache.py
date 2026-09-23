"""외부 API 응답 캐시 (작업 B8).

ShipFinder 스타터 키는 호출 빈도 제한이 있다(status 23, 29). 제한에 걸렸을 때
아무 값도 못 주면 판정 자체가 막히므로, 마지막으로 성공한 응답을 TTL 안에서 돌려준다.
값이 오래됐다는 사실은 응답에 담긴 fetched_at으로 드러난다.

지금은 프로세스 메모리에 둔다. SDD 3.9의 api_cache 테이블(Postgres)은 DB 계층이
생긴 뒤 이 클래스의 get·set만 바꿔 끼우면 된다. TTL 기본값은 SDD 5.2의 6시간이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_TTL = timedelta(hours=6)


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    cached_at: datetime

    def is_fresh(self, ttl: timedelta, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) - self.cached_at <= ttl


class ResponseCache:
    """키 하나에 마지막 성공 응답 하나. 예: shipfinder:pos:440063450"""

    def __init__(self, ttl: timedelta = DEFAULT_TTL):
        self._ttl = ttl
        self._store: dict[str, CacheEntry] = {}

    def set(self, key: str, value: Any) -> None:
        self._store[key] = CacheEntry(value=value, cached_at=datetime.now(timezone.utc))

    def get(self, key: str) -> Any | None:
        """TTL 안이면 값을, 지났거나 없으면 None을 돌려준다."""
        entry = self.entry(key)
        return entry.value if entry else None

    def entry(self, key: str) -> CacheEntry | None:
        """값과 함께 언제 담겼는지도 알아야 할 때 쓴다. 근거 카드에 캐시 시각을 적는다 (SDD 8절)."""
        entry = self._store.get(key)
        if entry is None:
            return None
        if not entry.is_fresh(self._ttl):
            del self._store[key]
            return None
        return entry

    def clear(self) -> None:
        self._store.clear()
