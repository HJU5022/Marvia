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
    # 440999103·440999104는 IMO가 300000001로 같지만 7자리가 아니라 서로 다른 배로 둔다
    assert 440999103 in mmsis and 440999104 in mmsis
    # 9900012(정상 IMO)은 한 척만 남는다
    assert len([m for m in mmsis if m == 440999102]) == 1


def test_stale_candidates_dropped_by_eta_window(fake):
    fake(stale_mmsi=(440999101,))
    mmsis = [c["mmsi"] for c in get_vessel_candidates("TEST STAR", eta_window_days=7)["candidates"]]
    assert 440999101 not in mmsis


def test_nationality_filters_out_other_flags(fake):
    """국적이 다른 것이 확인된 후보만 뺀다. 상세를 못 받아 국적을 모르는 후보는 남긴다."""
    fake(flag="Panama")
    kept = get_vessel_candidates("TEST STAR", nationality="Korea")["candidates"]
    assert all(c["flag"] is None for c in kept)  # 국적을 아는 후보는 전부 빠졌다


def test_flag_is_fetched_even_when_position_fails(monkeypatch):
    """위치가 없는 배(신호 끊김)도 국적은 받는다. 전에는 위치가 실패하면 국적도 건너뛰었다 (평가 B14)."""
    body = {"status": 0, "msg": "", "data": [
        {"match_type": 1, "mmsi": 351999301, "imo": 9900301, "call_sign": "3ETS1", "ship_name": "TEST STAR", "last_time": _fresh()}]}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("VesselSearch"):
            return httpx.Response(200, json=body)
        if path.endswith("VesselFlagInfo"):
            return httpx.Response(200, json={"status": 0, "msg": "", "data": {"registry": "Panama"}})
        return httpx.Response(200, json={"status": 3, "msg": "Operation target does not exist"})  # 위치 없음

    client = ShipFinderClient(key="test-key", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(vessel_candidates, "make_client", lambda: client)
    only = get_vessel_candidates("TEST STAR")["candidates"][0]
    assert only["flag"] == "Panama" and only["dest"] is None


def test_call_sign_is_carried_for_mof_lookup(fake):
    """호출부호는 해수부 조회 키다. 검색 응답에 있는 값을 그대로 넘긴다."""
    fake()
    first = get_vessel_candidates("TEST STAR")["candidates"][0]
    assert first["call_sign"] == "TST01"


def test_call_sign_search_keeps_exact_call_sign_only(fake):
    """호출부호로 찾으면 호출부호가 같은 배만 남긴다. 대소문자는 가리지 않는다 (MRN 식별)."""
    fake()
    got = get_vessel_candidates("TEST STAR", call_sign="tst02")["candidates"]
    assert [c["mmsi"] for c in got] == [440999102]


def test_call_sign_search_drops_old_holders(fake):
    """호출부호는 다른 배에 다시 배정된다. 최근에 신호를 보낸 배만 지금 그 호출부호를 쓰는 배다 (같은 호출부호 3척)."""
    fake(stale_mmsi=(440999102,))
    assert get_vessel_candidates("TEST STAR", call_sign="TST02")["candidates"] == []


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


def test_failed_detail_lookup_is_logged(monkeypatch, caplog):
    """후보 한 척의 위치 조회가 실패하면 목록은 그대로 주되 로그를 남긴다. 국적까지 모르면 B14 비교를 못 한다."""
    body = {"status": 0, "msg": "", "data": [
        {"match_type": 1, "mmsi": 351999301, "imo": 9900301, "call_sign": "3ETS1", "ship_name": "TEST STAR", "last_time": _fresh()}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("VesselSearch"):
            return httpx.Response(200, json=body)
        if request.url.path.endswith("VesselFlagInfo"):
            return httpx.Response(200, json={"status": 0, "msg": "", "data": {"registry": "Panama"}})
        return httpx.Response(200, json={"status": 3, "msg": "Operation target does not exist"})

    client = ShipFinderClient(key="test-key", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(vessel_candidates, "make_client", lambda: client)
    with caplog.at_level("WARNING", logger="marvia.failure"):
        get_vessel_candidates("TEST STAR")

    logged = [(r.stage, r.error) for r in caplog.records if r.name == "marvia.failure"]
    assert len(logged) == 1 and logged[0][0] == "candidate_detail" and logged[0][1].startswith("position ")
