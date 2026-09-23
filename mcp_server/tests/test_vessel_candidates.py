"""B3 get_vessel_candidates 단위 테스트. fixture 클라이언트로 키 없이 돈다."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from backend.app.clients.shipfinder import ShipFinderClient
from mcp_server.tools import vessel_candidates
from mcp_server.tools.vessel_candidates import get_vessel_candidates

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "shipfinder"


def _fresh(seconds_ago: int = 60) -> int:
    return int((datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).timestamp())


@pytest.fixture
def fake(monkeypatch):
    """검색 응답의 last_time을 지금 기준으로 바꿔 넣고, 상세 조회 응답도 함께 준다."""

    def _use(search_fixture: str = "search_same_name.json", *, dest="BUSAN, KR", flag="Panama", stale_mmsi=()):
        body = json.loads((FIXTURES / search_fixture).read_text(encoding="utf-8"))
        old = int((datetime.now(timezone.utc) - timedelta(days=60)).timestamp())
        for row in body["data"]:
            row["last_time"] = old if row["mmsi"] in stale_mmsi else _fresh()

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("VesselSearch"):
                return httpx.Response(200, json=body)
            if path.endswith("VesselFlagInfo"):
                return httpx.Response(200, json={"status": 0, "msg": "", "data": {"registry": flag}})
            pos = json.loads((FIXTURES / "position_busan_anchored.json").read_text(encoding="utf-8"))
            pos["data"]["mmsi"] = int(request.url.params["mmsi"])
            pos["data"]["dest"] = dest
            return httpx.Response(200, json=pos)

        client = ShipFinderClient(key="test-key", transport=httpx.MockTransport(handler))
        monkeypatch.setattr(vessel_candidates, "make_client", lambda: client)

    return _use


def test_keeps_same_name_candidates_and_scores_similarity(fake):
    fake()
    r = get_vessel_candidates("TEST STAR")

    names = [c["name"] for c in r["candidates"]]
    assert len(names) > 1  # 동명 선박은 좁히지 않고 그대로 넘긴다
    assert r["candidates"][0]["name"] == "TEST STAR"  # 정확히 일치하는 쪽이 먼저
    assert r["candidates"][0]["similarity"] == 1.0
    assert r["source"] == "shipfinder" and r["fetched_at"]


def test_same_imo_keeps_newest_only(fake):
    fake()
    mmsis = [c["mmsi"] for c in get_vessel_candidates("TEST STAR")["candidates"]]
    # 440999103·440999104는 IMO가 357289382로 같지만 7자리가 아니라 서로 다른 배로 둔다
    assert 440999103 in mmsis and 440999104 in mmsis
    # 9162150(정상 IMO)은 한 척만 남는다
    assert len([m for m in mmsis if m == 440999102]) == 1


def test_stale_candidates_dropped_by_eta_window(fake):
    fake(stale_mmsi=(440999101,))
    mmsis = [c["mmsi"] for c in get_vessel_candidates("TEST STAR", eta_window_days=7)["candidates"]]
    assert 440999101 not in mmsis


def test_nationality_filters_out_other_flags(fake):
    fake(flag="Panama")
    assert get_vessel_candidates("TEST STAR", nationality="Korea")["candidates"] == []


def test_detail_lookup_capped(fake):
    """상세 조회는 상위 MAX_LOOKUPS명까지만. 나머지는 flag·dest가 비어 있다."""
    fake()
    cands = get_vessel_candidates("TEST STAR")["candidates"]
    assert all(c["flag"] for c in cands[: vessel_candidates.MAX_LOOKUPS])
    assert all(c["flag"] is None for c in cands[vessel_candidates.MAX_LOOKUPS :])


def test_search_failure_returns_tool_error(fake, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 29, "msg": "too frequent"})

    client = ShipFinderClient(key="test-key", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(vessel_candidates, "make_client", lambda: client)
    r = get_vessel_candidates("TEST STAR")
    assert r["error"]["code"] == "rate_limited" and r["error"]["retryable"] is True
