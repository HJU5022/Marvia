"""get_port_schedule 호출부호 우선 테스트. 키 없이 가짜 해수부 클라이언트로 돈다.

국적선은 해수부 선명이 한글이고 세관·ShipFinder 선명은 영문이다. 호출부호로 찾은 기록을 선명으로 다시 거르면
그 배의 입항 예정·실적이 사라졌다 (데모 TESTBL48). 호출부호가 같으면 선명과 상관없이 쓰는지 본다.
값은 전부 모의값이다 (호출부호 TST, 선명 테스트, CLAUDE.md).
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.clients.mof import ControlEvent, SailingPlan, VesselCall
from mcp_server.tools import port_schedule

KST = timezone(timedelta(hours=9))
PLANNED = datetime(2026, 9, 24, 12, 0, tzinfo=KST)
ARRIVED = datetime(2026, 9, 22, 6, 0, tzinfo=KST)


def _plan(call_sign: str, name: str, at: datetime) -> SailingPlan:
    return SailingPlan(call_sign=call_sign, ship_name=name, nationality="KR", ship_kind=None, purpose=None,
                       previous_port=None, next_port=None, planned_arrival=at, planned_departure=None,
                       facility="테스트부두", revision="변경")


def _call(call_sign: str, name: str, at: datetime) -> VesselCall:
    return VesselCall(call_sign=call_sign, ship_name=name, nationality="KR", gross_tonnage=None, ship_kind=None,
                      reported_arrival=at, events=[ControlEvent(kind="입항", at=at, facility="테스트부두")])


class _FakeMof:
    """API처럼 호출부호로 거르지 않고 받은 기록을 그대로 준다. 거르기는 도구 쪽 책임인지 보려는 것이다."""

    def __init__(self, calls, plans):
        self.calls, self.plans = calls, plans

    def control_records(self, start, end, call_sign=None, max_pages=1):
        return self.calls

    def sailing_plans(self, start, end, call_sign=None, max_pages=1):
        return self.plans


@pytest.fixture
def mof(monkeypatch):
    def _use(calls=(), plans=()):
        monkeypatch.setattr(port_schedule, "make_client", lambda: _FakeMof(list(calls), list(plans)))
    return _use


def test_call_sign_keeps_korean_name_record(mof):
    # 해수부 선명은 한글, 넘긴 선명은 영문. 호출부호가 같으니 입항 예정과 실적을 그대로 쓴다
    mof(calls=[_call("TST481", "테스트트윈사십팔", ARRIVED)], plans=[_plan("TST481", "테스트트윈사십팔", PLANNED)])
    r = port_schedule.get_port_schedule(call_sign="TST481", ship_name="TEST TWIN 48")
    assert r["planned_arrival"].startswith("2026-09-24T12:00")
    assert r["actual_arrival"].startswith("2026-09-22T06:00")
    assert r["facility"] == "테스트부두"


def test_call_sign_ignores_other_ships_with_same_name(mof):
    # 같은 한글 선명의 다른 배(호출부호가 다름)는 섞이지 않는다. 더 이른 예정이 있어도 남의 배 것은 안 쓴다
    early = PLANNED - timedelta(days=1)
    mof(plans=[_plan("TST482", "테스트트윈사십팔", early), _plan("TST481", "테스트트윈사십팔", PLANNED)])
    r = port_schedule.get_port_schedule(call_sign="tst481 ", ship_name="TEST TWIN 48")
    assert r["planned_arrival"].startswith("2026-09-24T12:00")


def test_name_only_query_still_filters_by_name(mof):
    # 호출부호 없이 선명만 주면 지금까지처럼 선명으로 거른다. 영문 선명으로 한글 기록을 고르지 않는다
    mof(plans=[_plan("TST481", "테스트트윈사십팔", PLANNED)])
    r = port_schedule.get_port_schedule(ship_name="TEST TWIN 48")
    assert r["planned_arrival"] is None


def test_call_sign_without_match_falls_back_to_name(mof):
    # 호출부호가 같은 기록이 없으면 예전처럼 선명으로 거른다 (호출부호 칸이 빈 기록 등)
    mof(plans=[_plan(None, "TEST TWIN 48", PLANNED), _plan("TST999", "OTHER SHIP", PLANNED - timedelta(days=1))])
    r = port_schedule.get_port_schedule(call_sign="TST481", ship_name="TEST TWIN 48")
    assert r["planned_arrival"].startswith("2026-09-24T12:00")
