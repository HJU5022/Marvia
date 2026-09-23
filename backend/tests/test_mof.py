"""B5 해수부 관제정보 클라이언트 테스트. fixture XML로 키 없이 돈다."""
from datetime import date
from pathlib import Path

import httpx
import pytest

from backend.app.clients.mof import BUSAN_PRT_AG_CD, MofClient, MofError

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "mof"


def _client(fixture: str, calls: list | None = None) -> MofClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(200, text=(FIXTURES / fixture).read_text(encoding="utf-8"))

    return MofClient(key="test-key", transport=httpx.MockTransport(handler))


def test_sends_required_params_and_busan_code():
    calls = []
    _client("control_busan.xml", calls).control_records(date(2026, 9, 22), date(2026, 9, 23))

    params = calls[0].url.params
    # 넷 중 하나라도 빠지면 INVALID_REQUEST_PARAMETER_ERROR가 난다
    assert params["serviceKey"] == "test-key"
    assert params["prtAgCd"] == BUSAN_PRT_AG_CD == "020"
    assert (params["sde"], params["ede"]) == ("20260922", "20260923")
    assert "clsgn" not in params


def test_call_sign_is_passed_when_given():
    calls = []
    _client("control_busan.xml", calls).control_records(date(2026, 9, 22), date(2026, 9, 22), call_sign="TEST01")
    assert calls[0].url.params["clsgn"] == "TEST01"


def test_parses_vessel_and_events():
    calls = _client("control_busan.xml").control_records(date(2026, 9, 22), date(2026, 9, 23))

    assert len(calls) == 2
    first = calls[0]
    assert (first.call_sign, first.ship_name, first.nationality) == ("TEST01", "테스트예선1호", "대한민국")
    assert (first.gross_tonnage, first.ship_kind) == (54, "기타 예선")
    assert [e.kind for e in first.events] == ["입항", "접안"]


def test_actual_arrival_is_earliest_arrival_event():
    call = _client("control_busan.xml").control_records(date(2026, 9, 22), date(2026, 9, 23))[0]
    # 입항 22:30, 접안 23:10 중 이른 쪽
    assert call.actual_arrival.hour == 22 and call.actual_arrival.minute == 30
    assert call.facility == "대평동호안"


def test_departure_only_has_no_arrival():
    call = _client("control_busan.xml").control_records(date(2026, 9, 22), date(2026, 9, 23))[1]
    assert call.actual_arrival is None and call.facility is None
    assert call.reported_arrival is not None  # 신고 입항일시는 따로 있다


def test_empty_result_is_not_an_error():
    assert _client("control_empty.xml").control_records(date(2026, 9, 24), date(2026, 9, 26)) == []


def test_error_result_code_raises():
    with pytest.raises(MofError) as e:
        _client("invalid_parameter.xml").control_records(date(2026, 9, 22), date(2026, 9, 22))
    assert e.value.result_code == "11" and e.value.retryable is False


def test_timeout_is_retryable():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    client = MofClient(key="test-key", transport=httpx.MockTransport(boom))
    with pytest.raises(MofError) as e:
        client.control_records(date(2026, 9, 22), date(2026, 9, 22))
    assert (e.value.code, e.value.retryable) == ("timeout", True)


def test_missing_key_rejected(monkeypatch):
    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)
    with pytest.raises(MofError) as e:
        MofClient()
    assert e.value.code == "bad_key"


def test_sailing_plans_parse_arrival_and_departure():
    """선박운항정보는 입출항 신고 기반이라 아직 안 들어온 배의 입항 예정을 준다."""
    plans = _client("sailing_busan.xml").sailing_plans(date(2026, 9, 24), date(2026, 9, 26))

    assert len(plans) == 2
    first = plans[0]
    assert (first.call_sign, first.ship_name, first.nationality) == ("TEST01", "테스트예선1호", "대한민국")
    assert first.planned_arrival.strftime("%Y-%m-%d %H:%M") == "2026-09-25 08:00"
    assert first.planned_departure.strftime("%H:%M") == "18:00"
    assert first.facility == "감만부두 4선석"
    assert (first.purpose, first.previous_port, first.next_port) == ("양하", "SHANGHAI", "광양")
    assert first.revision == "변경"  # 신고가 바뀐 건인지 알 수 있다


def test_sailing_plans_hit_the_other_endpoint():
    calls = []
    _client("sailing_busan.xml", calls).sailing_plans(date(2026, 9, 24), date(2026, 9, 26), call_sign="TEST01")

    assert calls[0].url.path.endswith("/VsslEtrynd5/Info5")
    assert calls[0].url.params["clsgn"] == "TEST01"
