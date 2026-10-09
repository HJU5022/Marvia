"""B4 get_live_position 단위 테스트. fixture 클라이언트를 넣어 키 없이 돈다."""
import json
from pathlib import Path

import httpx
import pytest

from backend.app.clients.shipfinder import ShipFinderClient
from mcp_server.tools import live_position
from mcp_server.tools.live_position import get_live_position

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "shipfinder"


@pytest.fixture
def use_fixture(monkeypatch):
    """make_client를 fixture 응답만 돌려주는 클라이언트로 바꾼다."""

    def _use(fixture: str):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=json.loads((FIXTURES / fixture).read_text(encoding="utf-8")))

        client = ShipFinderClient(key="test-key", transport=httpx.MockTransport(handler))
        monkeypatch.setattr(live_position, "make_client", lambda: client)

    return _use


def test_returns_raw_values_and_both_times(use_fixture):
    use_fixture("position_busan_anchored.json")
    r = get_live_position(440999001)

    assert (r["mmsi"], r["lat"], r["lng"], r["sog"], r["navistat"]) == (440999001, 35.1, 129.05, 0.0, 8)
    assert (r["dest"], r["destcode"]) == ("BUSAN, KR", "KRPUS")
    assert r["source"] == "shipfinder"
    # last_time은 선박이 보고한 시각, fetched_at은 우리가 조회한 시각. 둘 다 있어야 C-4가 stale을 판정한다
    assert r["last_time"] and r["fetched_at"] and r["last_time"] != r["fetched_at"]
    assert r["ais_eta"] is None  # 이 응답에는 eta 키가 없다


def test_does_not_judge_freshness(use_fixture):
    """freshness·stale 판정은 services/judge/signals.py 몫이라 도구 출력에 없다 (작업 리스트 경계 정리)."""
    use_fixture("position_busan_anchored.json")
    r = get_live_position(440999001)
    assert "freshness" not in r and "stale" not in r


@pytest.mark.parametrize(
    "fixture, code, retryable",
    [("not_found.json", "not_found", False), ("no_permission.json", "no_permission", False), ("rate_limited.json", "rate_limited", True)],
)
def test_failure_returns_tool_error_not_exception(fixture, code, retryable, use_fixture):
    use_fixture(fixture)
    r = get_live_position(440999001)
    assert r["error"]["code"] == code and r["error"]["retryable"] is retryable
    assert r["error"]["message"]


# ── 도구는 예외를 던지지 않는다 (C4) ──

def test_missing_key_returns_bad_key_error(monkeypatch):
    """클라이언트 만들기에서 난 실패(키 없음)도 {error}로, 코드는 bad_key 그대로."""
    monkeypatch.delenv("SHIPFINDER_KEY", raising=False)
    monkeypatch.delenv("REPLAY_MODE", raising=False)
    monkeypatch.setattr(live_position, "make_client", ShipFinderClient)
    assert get_live_position(440999001) == {
        "error": {"code": "bad_key", "message": "SHIPFINDER_KEY가 비어 있습니다", "retryable": False}}


def test_missing_lat_returns_error(monkeypatch):
    body = {"status": 0, "data": {"mmsi": 440999001, "lng": 129.0}}
    client = ShipFinderClient(key="test-key", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    monkeypatch.setattr(live_position, "make_client", lambda: client)
    assert get_live_position(440999001)["error"]["code"] == "error"


def test_contract_violation_returns_bad_response(monkeypatch):
    """응답 값이 계약(LivePositionResult)에 안 맞으면 ValidationError 대신 bad_response."""
    body = {"status": 0, "data": {"mmsi": 440999001, "lat": "not-a-number", "lng": 129.0}}
    client = ShipFinderClient(key="test-key", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    monkeypatch.setattr(live_position, "make_client", lambda: client)
    error = get_live_position(440999001)["error"]
    assert (error["code"], error["retryable"]) == ("bad_response", False)


def test_quota_exhausted_returns_error(use_fixture):
    use_fixture("quota_exhausted.json")
    assert get_live_position(440999001)["error"]["code"] == "quota_exhausted"
