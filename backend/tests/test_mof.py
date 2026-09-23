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


# ---- 선박운항정보 (입항 신고). 값은 전부 가공값이다 ----

def test_arrival_reports_calls_info5_and_keeps_only_arrival_details():
    calls = []
    reports = _client("arrival_report_busan.xml", calls).arrival_reports(date(2026, 9, 22), date(2026, 9, 26))

    assert str(calls[0].url).startswith("https://apis.data.go.kr/1192000/VsslEtrynd5/Info5")
    assert calls[0].url.params["prtAgCd"] == "020"
    # 출항 신고만 있는 TEST13은 빠진다
    assert [r.call_sign for r in reports] == ["TEST11", "TEST12"]
    first = reports[0]
    assert (first.stage, first.facility, first.mrn) == ("변경", "테스트 신항 1선석", "26TEST0011I")


def test_final_stage_is_not_used_as_planned_arrival():
    # 최종 신고의 etryptDt는 실제 입항 시각이라 예정으로 쓰지 않는다 (mof.py 선박운항정보 절)
    changed, final = _client("arrival_report_busan.xml").arrival_reports(date(2026, 9, 22), date(2026, 9, 26))
    assert changed.planned_arrival is not None and changed.planned_arrival.hour == 12
    assert final.arrival_at is not None and final.planned_arrival is None


def test_find_arrival_by_mrn_matches_arrival_mrn_only():
    client = _client("arrival_report_busan.xml")
    found = client.find_arrival_by_mrn("26test0011i", date(2026, 9, 22), date(2026, 9, 26))
    assert found is not None and found.call_sign == "TEST11"
    # 출항 MRN(끝이 E)으로는 찾지 않는다
    assert client.find_arrival_by_mrn("26TEST0012E", date(2026, 9, 22), date(2026, 9, 26)) is None


def test_arrival_reports_follows_pages_until_total_count():
    # 51건 = 50건 페이지 + 1건 페이지. 두 번 부르고 멈춰야 한다
    def page_xml(page: int) -> str:
        start, count = (0, 50) if page == 1 else (50, 1)
        items = "".join(
            f"<item><clsgn>P{n:03d}</clsgn><vsslNm>테스트{n}</vsslNm><details><detail>"
            f"<reqstSeNm>최초</reqstSeNm><etryndNm>입항</etryndNm><etryptDt>2026-09-24T12:00:00+09:00</etryptDt>"
            f"<mrNum>26TEST{n:04d}I</mrNum></detail></details></item>"
            for n in range(start, start + count)
        )
        return (f"<response><header><resultCode>00</resultCode></header><body><items>{items}</items>"
                f"<totalCount>51</totalCount></body></response>")

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text=page_xml(int(request.url.params["pageNo"])))

    client = MofClient(key="test-key", transport=httpx.MockTransport(handler))
    reports = client.arrival_reports(date(2026, 9, 24), date(2026, 9, 30))
    assert len(reports) == 51 and len(calls) == 2
