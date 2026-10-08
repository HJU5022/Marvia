"""B5 해수부 관제정보 클라이언트 테스트. fixture XML로 키 없이 돈다."""
from datetime import date
from pathlib import Path

import httpx
import pytest

from backend.app.clients.mof import BUSAN_PRT_AG_CD, MofClient, MofError

FIXTURES = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "mof"


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


# ---- 선박운항정보의 MRN과 최종 신고 (2026-09-23 실측 반영). 값은 전부 가공값이다 ----

def test_plan_carries_arrival_mrn_and_excludes_final_from_expected():
    changed, final = [p for p in _client("arrival_report_busan.xml").sailing_plans(date(2026, 9, 22), date(2026, 9, 26))
                      if p.planned_arrival]
    assert (changed.revision, changed.mrn) == ("변경", "26TEST0011I")  # 출항 MRN(끝 E)이 아니라 입항 MRN
    assert changed.expected_arrival.hour == 12
    assert final.revision == "최종" and final.planned_arrival is not None and final.expected_arrival is None


def test_find_plan_by_mrn_matches_arrival_mrn_only():
    client = _client("arrival_report_busan.xml")
    found = client.find_plan_by_mrn("26test0011i", date(2026, 9, 22), date(2026, 9, 26))
    assert found is not None and found.call_sign == "TEST11"
    assert client.find_plan_by_mrn("26TEST0012E", date(2026, 9, 22), date(2026, 9, 26)) is None


def test_page_cap_hit_is_logged_only_when_pages_run_out(caplog):
    """마지막으로 받은 페이지까지 꽉 차 있으면 뒤를 못 본 것이다. "기록 없음"과 구분하려고 남긴다.
    한 페이지만 보는 호출은 원래 한 페이지라 남기지 않는다."""
    with caplog.at_level("WARNING", logger="marvia.failure"):
        _client("control_busan.xml").control_records(date(2026, 9, 22), date(2026, 9, 23), rows=2, max_pages=2)
        _client("control_busan.xml").control_records(date(2026, 9, 22), date(2026, 9, 23), rows=2, max_pages=1)
        _client("control_busan.xml").control_records(date(2026, 9, 22), date(2026, 9, 23), rows=50, max_pages=5)

    logged = [(r.stage, r.error) for r in caplog.records if r.name == "marvia.failure"]
    assert logged == [("mof_control", "page_cap_hit 2")]


def test_sailing_plans_all_fetches_rest_pages_together():
    """첫 쪽 totalCount로 쪽 수를 알고 나머지를 동시에 받는다 (자연어 선박 검색). 쪽 순서는 유지."""
    from datetime import date
    from urllib.parse import parse_qs, urlparse

    def item(n):
        return f"<item><clsgn>CS{n}</clsgn><vsslNm>SHIP {n}</vsslNm><prvsPrtNm>PORT {n}</prvsPrtNm></item>"

    def handler(request):
        page = int(parse_qs(urlparse(str(request.url)).query)["pageNo"][0])
        items = "".join(item((page - 1) * 50 + i) for i in range(50 if page < 3 else 7))
        body = f"<response><header><resultCode>00</resultCode></header><body><items>{items}</items><totalCount>107</totalCount></body></response>"
        return httpx.Response(200, text=body)

    client = MofClient(key="test-key", transport=httpx.MockTransport(handler))
    plans = client.sailing_plans_all(date(2026, 10, 1), date(2026, 10, 8))
    assert len(plans) == 107 and plans[0].ship_name == "SHIP 0" and plans[-1].ship_name == "SHIP 106"


# ── 릴레이·연결 실패 차단기 ─────────────────────────


def _transport(handler, calls: list):
    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    return httpx.MockTransport(wrapped)


def _ok(request):
    return httpx.Response(200, text=(FIXTURES / "control_busan.xml").read_text(encoding="utf-8"))


def _refuse(request):
    raise httpx.ConnectTimeout("unreachable")


def test_base_url_comes_from_env(monkeypatch):
    monkeypatch.setenv("MOF_BASE_URL", "https://relay.example/")
    calls = []
    MofClient(key="k", transport=_transport(_ok, calls)).control_records(date(2026, 9, 22), date(2026, 9, 22))
    assert str(calls[0].url).startswith("https://relay.example/1192000/CntlVssl2/Info?")


def test_relay_token_header_only_when_set(monkeypatch):
    monkeypatch.delenv("MOF_RELAY_TOKEN", raising=False)
    calls = []
    MofClient(key="k", transport=_transport(_ok, calls)).control_records(date(2026, 9, 22), date(2026, 9, 22))
    assert "x-relay-token" not in calls[0].headers

    monkeypatch.setenv("MOF_RELAY_TOKEN", "tok")
    MofClient(key="k", transport=_transport(_ok, calls)).control_records(date(2026, 9, 22), date(2026, 9, 22))
    assert calls[1].headers["x-relay-token"] == "tok"


def test_connect_failure_is_retried_once():
    """연결 실패는 한 번만 바로 다시 부르고, 그래도 안 되면 timeout (실사용 33번)."""
    calls = []
    client = MofClient(key="k", transport=_transport(_refuse, calls))
    with pytest.raises(MofError) as e:
        client.control_records(date(2026, 9, 22), date(2026, 9, 22))
    assert e.value.code == "timeout"
    assert len(calls) == 2  # 처음 + 한 번 더. 읽기 재시도(3번)는 타지 않는다


def test_connect_blip_recovers_on_second_try():
    """첫 연결만 끊기고 두 번째에 붙으면 정상 결과 (실사용 33번)."""
    calls = []
    state = {"n": 0}

    def flaky(request):
        state["n"] += 1
        return _refuse(request) if state["n"] == 1 else _ok(request)

    MofClient(key="k", transport=_transport(flaky, calls)).control_records(date(2026, 9, 22), date(2026, 9, 22))
    assert len(calls) == 2


def test_circuit_skips_network_then_resets(monkeypatch):
    from backend.app.clients import mof

    now = [1000.0]
    monkeypatch.setattr(mof.time, "monotonic", lambda: now[0])
    calls = []
    client = MofClient(key="k", transport=_transport(_refuse, calls))
    with pytest.raises(MofError):
        client.control_records(date(2026, 9, 22), date(2026, 9, 22))
    assert len(calls) == 2

    now[0] += mof.CIRCUIT_OPEN_SEC / 2  # 차단 시간 안: 네트워크 없이 같은 오류
    with pytest.raises(MofError) as e:
        client.sailing_plans(date(2026, 9, 22), date(2026, 9, 22))
    assert e.value.code == "timeout" and len(calls) == 2

    now[0] += mof.CIRCUIT_OPEN_SEC  # 차단 시간 뒤: 다시 시도한다
    with pytest.raises(MofError):
        client.control_records(date(2026, 9, 22), date(2026, 9, 22))
    assert len(calls) == 4
