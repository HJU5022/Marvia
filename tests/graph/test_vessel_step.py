"""배 식별 단계 시험 (계획 8b). 바깥 조회는 재생 데이터이고 키 없이 돈다."""

import pytest

from marvia.graph import vessel
from marvia.identify.models import CargoFacts, ToolError
from marvia.tools import mof, shipfinder
from marvia.tools.rules import load_rules
from marvia.tools.shipfinder import VesselHit
from marvia.tools.unipass_replay import lookup_cargo


def facts(number: str) -> CargoFacts:
    found = lookup_cargo(number)
    assert isinstance(found, CargoFacts)
    return found


@pytest.fixture(autouse=True)
def _fresh():
    shipfinder.reset_state()


def test_mrn_leads_to_one_ship_and_the_call_sign_is_what_was_checked(monkeypatch):
    monkeypatch.setattr(
        mof, "plans_for", lambda *a, **k: pytest.fail("호출부호를 맞췄는데 입항 신고를 받았다")
    )
    found = vessel.find_vessel(facts("TESTVSL0001"))
    assert found == {
        "status": "confirmed",
        "reason": "mrn_call_sign",
        "basis": ["call_sign"],
        "cap": None,
        "mmsi": "999000001",
        "call_sign": "QQTST1",
        "name": "TEST CARGO A",
    }


def test_same_name_ships_are_not_picked_and_each_says_why_papers_cannot_settle_it():
    # TESTVSL0002: MRN의 입항 신고가 없어(서류로 확정하는 길이 닫힘) 같은 이름의 셋 가운데 고르지 못한다
    found = vessel.find_vessel(facts("TESTVSL0002"))
    assert found["status"] == "ask" and found["reason"] == "mrn_report_missing"
    assert [c["mmsi"] for c in found["candidates"]] == ["999000001", "999000002", "999000003"]
    assert "mmsi" not in found  # 고르지 않았다
    # 후보마다 서류로 맞춰 본 이유가 따라온다(선택 카드가 보인다). 상한은 고른 뒤 검사가 건다
    assert {c["check"] for c in found["candidates"]} == {"mrn_report_missing"}
    assert all("cap" not in c for c in found["candidates"])
    assert (found["lookup"], found["mrn_call_sign"]) == ("not_found", None)  # 고른 뒤 검사가 쓸 것


def test_papers_decide_between_two_ships_only_when_the_mrn_report_has_no_call_sign(monkeypatch):
    # TESTVSL0004: MRN의 입항 신고가 있고 호출부호가 없다. 서류(입항일 09-24, 적재항 QINGDAO)가 한 척에만
    #      맞는다
    hits = [VesselHit(mmsi=999000004, call_sign="QQTST4"), VesselHit(mmsi=999000005, call_sign="QQTST9")]
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: hits)
    found = vessel.find_vessel(facts("TESTVSL0004"))
    assert (found["status"], found["reason"], found["mmsi"]) == ("confirmed", "papers_match", "999000004")
    assert (found["basis"], found["cap"]) == (["entry_date", "loading_port"], "partial")


def test_one_ship_found_by_name_is_checked_against_its_own_sailing_report():
    # TESTVSL0004: 한 척이고 그 배의 입항 신고가 입항일과 적재항이 맞는다. 맞춰 본 칸은 둘이고 호출부호는
    #      아니다
    found = vessel.find_vessel(facts("TESTVSL0004"))
    assert (found["status"], found["reason"], found["basis"], found["cap"]) == (
        "confirmed",
        "papers_match",
        ["entry_date", "loading_port"],
        "partial",
    )
    # TESTVSL0005: 한 척인데 MRN이 없다. 이름이 닮았을 뿐이니 서류가 맞아도 확정하지 않고 되묻는다
    asked = vessel.find_vessel(facts("TESTVSL0005"))
    assert (asked["status"], asked["reason"]) == ("ask", "mrn_report_missing")
    assert [c["name"] for c in asked["candidates"]] == ["TEST CARGO E"]


def test_ships_sharing_a_call_sign_are_asked_and_a_pick_among_them_is_capped():
    found = vessel.find_vessel(facts("TESTVSL0007"))
    assert (found["status"], found["reason"]) == ("ask", "same_call_sign_many_mmsi")
    assert [(c["mmsi"], c["check"]) for c in found["candidates"]] == [
        ("999000007", "mrn_call_sign"),  # 그 후보 하나만 있다면 호출부호가 맞는다
        ("999000008", "mrn_call_sign"),
    ]
    assert (found["lookup"], found["mrn_call_sign"]) == ("found_signed", "QQTWN")


def test_a_failed_mrn_lookup_is_a_card_not_a_papers_confirmation(monkeypatch):
    broken = ToolError(code="too_many", message="입항 신고가 너무 많아요", retryable=False)
    monkeypatch.setattr(mof, "plans_near", lambda *a, **k: broken)
    found = vessel.find_vessel(facts("TESTVSL0004"))  # 서류는 맞지만 MRN으로 입항 신고를 받지 못했다
    assert (found["status"], found["reason"]) == ("ask", "mrn_lookup_failed")
    assert [c["check"] for c in found["candidates"]] == ["mrn_lookup_failed"]


def test_no_candidate_no_clue_and_failed_lookup_never_name_a_ship(monkeypatch):
    assert vessel.find_vessel(facts("TESTVSL0003")) == {"status": "none", "reason": "no_candidate"}
    from datetime import UTC, datetime

    bare = CargoFacts(number="TESTVSL0009", stage="입항", fetched_at=datetime.now(UTC))
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: pytest.fail("단서 없이 찾았다"))
    assert vessel.find_vessel(bare) == {"status": "unknown", "reason": "no_clue"}
    quota = ToolError(code="quota_exhausted", message="오늘 조회할 수 있는 횟수를 다 썼어요", retryable=False)
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: quota)
    # 클라이언트의 정한 오류 글을 그대로 싣는다: 한도 소진("내일")과 일시 실패("잠시 뒤")가 갈린다
    assert vessel.find_vessel(facts("TESTVSL0004")) == {
        "status": "unknown",
        "reason": "lookup_failed",
        "detail": "오늘 조회할 수 있는 횟수를 다 썼어요",
    }


def test_cargo_off_the_ship_is_not_looked_up_at_all(monkeypatch):
    for name in ("plans_near", "plans_for"):
        monkeypatch.setattr(mof, name, lambda *a, **k: pytest.fail("내린 화물인데 해수부를 불렀다"))
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: pytest.fail("내린 화물인데 찾았다"))
    assert vessel.find_vessel(facts("TESTVSL0006")) == {"status": "unknown", "reason": "landed"}


def test_too_many_candidates_are_asked_without_one_schedule_call_each(monkeypatch):
    many = [VesselHit(mmsi=999000010 + n, call_sign=f"QQMNY{n}", ship_name="TEST CARGO A") for n in range(7)]
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: many)
    monkeypatch.setattr(mof, "plans_for", lambda *a, **k: pytest.fail("후보 수 상한을 넘었는데 조회했다"))
    found = vessel.find_vessel(facts("TESTVSL0004"))  # 서류로 확정하는 길이 열린 화물
    assert found["status"] == "ask" and found["reason"] == "schedule_lookup_failed"
    assert len(found["candidates"]) == 5  # rules/vessel.yaml max_candidates


def test_the_call_budget_per_cargo_stops_before_the_limit_is_passed(monkeypatch):
    # 한 화물의 해수부·ShipFinder 요청 수는 rules의 상한을 넘지 않는다(쪽 넘김은 쪽 수 상한만큼 센다).
    # 닿으면 배를 지어내지 않고 조회 한도에 닿았다고 한다
    calls = []
    for name, module in (("plans_near", mof), ("plans_for", mof), ("vessel_candidates", shipfinder)):
        real = getattr(module, name)
        monkeypatch.setattr(module, name, lambda *a, _n=name, _r=real, **k: calls.append(_n) or _r(*a, **k))
    cfg = load_rules("vessel")
    vessel.find_vessel(facts("TESTVSL0002"))
    assert calls[0] == "plans_near" and calls.count("vessel_candidates") == 1
    monkeypatch.setitem(cfg, "max_find_calls", cfg["max_mrn_pages"])  # MRN 길만 쓰면 바닥이다
    calls.clear()
    assert vessel.find_vessel(facts("TESTVSL0002")) == {"status": "unknown", "reason": "call_limit"}
    assert calls == ["plans_near"]  # 배 검색은 부르지 않았다
    monkeypatch.setitem(cfg, "max_find_calls", cfg["max_mrn_pages"] - 1)
    calls.clear()
    assert vessel.find_vessel(facts("TESTVSL0002")) == {"status": "unknown", "reason": "call_limit"}
    assert calls == []  # MRN 길의 쪽 수도 못 쓰면 아무것도 부르지 않는다


def test_the_same_day_sailing_list_is_fetched_once_per_turn(monkeypatch):
    calls = []
    real = mof.plans_near
    monkeypatch.setattr(mof, "plans_near", lambda *a, **k: calls.append(1) or real(*a, **k))
    near: dict = {}
    for number in ("TESTVSL0001", "TESTVSL0002", "TESTVSL0004"):
        vessel.find_vessel(facts(number), near=near)
    assert len(calls) == 1  # 세 화물 모두 부산, 같은 입항일


def test_the_budget_numbers_add_up_and_leave_the_mrn_path_enough_pages_for_busan():
    cfg = load_rules("vessel")
    assert cfg["max_find_calls"] == cfg["max_mrn_pages"] + 1 + cfg["max_candidates"]
    assert cfg["max_find_calls"] + cfg["verdict_calls"] + cfg["pick_calls"] == cfg["max_calls"]
    # v1이 부산 5일치를 12쪽으로 쟀다. 창이 3일이면 약 7쪽이라 쪽 상한이 그보다 커야
    # MRN 길이 too_many로 끝나지 않는다
    window_days = 2 * load_rules("ports")["ports"]["KRPUS"]["mrn_search_days"] + 1
    assert cfg["max_mrn_pages"] >= -(-12 * window_days // 5)
