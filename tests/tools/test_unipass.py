"""UNI-PASS 실제 조회 클라이언트 시험 (done 2.3, 계획 3b Task 7). 키·인터넷 없이 MockTransport로 돈다."""

import logging
from pathlib import Path

import httpx
import pytest

from marvia.identify.models import CargoFacts, ToolError
from marvia.tools import unipass
from marvia.tools.unipass import fetch_cargo, lookup_cargo

FIXTURES = Path(__file__).parent / "fixtures" / "unipass"
KEY = "TESTKEY-NOT-REAL-0001"  # 가짜 키. 로그·오류 글에 나오면 안 된다
CARGO_NO = "TEST0099I0001000100"  # 19자리 화물관리번호 꼴 가공값
BL = "TESTHBL0000001"


def _client(*responses) -> tuple[httpx.Client, list[httpx.Request]]:
    """차례로 응답(또는 예외)을 내는 가짜 전송. 받은 요청을 모은다."""
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


def _fetch(*responses, number: str = CARGO_NO):
    client, seen = _client(*responses)
    return fetch_cargo(number, key=KEY, client=client, year=2026, sleep=lambda s: None), seen


def test_progress_reads_the_latest_history_row_as_the_stage():
    facts, seen = _fetch(_xml("progress_ok.xml"))
    assert isinstance(facts, CargoFacts)
    assert (facts.stage, facts.port, facts.vessel_name, facts.mrn) == (
        "반출신고",
        "부산항",
        "TEST STAR",
        "TEST0099I00",
    )
    assert facts.stage_at is not None and facts.stage_at.isoformat() == "2026-09-29T10:00:00+09:00"
    assert facts.source == "unipass"
    assert seen[0].url.params["cargMtNo"] == CARGO_NO and seen[0].url.params["crkyCn"] == KEY


def test_timeouts_and_5xx_are_retried_twice_then_fail_retryable():
    facts, seen = _fetch(httpx.Response(503), httpx.ReadTimeout("느림"), _xml("progress_ok.xml"))
    assert isinstance(facts, CargoFacts) and len(seen) == 3
    error, seen = _fetch(*[httpx.ConnectTimeout("느림")] * 3)
    assert error == ToolError(code="timeout", message=unipass.CFG["messages"]["timeout"], retryable=True)
    assert len(seen) == 3  # 처음 한 번 + 다시 두 번 (설계 7.2)


def test_client_errors_and_unreadable_bodies_are_not_retried():
    error, seen = _fetch(httpx.Response(404))
    assert (
        isinstance(error, ToolError)
        and error.code == "bad_response"
        and not error.retryable
        and len(seen) == 1
    )
    error, _ = _fetch(httpx.Response(200, text="<html>점검 중</html"))
    assert isinstance(error, ToolError) and error.code == "bad_response"


def test_notice_and_counts_are_read_not_guessed():
    error, _ = _fetch(_xml("param_error.xml"))
    assert isinstance(error, ToolError) and error.code == "bad_input"  # HTTP 200이어도 "없음"이 아니다
    error, _ = _fetch(_xml("two_cargos.xml"))
    assert isinstance(error, ToolError) and error.code == "ambiguous"  # 첫 화물을 고르지 않는다


def test_bl_is_tried_as_house_then_master():
    facts, seen = _fetch(_xml("not_found.xml"), _xml("progress_ok.xml"), number=BL)
    assert isinstance(facts, CargoFacts)
    assert [("hblNo" in r.url.params, "mblNo" in r.url.params) for r in seen] == [
        (True, False),
        (False, True),
    ]
    assert seen[0].url.params["blYy"] == "2026"
    error, seen = _fetch(_xml("not_found.xml"), _xml("not_found.xml"), number=BL)
    assert (
        isinstance(error, ToolError) and error.code == "not_found" and not error.retryable and len(seen) == 2
    )


def test_key_and_number_never_reach_logs_or_error_text(caplog):
    caplog.set_level(logging.DEBUG)
    results = [_fetch(*[httpx.ConnectError(f"https://x/?crkyCn={KEY}&cargMtNo={CARGO_NO}")] * 3)[0]]
    results.append(_fetch(_xml("progress_ok.xml"))[0])
    error = results[0]
    assert isinstance(error, ToolError) and KEY not in error.message and CARGO_NO not in error.message
    assert KEY not in caplog.text and CARGO_NO not in caplog.text
    # [왜] 음성 대조: 이 모듈이 httpx 로거를 올리지 않으면 INFO에 요청 주소 전체가 찍힌다
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


def test_replay_is_the_default_and_never_opens_a_connection(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("재생 모드에서 HTTP 클라이언트를 만들었다")

    monkeypatch.setattr(unipass.httpx, "Client", no_network)
    assert isinstance(lookup_cargo("DEMO0001"), CargoFacts)
    # [왜] B05(NOPE0001)의 행동이 계획 3b 전과 같아야 한다: 재생의 not_found, 다시 시도하지 않음
    error = lookup_cargo("NOPE0001")
    assert isinstance(error, ToolError) and (error.code, error.retryable) == ("not_found", False)


def test_live_without_a_key_refuses_without_calling(monkeypatch):
    monkeypatch.setenv("MARVIA_UNIPASS_MODE", "live")
    monkeypatch.delenv("MARVIA_UNIPASS_KEY", raising=False)
    real = unipass.Settings
    monkeypatch.setattr(
        unipass, "Settings", lambda: real(_env_file=None)
    )  # [왜] .env의 실제 키를 읽지 않는다
    monkeypatch.setattr(unipass.httpx, "Client", lambda *a, **k: pytest.fail("키 없이 HTTP를 열었다"))
    error = lookup_cargo(CARGO_NO)
    assert isinstance(error, ToolError) and error.code == "no_key"
