"""B8 캐시 테스트. 빈도 초과(23·29)일 때만 마지막 성공 값을 돌려준다."""
import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from datetime import datetime, timezone

from backend.app.clients.cache import CacheEntry, ResponseCache
from backend.app.clients.shipfinder import ShipFinderClient, ShipFinderError

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "shipfinder"


def _client(fixtures: list[str]) -> ShipFinderClient:
    """호출할 때마다 fixtures를 순서대로 돌려주는 클라이언트."""
    remaining = list(fixtures)

    def handler(request: httpx.Request) -> httpx.Response:
        name = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return httpx.Response(200, json=json.loads((FIXTURES / name).read_text(encoding="utf-8")))

    return ShipFinderClient(key="test-key", transport=httpx.MockTransport(handler))


def test_rate_limited_falls_back_to_last_success():
    client = _client(["position_busan_anchored.json", "rate_limited.json"])

    first = client.position(440999001)
    second = client.position(440999001)  # 이번엔 빈도 초과지만 캐시가 받아준다

    assert second.mmsi == first.mmsi
    assert second.fetched_at == first.fetched_at  # 조회 시각이 그대로라 오래된 값임을 알 수 있다


def test_other_failures_are_not_hidden_by_cache():
    """권한 없음이나 없는 배는 사실이므로 캐시로 가리지 않는다."""
    client = _client(["position_busan_anchored.json", "no_permission.json"])
    client.position(440999001)

    with pytest.raises(ShipFinderError) as e:
        client.position(440999001)
    assert e.value.code == "no_permission"


def test_rate_limited_without_cache_raises():
    with pytest.raises(ShipFinderError) as e:
        _client(["rate_limited.json"]).position(440999001)
    assert e.value.code == "rate_limited"


def test_cache_key_is_per_mmsi():
    client = _client(["position_busan_anchored.json", "rate_limited.json"])
    client.position(440999001)

    with pytest.raises(ShipFinderError):
        client.position(999999999)  # 다른 MMSI는 캐시가 없다


def test_entry_expires_after_ttl():
    cache = ResponseCache(ttl=timedelta(hours=6))
    cache.set("k", "v")
    assert cache.get("k") == "v"

    # 7시간 전에 담긴 값으로 바꿔치면 TTL을 넘겨 버려진다
    cache._store["k"] = CacheEntry(value="v", cached_at=datetime.now(timezone.utc) - timedelta(hours=7))
    assert cache.get("k") is None


def test_cache_hit_is_visible():
    """캐시로 답했으면 언제 담긴 값인지 알 수 있어야 한다 (SDD 8절 근거에 캐시 표시)."""
    client = _client(["position_busan_anchored.json", "rate_limited.json"])

    client.position(440999001)
    assert client.last_cached_at is None  # 실시간으로 받았다

    client.position(440999001)
    assert client.last_cached_at is not None  # 이번엔 캐시가 받아냈다
