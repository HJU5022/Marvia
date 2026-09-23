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
    def _use(fixture: str = "control_busan.xml", calls: list | None = None, report: str = "arrival_report_busan.xml"):
        # 관제정보(CntlVssl2)와 선박운항정보(VsslEtrynd5)를 주소로 나눠 각자 fixture를 돌려준다
        def handler(request: httpx.Request) -> httpx.Response:
            if calls is not None:
                calls.append(request)
            name = report if "VsslEtrynd5" in str(request.url) else fixture
            return httpx.Response(200, text=(FIXTURES / name).read_text(encoding="utf-8"))

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


def test_planned_arrival_comes_from_arrival_report(fake):
    """입항 예정은 선박운항정보에서 온다. 최초·변경 단계 값만 쓰고 최종은 뺀다.

    fixture에는 변경(09-24 12:00)과 최종(09-22 13:54) 신고가 있다. 최종은 실제 시각이라 예정이 아니다.
    """
    fake()
    assert get_port_schedule(call_sign="TEST11")["planned_arrival"].startswith("2026-09-24T12:00")


def test_report_query_uses_call_sign_and_looks_ahead(fake):
    calls = []
    fake(calls=calls)
    get_port_schedule(call_sign="TEST11", lookback_days=2)
    report_call = next(c for c in calls if "VsslEtrynd5" in str(c.url))
    assert report_call.url.params["clsgn"] == "TEST11"
    assert report_call.url.params["ede"] == (date.today() + timedelta(days=port_schedule.LOOKAHEAD_DAYS)).strftime("%Y%m%d")


def test_ship_name_only_skips_report_query(fake):
    """선박운항정보는 한글 선명이라 영문 선명으로 못 찾는다. 호출부호가 없으면 부르지 않는다."""
    calls = []
    fake(calls=calls)
    r = get_port_schedule(ship_name="테스트벌크2호")
    assert r["planned_arrival"] is None
    assert not any("VsslEtrynd5" in str(c.url) for c in calls)


def test_report_failure_keeps_actual_records(fake):
    """예정 조회가 실패해도 실적은 그대로 준다. 예정만 비운다."""
    fake(report="invalid_parameter.xml")
    # fake는 실제 API처럼 호출부호로 걸러 주지 않아서 선명도 같이 준다
    r = get_port_schedule(call_sign="TEST01", ship_name="테스트예선1호")
    assert "error" not in r
    assert r["planned_arrival"] is None and r["actual_arrival"].startswith("2026-09-22T22:30")


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
