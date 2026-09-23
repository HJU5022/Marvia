"""B6 get_port_schedule 단위 테스트. fixture XML로 키 없이 돈다."""
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from backend.app.clients.mof import MofClient
from mcp_server.tools import port_schedule
from mcp_server.tools.port_schedule import get_port_schedule

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "mof"


@pytest.fixture
def fake(monkeypatch):
    def _use(fixture: str = "control_busan.xml", calls: list | None = None):
        def handler(request: httpx.Request) -> httpx.Response:
            if calls is not None:
                calls.append(request)
            return httpx.Response(200, text=(FIXTURES / fixture).read_text(encoding="utf-8"))

        client = MofClient(key="test-key", transport=httpx.MockTransport(handler))
        monkeypatch.setattr(port_schedule, "make_client", lambda: client)

    return _use


def test_returns_actual_arrival_and_facility(fake):
    fake()
    r = get_port_schedule(call_sign="TEST01", ship_name="테스트예선1호")

    assert r["actual_arrival"].startswith("2026-09-22T22:30")
    assert r["facility"] == "대평동호안"
    assert [e["kind"] for e in r["control_events"]] == ["입항", "접안"]
    assert r["source"] == "mof" and r["fetched_at"]


def test_planned_arrival_is_none_for_now(fake):
    """관제정보는 실적만 준다. 입항 예정은 선박운항정보 연동 후에 채운다."""
    fake()
    assert get_port_schedule(call_sign="TEST01")["planned_arrival"] is None


def test_ship_name_picks_matching_vessel(fake):
    fake()
    r = get_port_schedule(ship_name="테스트벌크2호")
    assert r["actual_arrival"] is None  # 출항 기록만 있는 배
    assert r["control_events"][0]["kind"] == "출항"


def test_no_record_is_not_an_error(fake):
    """기록이 없으면 아직 안 들어왔다는 뜻일 수 있다. 빈 결과로 돌려준다."""
    fake("control_empty.xml")
    r = get_port_schedule(call_sign="TEST99")
    assert r["actual_arrival"] is None and r["control_events"] == []
    assert "error" not in r


def test_lookback_window_is_sent(fake):
    calls = []
    fake(calls=calls)
    get_port_schedule(call_sign="TEST01", lookback_days=5)
    params = calls[0].url.params
    assert params["ede"] == date.today().strftime("%Y%m%d")
    assert params["sde"] == (date.today() - timedelta(days=5)).strftime("%Y%m%d")


def test_requires_call_sign_or_ship_name(fake):
    fake()
    r = get_port_schedule()
    assert r["error"]["code"] == "bad_input"


def test_api_error_returns_tool_error(fake):
    fake("invalid_parameter.xml")
    r = get_port_schedule(call_sign="TEST01")
    assert r["error"]["code"] == "error" and r["error"]["retryable"] is False
