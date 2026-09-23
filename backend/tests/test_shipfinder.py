"""B2 ShipFinder 클라이언트 단위 테스트.

fixture는 evals/fixtures/shipfinder/. 실제 응답과 형식만 같은 가공값이다
(CLAUDE.md "실제 응답 원본은 커밋하지 않는다"). 진짜 호출은 scripts/fetch_shipfinder.py.
"""
import json
from pathlib import Path

import httpx
import pytest

from backend.app.clients.shipfinder import ShipFinderClient, ShipFinderError

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "shipfinder"


def _client(fixture: str | None = None, *, handler=None, calls: list | None = None) -> ShipFinderClient:
    def default(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(200, json=json.loads((FIXTURES / fixture).read_text(encoding="utf-8")))

    return ShipFinderClient(key="test-key", transport=httpx.MockTransport(handler or default))


def test_search_parses_hits_and_sends_params():
    calls = []
    result = _client("search_same_imo.json", calls=calls).search("TEST LEADER", max=500)

    assert [h.mmsi for h in result.hits] == [440999201, 440999202, 440999203]
    # 같은 IMO에 MMSI 2개. 최신 선택은 B3 몫이므로 클라이언트는 그대로 돌려준다
    assert result.hits[0].imo == result.hits[1].imo == 9900021
    assert result.hits[2].imo is None and result.hits[2].call_sign is None
    assert result.hits[0].last_time.year == 2026
    assert result.fetched_at.tzinfo is not None

    params = calls[0].url.params
    assert calls[0].url.path.endswith("/v1/AIS/VesselSearch")
    assert params["key"] == "test-key" and params["keywords"] == "TEST LEADER"
    assert params["max"] == "100"  # API 상한으로 자름


def test_position_parses_fields_and_invalid_markers():
    calls = []
    pos = _client("position_ok.json", calls=calls).position(440999002)

    assert calls[0].url.params["mmsi"] == "440999002"
    assert (pos.mmsi, pos.lat, pos.lng, pos.sog, pos.cog) == (440999002, 32.1, 119.6, 6.2, 80.8)
    assert pos.hdg is None  # 511 = 무효
    assert pos.imo is None  # 0 = 없음
    assert (pos.dest, pos.destcode, pos.navistat) == ("TAIZHOU,CN", "CNTZO", 0)
    assert pos.ais_eta is not None and pos.last_time is not None
    assert pos.raw["hdg"] == 511  # 원본은 보존


def test_position_without_eta_field():
    """실제 응답에는 eta 키가 아예 없고 hdg가 511.0(float)으로 오는 경우가 있다."""
    pos = _client("position_busan_anchored.json").position(440999001)
    assert (pos.ship_name, pos.destcode, pos.navistat) == ("TEST CARRIER 1", "KRPUS", 8)
    assert pos.ais_eta is None and pos.hdg is None
    assert pos.sog == 0.0  # 0은 무효가 아니라 정지


def test_search_same_name_many_candidates():
    """같은 선명이 여럿이고 IMO가 겹친다. 선박 식별을 되묻는 근거 (PRD 6.4)."""
    hits = _client("search_same_name.json").search("TEST STAR").hits
    assert len(hits) == 6
    assert sum(h.ship_name == "TEST STAR DREAM" for h in hits) == 3
    assert hits[2].imo == hits[3].imo == 300000001  # 7자리가 아닌 IMO도 원본 그대로 온다


@pytest.mark.parametrize(
    "fixture, code, status, retryable",
    [
        ("not_found.json", "not_found", 3, False),
        ("no_permission.json", "no_permission", 21, False),
        ("rate_limited.json", "rate_limited", 29, True),
    ],
)
def test_status_code_mapping_from_fixtures(fixture, code, status, retryable):
    with pytest.raises(ShipFinderError) as e:
        _client(fixture).position(440999001)
    assert (e.value.code, e.value.status, e.value.retryable) == (code, status, retryable)
    assert e.value.to_dict() == {"code": code, "message": e.value.message, "retryable": retryable}


@pytest.mark.parametrize(
    "status, code, retryable",
    [(9, "bad_key", False), (23, "rate_limited", True), (13, "busy", True), (14, "error", False)],
)
def test_status_code_mapping_other_codes(status, code, retryable):
    client = _client(handler=lambda r: httpx.Response(200, json={"status": status, "msg": ""}))
    with pytest.raises(ShipFinderError) as e:
        client.search("TEST STAR")
    assert (e.value.code, e.value.retryable) == (code, retryable)


def test_timeout_is_retryable():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ShipFinderError) as e:
        _client(handler=boom).position(440999001)
    assert (e.value.code, e.value.retryable) == ("timeout", True)


def test_http_5xx_is_error():
    with pytest.raises(ShipFinderError) as e:
        _client(handler=lambda r: httpx.Response(502)).search("TEST STAR")
    assert e.value.code == "error"


def test_missing_key_rejected(monkeypatch):
    monkeypatch.delenv("SHIPFINDER_KEY", raising=False)
    with pytest.raises(ShipFinderError) as e:
        ShipFinderClient()
    assert e.value.code == "bad_key"
