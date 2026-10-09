"""B8 캐시 테스트. 빈도 초과(23·29)일 때만 마지막 성공 값을 돌려준다."""
import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from datetime import datetime, timezone

from backend.app.clients.cache import CacheEntry, ResponseCache
from backend.app.clients.shipfinder import ShipFinderClient, ShipFinderError

FIXTURES = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "shipfinder"


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


def test_cache_fallback_is_logged(caplog):
    """지난 값이 지금 값처럼 나가므로 어느 호출이 캐시로 대체됐는지 남긴다. MMSI는 로그에 넣지 않는다."""
    client = _client(["position_busan_anchored.json", "rate_limited.json"])
    client.position(440999001)
    with caplog.at_level("WARNING", logger="marvia.failure"):
        client.position(440999001)

    logged = [(r.stage, r.error) for r in caplog.records if r.name == "marvia.failure"]
    assert logged == [("shipfinder:pos", "rate_limited served_from_cache")]


def test_timeout_falls_back_to_last_success(monkeypatch, caplog):
    """시간 초과도 마지막 성공 값으로 대신한다 (평가셋 F02). 대신했다는 사실은 로그와 last_cached_at에 남는다."""
    from backend.app.clients import retry

    monkeypatch.setattr(retry, "BACKOFF_SEC", 0)  # 재시도 대기를 없앤다
    calls = {"n": 0}
    ok_body = json.loads((FIXTURES / "position_busan_anchored.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=ok_body)
        raise httpx.ReadTimeout("테스트: 시간 초과", request=request)  # 두 번째 조회부터 전부 시간 초과

    client = ShipFinderClient(key="test-key", transport=httpx.MockTransport(handler))
    first = client.position(440999001)
    assert client.last_cached_at is None

    with caplog.at_level("WARNING", logger="marvia.failure"):
        second = client.position(440999001)

    assert second.mmsi == first.mmsi
    assert client.last_cached_at is not None
    assert [(r.stage, r.error) for r in caplog.records if r.name == "marvia.failure"] == [
        ("shipfinder:pos", "timeout served_from_cache")]


def test_timeout_without_cache_raises(monkeypatch):
    """캐시가 없으면 시간 초과를 그대로 올린다. 라우터가 위치 없음(도구 고장)으로 처리한다."""
    from backend.app.clients import retry

    monkeypatch.setattr(retry, "BACKOFF_SEC", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("테스트: 시간 초과", request=request)

    client = ShipFinderClient(key="test-key", transport=httpx.MockTransport(handler))
    with pytest.raises(ShipFinderError) as e:
        client.position(440999001)
    assert e.value.code == "timeout"


def test_set_keeps_given_cached_at():
    """평가 실행기가 평가셋에 적힌 담긴 시각을 그대로 넣을 수 있다 (F02)."""
    cache = ResponseCache()
    when = datetime.now(timezone.utc) - timedelta(hours=1)
    cache.set("k", "v", cached_at=when)
    assert cache.entry("k").cached_at == when


def _stale_client(error: str, monkeypatch) -> ShipFinderClient:
    """9시간 전에 담긴 위치가 캐시에 있고, 이번 조회는 error로 실패하는 클라이언트 (평가셋 F02와 같은 간격)."""
    from backend.app.clients import retry
    from backend.app.clients.shipfinder import position_from_data

    monkeypatch.setattr(retry, "BACKOFF_SEC", 0)
    body = json.loads((FIXTURES / "position_busan_anchored.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        if error == "timeout":
            raise httpx.ReadTimeout("테스트: 시간 초과", request=request)
        return httpx.Response(200, json=json.loads((FIXTURES / "rate_limited.json").read_text(encoding="utf-8")))

    client = ShipFinderClient(key="test-key", transport=httpx.MockTransport(handler))
    client.cache = ResponseCache()
    client.cache.set("shipfinder:pos:440999001", position_from_data(body["data"]),
                     cached_at=datetime.now(timezone.utc) - timedelta(hours=9))
    return client


def test_timeout_uses_cache_older_than_ttl(monkeypatch):
    """시간 초과면 TTL(6시간)이 지난 캐시도 마지막 수신 위치로 쓴다 (①, 평가셋 F02)."""
    client = _stale_client("timeout", monkeypatch)
    assert client.position(440999001).mmsi == 440999001
    assert client.last_cached_at is not None


def test_rate_limited_still_respects_ttl(monkeypatch):
    """빈도 초과는 SDD 5.2대로 TTL 안의 캐시만 쓴다. 9시간 된 값이면 실패를 올린다."""
    client = _stale_client("rate_limited", monkeypatch)
    with pytest.raises(ShipFinderError) as e:
        client.position(440999001)
    assert e.value.code == "rate_limited"
