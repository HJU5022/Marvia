"""해수부 클라이언트 시험 (계획 8a). 키·인터넷 없이 MockTransport와 재생 fixture로 돈다. 값은 가공값이다."""

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from marvia.identify.models import ToolError
from marvia.tools import mof
from marvia.tools.mof import control_arrivals, plan_by_mrn, port_schedule, sailing_plans
from marvia.tools.ports import Port, port
from marvia.tools.vessel import PortSchedule, SailingPlan

FIXTURES = Path(__file__).parent / "fixtures" / "mof"
KEY = "TESTKEY-NOT-REAL-0002"  # 가짜 키. 로그·오류 글에 나오면 안 된다
KST = timezone(timedelta(hours=9))
START, END = date(2026, 9, 21), date(2026, 9, 25)


def _client(*responses) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    left = iter(responses)

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = next(left)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.Client(transport=httpx.MockTransport(handle)), seen


def _xml(name: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=(FIXTURES / name).read_text(encoding="utf-8"))


def _plans(*responses, **kwargs):
    client, seen = _client(*responses)
    found = sailing_plans(
        "020", START, END, key=KEY, client=client, base_url="https://mof.test", sleep=lambda s: None, **kwargs
    )
    return found, seen


def test_sailing_plans_read_the_arrival_report_of_each_ship():
    plans, seen = _plans(_xml("sailing.xml"), call_sign="QQTST1")
    assert isinstance(plans, list) and len(plans) == 2
    first = plans[0]
    assert (first.call_sign, first.ship_name, first.previous_port) == ("QQTST1", "TEST CARGO A", "QINGDAO")
    assert first.planned_arrival == datetime(2026, 9, 24, 12, 0, tzinfo=KST) and first.revision == "변경"
    assert (first.facility, first.mrn) == ("TEST부두 1선석", "26TEST0001I")  # 출항 MRN(끝이 E)이 아니다
    sent = dict(seen[0].url.params)
    assert seen[0].url.path == "/1192000/VsslEtrynd5/Info5" and seen[0].url.host == "mof.test"
    assert (sent["prtAgCd"], sent["sde"], sent["ede"], sent["clsgn"]) == (
        "020",
        "20260921",
        "20260925",
        "QQTST1",
    )


def test_the_office_code_comes_from_the_caller_not_from_the_code():
    client, seen = _client(_xml("empty.xml"))
    assert sailing_plans("030", START, END, key=KEY, client=client, base_url="https://mof.test") == []
    assert dict(seen[0].url.params)["prtAgCd"] == "030"


def test_pages_are_followed_until_a_short_page_and_a_full_last_page_is_an_error(monkeypatch):
    monkeypatch.setitem(mof.CFG, "max_rows", 2)  # 가공 fixture는 한 쪽에 2건이다
    plans, seen = _plans(_xml("sailing.xml"), _xml("empty.xml"), max_pages=3)
    assert (
        isinstance(plans, list)
        and len(plans) == 2
        and [dict(r.url.params)["pageNo"] for r in seen] == ["1", "2"]
    )
    # [왜] 쪽 상한까지 꽉 차 있으면 뒤에 못 본 배가 있다. "없다"고 답하지 않고 오류로 돌려준다
    cut, _ = _plans(_xml("sailing.xml"), _xml("sailing.xml"), max_pages=2)
    assert isinstance(cut, ToolError) and cut.code == "too_many"


def test_control_arrivals_take_the_earliest_arrival_or_berthing_event():
    client, seen = _client(_xml("control.xml"))
    calls = control_arrivals(
        "020", START, END, key=KEY, client=client, base_url="https://mof.test", call_sign="QQTST2"
    )
    assert isinstance(calls, list) and len(calls) == 1 and seen[0].url.path == "/1192000/CntlVssl2/Info"
    # 투묘(닻 내림)는 입항이 아니다. 입항 10:00과 접안 10:40 가운데 이른 쪽이고 시설은 이름이 있는 쪽이다
    assert calls[0].call_sign == "QQTST2" and calls[0].actual_arrival == datetime(
        2026, 9, 22, 10, 0, tzinfo=KST
    )
    assert calls[0].facility == "TEST부두 2선석"


def test_timeouts_and_5xx_are_retried_twice_and_api_errors_are_fixed_texts():
    late, seen = _plans(*[httpx.ReadTimeout("t")] * 3)
    assert (
        late == ToolError(code="timeout", message=mof.CFG["messages"]["timeout"], retryable=True)
        and len(seen) == 3
    )
    down, seen = _plans(*[httpx.Response(503)] * 3)
    assert isinstance(down, ToolError) and (down.code, down.retryable, len(seen)) == ("unavailable", True, 3)
    ok, seen = _plans(httpx.Response(502), _xml("empty.xml"))
    assert ok == [] and len(seen) == 2
    bad_key, seen = _plans(_xml("key_error.xml"))
    assert isinstance(bad_key, ToolError) and (bad_key.code, bad_key.retryable, len(seen)) == (
        "bad_key",
        False,
        1,
    )
    assert "SERVICE_KEY" not in bad_key.message  # 바깥 글을 옮기지 않는다
    assert _plans(_xml("param_error.xml"))[0] == ToolError(
        code="api_error", message=mof.CFG["messages"]["api_error"], retryable=False
    )
    assert _plans(httpx.Response(200, text="<html>점검 중"))[0].code == "bad_response"  # type: ignore[union-attr]
    assert _plans(httpx.Response(404))[0].code == "bad_response"  # type: ignore[union-attr]


def test_key_never_reaches_logs_or_error_text(caplog):
    caplog.set_level(logging.DEBUG)
    error, _ = _plans(*[httpx.ConnectError(f"https://x/?serviceKey={KEY}")] * 3)
    ok, _ = _plans(_xml("sailing.xml"))
    assert isinstance(error, ToolError) and KEY not in error.message and KEY not in repr(error)
    assert isinstance(ok, list) and KEY not in caplog.text
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    raised, _ = _plans(httpx.DecodingError(f"https://x/?serviceKey={KEY}"))
    assert isinstance(raised, ToolError) and raised.code == "bad_response" and KEY not in repr(raised)


def test_plan_by_mrn_matches_the_arrival_mrn_only():
    plans, _ = _plans(_xml("sailing.xml"))
    assert isinstance(plans, list)
    found = plan_by_mrn(plans, "26test0001i")
    assert isinstance(found, SailingPlan) and found.call_sign == "QQTST1"
    assert plan_by_mrn(plans, "26TEST0001E") is None and plan_by_mrn(plans, "") is None


def test_replay_is_the_default_and_reads_only_that_office_folder(monkeypatch):
    monkeypatch.setattr(
        mof.httpx, "HTTPTransport", lambda *a, **k: pytest.fail("재생 모드에서 바깥 연결을 만들었다")
    )
    busan = port("KRPUS")
    assert busan is not None
    arrived = port_schedule(busan, "QQTST2", today=date(2026, 9, 22))
    assert isinstance(arrived, PortSchedule)
    # 최종 신고의 시각은 실제 입항 시각이라 예정으로 쓰지 않는다. 실적은 관제정보에서 온다
    assert arrived.planned_arrival is None and arrived.actual_arrival == datetime(
        2026, 9, 22, 10, 0, tzinfo=KST
    )
    coming = port_schedule(busan, "qqtst 1", today=date(2026, 9, 22))
    assert isinstance(coming, PortSchedule) and coming.actual_arrival is None
    assert (
        coming.planned_arrival == datetime(2026, 9, 24, 12, 0, tzinfo=KST)
        and coming.facility == "TEST부두 1선석"
    )
    unknown = port_schedule(busan, "QQNONE", today=date(2026, 9, 22))
    assert isinstance(unknown, PortSchedule) and (unknown.planned_arrival, unknown.actual_arrival) == (
        None,
        None,
    )
    # 청코드가 다른 항만은 부산 폴더를 읽지 않는다
    other = Port(
        code="KRTST", name="시험항", mof_office="999", schedule_lookback_days=3, schedule_lookahead_days=7
    )
    elsewhere = port_schedule(other, "QQTST1", today=date(2026, 9, 22))
    assert isinstance(elsewhere, PortSchedule) and elsewhere.planned_arrival is None


def test_a_port_without_office_or_window_is_a_fixed_error_not_a_busan_call():
    incheon = port("KRINC")
    assert incheon is not None  # 청코드는 있지만 조회 기간을 확인하지 못한 줄이다
    assert port_schedule(incheon, "QQTST1", today=date(2026, 9, 22)) == ToolError(
        code="port_unknown", message=mof.CFG["messages"]["port_unknown"], retryable=False
    )
    bare = Port(code="KRTST", name="시험항")
    assert port_schedule(bare, "QQTST1", today=date(2026, 9, 22)).code == "port_unknown"  # type: ignore[union-attr]


def test_live_without_a_key_refuses_without_calling(monkeypatch):
    monkeypatch.setenv("MARVIA_MOF_MODE", "live")
    monkeypatch.delenv("MARVIA_MOF_KEY", raising=False)
    real = mof.Settings
    monkeypatch.setattr(mof, "Settings", lambda: real(_env_file=None))  # [왜] .env의 실제 키를 읽지 않는다
    monkeypatch.setattr(mof.httpx, "Client", lambda *a, **k: pytest.fail("키 없이 HTTP를 열었다"))
    busan = port("KRPUS")
    assert busan is not None
    error = port_schedule(busan, "QQTST1", today=date(2026, 9, 22))
    assert error == ToolError(code="no_key", message=mof.CFG["messages"]["no_key"], retryable=False)


def test_live_sends_the_relay_token_to_the_relay_address_only(monkeypatch):
    monkeypatch.setenv("MARVIA_MOF_MODE", "live")
    monkeypatch.setenv("MARVIA_MOF_KEY", KEY)
    monkeypatch.setenv("MARVIA_MOF_BASE_URL", "https://relay.test/")
    monkeypatch.setenv("MARVIA_MOF_RELAY_TOKEN", "TESTTOKEN-NOT-REAL")
    real = mof.Settings
    monkeypatch.setattr(mof, "Settings", lambda: real(_env_file=None))
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _xml("empty.xml")

    real_client = httpx.Client
    monkeypatch.setattr(
        mof.httpx, "Client", lambda **kw: real_client(**{**kw, "transport": httpx.MockTransport(handle)})
    )
    busan = port("KRPUS")
    assert busan is not None
    assert isinstance(port_schedule(busan, "QQTST1", today=date(2026, 9, 22)), PortSchedule)
    assert {r.url.host for r in seen} == {"relay.test"} and len(
        seen
    ) == 2  # 관제정보 한 번, 선박운항정보 한 번
    assert all(r.headers["X-Relay-Token"] == "TESTTOKEN-NOT-REAL" for r in seen)
    assert all(not r.extensions.get("follow_redirects") for r in seen)


@pytest.mark.parametrize(
    ("name", "code", "outside"),
    [
        ("gateway_key.xml", "bad_key", "SERVICE_KEY"),
        ("gateway_quota.xml", "quota_exhausted", "LIMITED_NUMBER"),
        ("gateway_other.xml", "api_error", "APPLICATION_ERROR"),
    ],
)
def test_a_gateway_error_body_is_an_error_not_an_empty_result(name, code, outside):
    # [왜] 관문의 오류 본문에는 resultCode가 없다. 정상 0건으로 읽으면 키가 틀려도 "입항 신고 없음"이 된다
    found, seen = _plans(_xml(name))
    assert found == ToolError(code=code, message=mof.CFG["messages"][code], retryable=False)
    assert len(seen) == 1 and outside not in found.message  # 다시 부르지 않고, 바깥 글을 옮기지 않는다


@pytest.mark.parametrize(
    "body",
    [
        "<response><header/><body><items/></body></response>",  # 결과 코드가 없다
        "<response><header><resultCode>00</resultCode></header></response>",  # 목록 칸(items)이 없다
        "<other><header><resultCode>00</resultCode></header><body><items/></body></other>",  # 뿌리가 다르다
        "<html><body>점검 중</body></html>",
    ],
)
def test_a_body_of_an_unexpected_shape_is_bad_response_not_zero_rows(body):
    found, _ = _plans(httpx.Response(200, text=body))
    assert found == ToolError(
        code="bad_response", message=mof.CFG["messages"]["bad_response"], retryable=False
    )


def _arrivals(text: str):
    client, _ = _client(httpx.Response(200, text=text))
    return control_arrivals(
        "020", START, END, key=KEY, client=client, base_url="https://mof.test", sleep=lambda s: None
    )


def _control(details: str) -> str:
    head = "<response><header><resultCode>00</resultCode></header><body><items>"
    return f"{head}<item><clsgn>QQTST1</clsgn>{details}</item></items></body></response>"


def test_arrival_times_that_mix_zoned_and_unzoned_values_are_bad_response_not_an_exception():
    # [왜] 시간대가 있는 시각과 없는 시각은 견줄 수 없어 TypeError가 났다. 어느 쪽이 맞는지 짐작하지 않는다
    mixed = _control(
        "<detail><cntrlNm>입항</cntrlNm><cntrlOpertDt>2026-09-22T10:00:00</cntrlOpertDt></detail>"
        "<detail><cntrlNm>접안</cntrlNm><cntrlOpertDt>2026-09-22T11:00:00+09:00</cntrlOpertDt></detail>"
    )
    assert _arrivals(mixed) == ToolError(
        code="bad_response", message=mof.CFG["messages"]["bad_response"], retryable=False
    )
    # 시간대가 없는 값만 있어도 어느 시간대인지 모른다
    bare = _control(
        "<detail><cntrlNm>입항</cntrlNm><cntrlOpertDt>2026-09-22T10:00:00</cntrlOpertDt></detail>"
    )
    assert isinstance(_arrivals(bare), ToolError)


def test_a_json_body_is_bad_response():
    assert _arrivals('{"a": 1}') == ToolError(
        code="bad_response", message=mof.CFG["messages"]["bad_response"], retryable=False
    )


def _live(monkeypatch, base_url: str) -> list[httpx.Request]:
    """실제 모드로 두고, 나간 요청을 모으는 가짜 연결을 끼운다."""
    monkeypatch.setenv("MARVIA_MOF_MODE", "live")
    monkeypatch.setenv("MARVIA_MOF_KEY", KEY)
    monkeypatch.setenv("MARVIA_MOF_BASE_URL", base_url)
    monkeypatch.setenv("MARVIA_MOF_RELAY_TOKEN", "TESTTOKEN-NOT-REAL")
    real = mof.Settings
    monkeypatch.setattr(mof, "Settings", lambda: real(_env_file=None))
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _xml("empty.xml")

    real_client = httpx.Client
    monkeypatch.setattr(
        mof.httpx, "Client", lambda **kw: real_client(**{**kw, "transport": httpx.MockTransport(handle)})
    )
    return seen


@pytest.mark.parametrize(
    "base_url",
    [
        "http://relay.test",
        "ftp://relay.test",
        "relay.test",
        "https://evil.test\\@localhost",
        "https://relay .test",
    ],
)
def test_live_refuses_an_unsafe_address_without_sending_the_key_or_the_token(monkeypatch, base_url):
    seen = _live(monkeypatch, base_url)
    busan = port("KRPUS")
    assert busan is not None
    error = port_schedule(busan, "QQTST1", today=date(2026, 9, 22))
    assert error == ToolError(
        code="unsafe_address", message=mof.CFG["messages"]["unsafe_address"], retryable=False
    )
    assert seen == []


def test_live_allows_plain_http_on_loopback(monkeypatch):
    seen = _live(monkeypatch, "http://localhost:8080")
    busan = port("KRPUS")
    assert busan is not None
    assert isinstance(port_schedule(busan, "QQTST1", today=date(2026, 9, 22)), PortSchedule)
    assert {r.url.host for r in seen} == {"localhost"}


def test_live_without_a_relay_address_does_not_send_the_relay_token(monkeypatch):
    seen = _live(monkeypatch, "")
    busan = port("KRPUS")
    assert busan is not None
    assert isinstance(port_schedule(busan, "QQTST1", today=date(2026, 9, 22)), PortSchedule)
    assert {r.url.host for r in seen} == {"apis.data.go.kr"}
    assert all("X-Relay-Token" not in r.headers for r in seen)
