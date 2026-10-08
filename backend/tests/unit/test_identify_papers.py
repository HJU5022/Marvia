"""services/judge/identify.match_by_papers 테스트 (서류 대조 확정).

동명 선박이 여럿이고 사용자가 항차·포워더 입항 예정일을 안 줬을 때, 세관 입항일·적재항과 후보별 해수부 입항 신고가
둘 다 맞는 배가 정확히 1척이면 확정하는지 본다. 해수부는 가짜 클라이언트로 바꿔 끼워 키 없이 돈다.
값은 전부 모의값이다 (B/L·호출부호·MMSI 모두 TEST 계열, CLAUDE.md).
"""
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.clients.mof import MofError
from backend.app.main import app
from backend.app.routers import agent as agent_router
from backend.app.schemas.customs import CustomsRecord
from backend.app.services.judge import identify
from backend.tests.integration.test_routers import JUDGED, POSITION, _candidate, _request, fake  # noqa: F401  fake는 fixture

NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
KST = timezone(timedelta(hours=9))
ENTRY = datetime(2026, 9, 24)  # 세관 입항(예정)일. UNI-PASS는 시간대 없이 준다


def _customs(entry=ENTRY, port="Ningbo", nat=None) -> CustomsRecord:
    """모의 세관 기록. 입항일(etprDt)·적재항 이름(ldprNm)·국적(shipNat)만 이 기능에 쓰인다."""
    return CustomsRecord(ship_name="TEST STAR", entry_date=entry, loading_port_name=port, ship_nat=nat,
                         bl_masked="TEST****0001", fetched_at=NOW)


SAME_SIGN = agent_router._same_call_sign
SAME_NAT = agent_router._same_nationality
WINDOW = (date(2026, 9, 23), date(2026, 9, 25))  # 세관 입항일 9/24 앞뒤 SEARCH_DAYS(1)일


@dataclass
class Plan:
    """SailingPlan에서 match_by_papers가 읽는 세 칸만 흉내 낸다."""

    planned_arrival: datetime | None
    previous_port: str | None
    call_sign: str | None


def _arrive(day: int, hour: int = 10, prev: str | None = "NINGBO PT", sign: str | None = "") -> Plan:
    """한국 시각 9월 day일 hour시에 들어오는 신고. sign이 ""이면 FakeMof가 조회한 호출부호를 채운다."""
    return Plan(datetime(2026, 9, day, hour, tzinfo=KST), prev, sign)


class FakeMof:
    """sailing_plans만 흉내 낸다. 호출부호별로 정해 둔 신고를 돌려주고 받은 인자를 기록한다.
    errors에 든 호출부호는 MofError를 낸다. 라우터·서비스가 여러 스레드로 부르므로 기록은 잠금 안에서 한다.
    호출 순서는 스레드에 따라 달라서 테스트는 집합으로만 비교한다."""

    def __init__(self, plans: dict[str, list[Plan]], errors: set[str] = frozenset()):
        self.plans, self.errors, self.calls = plans, errors, []
        self._lock = threading.Lock()

    def sailing_plans(self, start, end, call_sign=None, **kwargs):
        with self._lock:
            self.calls.append((start, end, call_sign))
        if call_sign in self.errors:
            raise MofError("timeout", "테스트")
        # sign이 ""(기본)인 신고는 조회한 호출부호의 신고로 만든다
        return [Plan(p.planned_arrival, p.previous_port, call_sign if p.call_sign == "" else p.call_sign)
                for p in self.plans.get(call_sign, [])]


def _rows(*pairs, flag="Panama") -> list[dict]:
    """(mmsi, call_sign) 쌍으로 ShipFinder 후보 원본 줄을 만든다."""
    return [_candidate(mmsi, call_sign=cs) | {"flag": flag} for mmsi, cs in pairs]


def _match(customs, rows, mof, **kw):
    """라우터와 같은 비교 함수(_same_call_sign, _same_nationality)를 넘겨 부른다."""
    return identify.match_by_papers(customs, rows, same_call_sign=SAME_SIGN, same_nationality=SAME_NAT, mof=mof, **kw)


TWO = ((440999001, "TST01"), (440999002, "TST02"))


# ── 서비스: 확정 근거 (날짜·적재항) ──────────────────────────

def test_one_candidate_matches_date_and_port():
    """한 척만 날짜·적재항이 둘 다 맞으면 그 배를 근거 한 줄과 함께 돌려준다."""
    mof = FakeMof({"TST01": [_arrive(24, prev="SHANGHAI")], "TST02": [_arrive(24)]})
    got = _match(_customs(), _rows(*TWO), mof)

    assert got is not None
    mmsi, call_sign, reason = got
    assert (mmsi, call_sign) == (440999002, "TST02")
    assert "2026-09-24" in reason and "Ningbo" in reason
    # 후보마다 호출부호로 한 번씩, 세관 입항일 앞뒤 1일을 조회한다. 병렬이라 순서는 보지 않는다
    assert sorted(mof.calls, key=lambda c: c[2]) == [(*WINDOW, "TST01"), (*WINDOW, "TST02")]


def test_date_matches_but_port_differs_is_none():
    mof = FakeMof({"TST01": [_arrive(24, prev="SHANGHAI")], "TST02": [_arrive(24, prev="QINGDAO")]})
    assert _match(_customs(), _rows(*TWO), mof) is None


def test_port_matches_but_date_off_by_one_day_is_none():
    """조회 기간(±1일) 안이라 신고는 오지만 날짜가 하루 다르면 맞지 않는다."""
    mof = FakeMof({"TST01": [_arrive(25)], "TST02": [_arrive(23)]})
    assert _match(_customs(), _rows(*TWO), mof) is None


def test_two_candidates_both_match_is_none():
    """둘 다 맞으면 서류로 가를 수 없다. 되묻는다 (PRD 6.2)."""
    mof = FakeMof({"TST01": [_arrive(24)], "TST02": [_arrive(24, prev="NINGBO")]})
    assert _match(_customs(), _rows(*TWO), mof) is None


def test_compares_by_kst_date_not_utc_date():
    """세관 입항일은 시간대 없는 9/24, 해수부 신고는 UTC로 9/23 16:00(= 한국 9/24 01:00).
    UTC 날짜로 비교하면 9/23이라 틀리고, 한국 날짜로 비교해야 맞는다.
    반대로 UTC 9/24 15:30은 한국 9/25 00:30이라 맞지 않아야 한다."""
    late_utc_evening = Plan(datetime(2026, 9, 23, 16, 0, tzinfo=timezone.utc), "NINGBO PT", "")
    next_kst_day = Plan(datetime(2026, 9, 24, 15, 30, tzinfo=timezone.utc), "NINGBO PT", "")
    mof = FakeMof({"TST01": [late_utc_evening], "TST02": [next_kst_day]})

    got = _match(_customs(), _rows(*TWO), mof)
    assert got is not None and got[:2] == (440999001, "TST01")


@pytest.mark.parametrize(("loading", "previous", "same"), [
    ("Ningbo", "NINGBO PT", True),
    ("NINGBO PT", "ningbo", True),
    ("Qingdao", "QINGDAO", True),
    ("Ningbo", "SHANGHAI", False),
    # 가운데에만 들어 있으면 같은 항구로 보지 않는다 (앞부분 비교, 검토)
    ("Ningbo", "XINGANG NINGBO", False),
    ("Busan", "NEW BUSAN", False),
    ("Ningbo", "", False),
    ("Ningbo", None, False),
    ("", "NINGBO", False),
    (None, "NINGBO", False),
    ("", "", False),
    (None, None, False),
])
def test_port_normalization(loading, previous, same):
    """대소문자·공백 차이는 같고, 한쪽이 다른 쪽 앞부분이면 같다. 빈 값은 절대 맞지 않는다."""
    assert identify._same_port(loading, previous) is same


def test_plan_without_previous_port_never_matches():
    mof = FakeMof({"TST01": [_arrive(24, prev=None)], "TST02": [_arrive(24, prev="")]})
    assert _match(_customs(), _rows(*TWO), mof) is None


# ── 서비스: 신고의 호출부호 ────────────────────────────────

@pytest.mark.parametrize("plan_sign", ["OTHER9", None])
def test_plan_of_other_or_unknown_call_sign_never_counts(plan_sign):
    """해수부가 준 신고의 호출부호가 조회한 것과 다르거나 비어 있으면 그 배의 신고로 치지 않는다."""
    mof = FakeMof({"TST01": [_arrive(24, prev="SHANGHAI")], "TST02": [_arrive(24, sign=plan_sign)]})
    assert _match(_customs(), _rows(*TWO), mof) is None


def test_plan_call_sign_compared_case_insensitively():
    mof = FakeMof({"TST01": [_arrive(24, prev="SHANGHAI")], "TST02": [_arrive(24, sign="tst02 ")]})
    got = _match(_customs(), _rows(*TWO), mof)
    assert got is not None and got[0] == 440999002


# ── 서비스: 빼는 근거 (국적)와 확인 못 한 후보 ────────────────

def test_nationality_mismatch_is_excluded_before_matching():
    """세관 국적 KR. 파나마 국적 후보는 서류가 맞아도 대조 전에 빠지고, 남은 1척이 맞으면 확정한다."""
    rows = _rows((440999001, "TST01"), flag="Panama") + _rows((440999002, "TST02"), flag="Korea, Republic of")
    mof = FakeMof({"TST01": [_arrive(24)], "TST02": [_arrive(24)]})

    got = _match(_customs(nat="KR"), rows, mof)
    assert got is not None and got[:2] == (440999002, "TST02")
    assert {c[2] for c in mof.calls} == {"TST02"}  # 뺀 배는 조회하지 않는다


def test_missing_nationality_keeps_all_candidates():
    """세관 국적이 없으면 아무도 빼지 않는다. 둘 다 맞으니 가를 수 없다."""
    mof = FakeMof({"TST01": [_arrive(24)], "TST02": [_arrive(24)]})
    assert _match(_customs(nat=None), _rows(*TWO), mof) is None
    assert {c[2] for c in mof.calls} == {"TST01", "TST02"}


def test_missing_candidate_flag_keeps_candidate():
    """후보 국적이 비어 있으면 빼지 않는다. 그래서 둘 다 맞아 None."""
    rows = _rows((440999001, "TST01"), flag=None) + _rows((440999002, "TST02"), flag="Korea, Republic of")
    mof = FakeMof({"TST01": [_arrive(24)], "TST02": [_arrive(24)]})
    assert _match(_customs(nat="KR"), rows, mof) is None


@pytest.mark.parametrize("missing", ["", None])
def test_candidate_without_call_sign_makes_result_none(missing):
    """호출부호가 없는 후보가 남아 있으면 그 배를 확인할 수 없다. "1척만 맞다"고 못 하니 해수부도 부르지 않고 None."""
    mof = FakeMof({"TST02": [_arrive(24)]})
    assert _match(_customs(), _rows((440999001, missing), (440999002, "TST02")), mof) is None
    assert mof.calls == []


def test_candidate_without_call_sign_excluded_by_nationality_does_not_block():
    """호출부호 없는 후보라도 국적이 달라 빠졌으면 확인할 필요가 없다."""
    rows = _rows((440999001, None), flag="Panama") + _rows((440999002, "TST02"), flag="Korea, Republic of")
    got = _match(_customs(nat="KR"), rows, FakeMof({"TST02": [_arrive(24)]}))
    assert got is not None and got[0] == 440999002


def test_same_call_sign_is_queried_once():
    """호출부호가 같은 줄이 둘이면 해수부는 한 번만 부른다. MMSI가 서로 다르면 어느 MMSI인지 근거가 없어 확정하지 않는다 (2차 검토)."""
    mof = FakeMof({"TST01": [_arrive(24)]})
    got = _match(_customs(), _rows((440999001, "TST01"), (440999011, " tst01 ")), mof)
    assert [c[2] for c in mof.calls] == ["TST01"] and got is None
    # 같은 MMSI가 두 줄로 온 경우는 1척이라 확정한다
    mof = FakeMof({"TST01": [_arrive(24)]})
    got = _match(_customs(), _rows((440999001, "TST01"), (440999001, "TST 01")), mof)
    assert got is not None and got[0] == 440999001


@pytest.mark.parametrize("customs", [_customs(entry=None), _customs(port=None), _customs(port="")])
def test_missing_customs_values_skip_mof(customs):
    """세관 입항일이나 적재항이 없으면 비교할 근거가 없다. 해수부를 부르지 않는다."""
    mof = FakeMof({"TST01": [_arrive(24)]})
    assert _match(customs, _rows((440999001, "TST01")), mof) is None
    assert mof.calls == []


@pytest.mark.parametrize("failing", ["TST01", "TST02"])
def test_mof_error_on_any_candidate_is_none(failing):
    """한 척이라도 조회에 실패하면 "1척만 맞다"고 말할 수 없다. 다른 배가 맞아도 None."""
    mof = FakeMof({"TST01": [_arrive(24)], "TST02": [_arrive(24, prev="SHANGHAI")]}, errors={failing})
    assert _match(_customs(), _rows(*TWO), mof) is None


def test_missing_mof_key_returns_none(monkeypatch):
    """해수부 키가 없고 REPLAY도 꺼져 있으면 MofClient()가 MofError(bad_key)를 낸다. 예외 없이 None이어야 한다."""
    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)
    monkeypatch.setenv("REPLAY_MODE", "false")
    assert identify.match_by_papers(_customs(), _rows(*TWO), same_call_sign=SAME_SIGN, same_nationality=SAME_NAT) is None


# ── 서비스: MRN 호출부호와 어긋남 ──────────────────────────

def test_mrn_call_sign_differs_from_match_is_none():
    """MRN 서류의 호출부호를 아는데 서류로 맞은 배의 호출부호가 다르면 확정하지 않는다 (단일 후보 B07과 같은 기준)."""
    mof = FakeMof({"TST01": [_arrive(24, prev="SHANGHAI")], "TST02": [_arrive(24)]})
    assert _match(_customs(), _rows(*TWO), mof, mrn_call_sign="TST09") is None


def test_mrn_call_sign_same_as_match_confirms():
    mof = FakeMof({"TST01": [_arrive(24, prev="SHANGHAI")], "TST02": [_arrive(24)]})
    got = _match(_customs(), _rows(*TWO), mof, mrn_call_sign=" tst02")
    assert got is not None and got[0] == 440999002


# ── 라우터: _identify가 되묻기 직전에 서류 대조를 쓴다 ──────────

def _papers_customs() -> CustomsRecord:
    return CustomsRecord(ship_name="TEST STAR", ship_nat="PA", stage_name="반입신고", entry_date=ENTRY,
                         loading_port_name="Ningbo", bl_masked="TEST****0001", fetched_at=NOW)


def test_router_confirms_by_papers(fake, monkeypatch):
    """동명 2척, 항차·포워더 ETA 없음. 서류가 1척만 맞으면 되묻지 않고 확정해 판정까지 간다.
    LLM 선택은 부르지 않고, 화면 후보는 확정한 배 1척뿐이며 근거 한 줄이 그 배에 붙는다."""
    fake(customs=_papers_customs(), candidates=[_candidate(440999001), _candidate(440999002, call_sign="TST02")],
         position={**POSITION, "mmsi": 440999002}, judge=JUDGED)
    mof = FakeMof({"TST01": [_arrive(24, prev="SHANGHAI")], "TST02": [_arrive(24)]})
    monkeypatch.setattr(agent_router.identify, "MofClient", lambda *a, **k: mof)
    picks = []
    monkeypatch.setattr(agent_router.llm, "pick_vessel", lambda *a, **k: picks.append(1))

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert picks == []
    assert body["status"] != "insufficient" and body["vessel_match"] == "confirmed"
    assert body["missing_inputs"] == []
    assert [c["mmsi"] for c in body["vessel_candidates"]] == [440999002]
    assert any("해수부 입항 신고가 일치" in r for r in body["vessel_candidates"][0]["match_reasons"])


def test_router_asks_back_when_papers_do_not_settle(fake, monkeypatch):
    """서류가 둘 다 맞으면(가를 수 없으면) 지금까지처럼 되묻는다."""
    fake(customs=_papers_customs(), candidates=[_candidate(440999001), _candidate(440999002, call_sign="TST02")])
    mof = FakeMof({"TST01": [_arrive(24)], "TST02": [_arrive(24)]})
    monkeypatch.setattr(agent_router.identify, "MofClient", lambda *a, **k: mof)

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert body["status"] == "insufficient" and body["vessel_match"] == "uncertain"
    assert set(body["missing_inputs"]) == {"voyage_no", "forwarder_eta"}
    assert len(body["vessel_candidates"]) == 2


def test_router_asks_back_when_mrn_call_sign_conflicts(fake, monkeypatch):
    """MRN으로 찾은 호출부호(TST09)가 서류로 맞은 배(TST02)와 다르면 확정하지 않고 되묻는다."""
    fake(customs=_papers_customs(), candidates=[_candidate(440999001), _candidate(440999002, call_sign="TST02")],
         position={**POSITION, "mmsi": 440999002}, judge=JUDGED)
    monkeypatch.setattr(agent_router.identify, "call_sign_from_mrn", lambda customs: "TST09")
    mof = FakeMof({"TST01": [_arrive(24, prev="SHANGHAI")], "TST02": [_arrive(24)]})
    monkeypatch.setattr(agent_router.identify, "MofClient", lambda *a, **k: mof)

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert body["status"] == "insufficient" and body["vessel_match"] == "uncertain"
    assert {c[2] for c in mof.calls} == {"TST01", "TST02"}  # 서류 대조까지는 갔다


def test_router_does_not_confirm_vessel_missing_from_candidates(fake, monkeypatch):
    """마지막 신호 시각이 없는 줄은 화면 후보에서 빠진다 (routers/agent._candidates).
    그 줄은 서류 대조에도 넘기지 않아야 한다. 그 줄만 서류가 맞으면 확정하지 않는다."""
    ghost = {**_candidate(440999003, call_sign="TST03"), "last_time": None}
    fake(customs=_papers_customs(), candidates=[_candidate(440999001), _candidate(440999002, call_sign="TST02"), ghost],
         position={**POSITION, "mmsi": 440999003}, judge=JUDGED)
    mof = FakeMof({"TST03": [_arrive(24)]})
    monkeypatch.setattr(agent_router.identify, "MofClient", lambda *a, **k: mof)

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert body["vessel_match"] == "uncertain"
    assert "TST03" not in {c[2] for c in mof.calls}



# ── 2차 검토 반영 ──

def test_unknown_flag_name_is_not_excluded():
    """국적 이름을 알아볼 수 없으면(ISO 이름과 다른 모양) 빼지 않는다. 진짜 배를 대조 전에 지우지 않게."""
    from backend.app.routers.agent import _clearly_other_nationality
    assert not _clearly_other_nationality("KR", "South Korea")  # 모르는 모양: 빼지 않음
    assert _clearly_other_nationality("KR", "Panama") and _clearly_other_nationality("KR", "PA")
    assert not _clearly_other_nationality("KR", "Korea, Republic of") and not _clearly_other_nationality("ZZ", "Panama")
