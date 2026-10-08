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
    """관제정보와 선박운항정보를 경로로 갈라 fixture를 돌려준다."""

    def _use(fixture: str = "control_busan.xml", calls: list | None = None, sailing: str = "sailing_busan.xml"):
        def handler(request: httpx.Request) -> httpx.Response:
            if calls is not None:
                calls.append(request)
            name = sailing if request.url.path.endswith("Info5") else fixture
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


def test_planned_arrival_comes_from_sailing_info(fake):
    """관제정보는 실적만 준다. 입항 예정은 선박운항정보(Info5)에서 온다."""
    fake()
    result = get_port_schedule(call_sign="TEST01", ship_name="테스트예선1호")
    assert result["planned_arrival"].startswith("2026-09-25T08:00")


def test_earliest_plan_wins(fake):
    """예정이 여럿이면 가장 이른 입항을 쓴다."""
    fake()
    assert get_port_schedule(call_sign="TEST03", ship_name="테스트컨테이너3호")["planned_arrival"].startswith("2026-09-24T06:00")


def test_actual_facility_wins_over_planned(fake):
    """실적이 있으면 접안 시설은 실적 쪽을 쓴다. 예정은 바뀔 수 있다."""
    fake()
    assert get_port_schedule(call_sign="TEST01", ship_name="테스트예선1호")["facility"] == "대평동호안"


def test_lookahead_zero_skips_sailing_call(fake):
    calls = []
    fake(calls=calls)
    result = get_port_schedule(call_sign="TEST01", lookahead_days=0)
    assert result["planned_arrival"] is None
    assert not any(c.url.path.endswith("Info5") for c in calls)


def test_ship_name_picks_matching_vessel(fake):
    fake()
    r = get_port_schedule(ship_name="테스트벌크2호")
    assert r["actual_arrival"] is None  # 출항 기록만 있는 배
    assert r["control_events"][0]["kind"] == "출항"


def test_no_record_is_not_an_error(fake):
    """기록이 없으면 아직 안 들어왔다는 뜻일 수 있다. 빈 결과로 돌려준다."""
    fake("control_empty.xml", sailing="control_empty.xml")
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
    fake("invalid_parameter.xml", sailing="invalid_parameter.xml")
    r = get_port_schedule(call_sign="TEST01")
    assert r["error"]["code"] == "error" and r["error"]["retryable"] is False


def test_name_match_ignores_spacing_and_suffix(fake):
    """해수부 선명과 입력이 공백·호 접미사만 다르면 같은 배로 본다."""
    fake()
    result = get_port_schedule(ship_name="테스트 예선 1")
    assert result["actual_arrival"].startswith("2026-09-22T22:30")


def test_unmatched_name_returns_empty_not_another_vessel(fake):
    """닮은 이름이 없으면 빈 결과다. 남의 배 입항 시각을 그 배 것처럼 답하면 안 된다."""
    fake()
    result = get_port_schedule(ship_name="전혀다른배이름")
    assert result["actual_arrival"] is None and result["planned_arrival"] is None
    assert result["control_events"] == [] and "error" not in result


def test_name_search_reads_more_pages(fake):
    """호출부호 없이 선명으로 찾을 때는 뒤 페이지까지 본다. 부산은 하루 100건이 넘는다."""
    calls = []
    fake(calls=calls)
    get_port_schedule(ship_name="테스트예선1호")
    pages = [c.url.params.get("pageNo") for c in calls]
    assert pages.count("1") >= 1  # fixture가 한 페이지뿐이라 첫 장에서 멈춘다


def test_call_sign_search_reads_one_page(fake):
    calls = []
    fake(calls=calls)
    get_port_schedule(call_sign="TEST01")
    assert all(c.url.params.get("pageNo") == "1" for c in calls)


def test_final_revision_is_not_planned_arrival(fake):
    """최종 신고의 시각은 실제 입항 시각이라 예정으로 돌려주지 않는다 (2026-09-23 실측).

    arrival_report_busan.xml: TEST11은 변경(09-24 12:00), TEST12는 최종(09-22 13:54).
    """
    fake(sailing="arrival_report_busan.xml")
    assert get_port_schedule(call_sign="TEST11", ship_name="테스트컨테이너11")["planned_arrival"].startswith("2026-09-24T12:00")
    assert get_port_schedule(call_sign="TEST12", ship_name="테스트벌크12")["planned_arrival"] is None


# ── 도구는 예외를 던지지 않는다 (C4) ──

def test_missing_key_returns_bad_key_error(monkeypatch):
    """클라이언트 만들기에서 난 실패(키 없음)도 {error}로, 코드는 bad_key 그대로."""
    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)
    monkeypatch.delenv("REPLAY_MODE", raising=False)
    monkeypatch.setattr(port_schedule, "make_client", MofClient)
    r = get_port_schedule(call_sign="TEST01")
    assert (r["error"]["code"], r["error"]["retryable"]) == ("bad_key", False)


def test_unexpected_exception_returns_bad_response(monkeypatch):
    """응답 조립 중 예상 밖 예외(계약 검사 실패 등)도 도구 밖으로 새지 않는다."""
    class Broken:
        def control_records(self, *args, **kwargs):
            raise ValueError("깨진 응답")

    monkeypatch.setattr(port_schedule, "make_client", Broken)
    r = get_port_schedule(call_sign="TEST01")
    assert (r["error"]["code"], r["error"]["retryable"]) == ("bad_response", False)


def test_defaults_come_from_rules():
    """조회 기간·선명 비교 기준은 port-busan/rules.md 프론트매터 값이다 (C6)."""
    from backend.app.services.judge.rules import rule

    assert port_schedule.LOOKBACK_DAYS == rule("port_schedule_lookback_days")
    assert port_schedule.LOOKAHEAD_DAYS == rule("port_schedule_lookahead_days")
    assert port_schedule.NAME_MATCH_RATIO == rule("port_schedule_name_match_ratio")
