"""A9 재시도 테스트. 타임아웃·5xx만 다시 부르고 나머지는 바로 올린다."""
import httpx
import pytest

from backend.app.clients.retry import MAX_ATTEMPTS, is_retryable, with_retry
from backend.app.clients.shipfinder import ShipFinderClient, ShipFinderError


def _counting(responses):
    """호출될 때마다 responses를 순서대로 돌려주거나 던지는 함수와 호출 수를 준다."""
    calls = {"n": 0}

    def call():
        calls["n"] += 1
        item = responses[min(calls["n"] - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    return call, calls


def test_retries_timeout_then_succeeds():
    request = httpx.Request("GET", "https://example.test")
    call, calls = _counting([httpx.ReadTimeout("slow", request=request), "ok"])

    assert with_retry(call, name="t", backoff=0) == "ok"
    assert calls["n"] == 2


def test_gives_up_after_max_attempts():
    request = httpx.Request("GET", "https://example.test")
    call, calls = _counting([httpx.ReadTimeout("slow", request=request)])

    with pytest.raises(httpx.ReadTimeout):
        with_retry(call, name="t", backoff=0)
    assert calls["n"] == MAX_ATTEMPTS == 3  # 최초 1회 + 재시도 2회


def test_does_not_retry_client_error():
    request = httpx.Request("GET", "https://example.test")
    error = httpx.HTTPStatusError("bad", request=request, response=httpx.Response(400, request=request))
    call, calls = _counting([error])

    with pytest.raises(httpx.HTTPStatusError):
        with_retry(call, name="t", backoff=0)
    assert calls["n"] == 1


def test_is_retryable_by_status():
    request = httpx.Request("GET", "https://example.test")

    def status_error(code: int) -> httpx.HTTPStatusError:
        return httpx.HTTPStatusError("x", request=request, response=httpx.Response(code, request=request))

    assert is_retryable(status_error(503)) is True
    assert is_retryable(status_error(404)) is False
    assert is_retryable(httpx.ConnectError("no route")) is True
    assert is_retryable(ValueError("other")) is False


def test_client_recovers_from_one_5xx():
    """클라이언트가 실제로 재시도를 쓰는지 확인한다."""
    seen = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["n"] += 1
        if seen["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"status": 0, "msg": "", "total": 0, "data": []})

    client = ShipFinderClient(key="test-key", transport=httpx.MockTransport(handler))
    assert client.search("TEST STAR").hits == []
    assert seen["n"] == 2


def test_client_gives_up_and_raises_error():
    client = ShipFinderClient(key="test-key", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(ShipFinderError) as e:
        client.search("TEST STAR")
    assert e.value.code == "error"
