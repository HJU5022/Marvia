"""배 추적 기반을 재생 데이터로 한 줄에 이어 보는 시험 (계획 8a). 키·인터넷·DB·LLM 없이 돈다.

그래프는 아직 이 길을 부르지 않는다. 여기서는 조각들이 서로 맞물리는지만 본다:
화물 사실 → 항만 표 → MRN으로 배 찾기 → 후보 → 배 확정 → 위치와 입항 일정 → 판정 네 칸.
"""

from datetime import date, datetime, timedelta, timezone

from marvia.identify.models import CargoFacts
from marvia.tools.judge import judge
from marvia.tools.mof import plan_by_mrn, plans_near, port_schedule
from marvia.tools.ports import port
from marvia.tools.shipfinder import vessel_candidates, vessel_position
from marvia.tools.vessel import PortSchedule, Position
from marvia.tools.vessel_match import Candidate, match_vessel

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 22, 12, 0, tzinfo=KST)


def cargo(port_code: str | None = "KRPUS") -> CargoFacts:
    return CargoFacts(
        number="TEST0001",
        stage="입항적재화물목록 심사완료",
        mrn="26TEST0001I",
        port_code=port_code,
        entry_date=date(2026, 9, 24),
        loading_port="QINGDAO",
        vessel_name="TEST CARGO A",
        fetched_at=NOW,
    )


def test_replay_chain_from_cargo_facts_to_the_four_verdict_cells():
    facts = cargo()
    row = port(facts.port_code)
    assert row is not None and facts.entry_date is not None and facts.mrn is not None
    plans = plans_near(row, facts.entry_date)
    assert isinstance(plans, list)
    report = plan_by_mrn(plans, facts.mrn)
    assert report is not None and report.call_sign == "QQTST1"  # 배 이름이 아니라 MRN으로 찾았다
    hits = vessel_candidates(report.call_sign)
    assert isinstance(hits, list)
    found = match_vessel(
        facts, [Candidate(mmsi=h.mmsi, call_sign=h.call_sign) for h in hits], {}, report.call_sign
    )
    assert (found.status, found.mmsi, found.reason) == ("confirmed", 999000001, "single_candidate")
    assert found.mmsi is not None and found.call_sign is not None
    position = vessel_position(found.mmsi)
    schedule = port_schedule(row, found.call_sign, today=NOW.date())
    assert isinstance(position, Position) and isinstance(schedule, PortSchedule)
    verdict = judge(facts, position, schedule, now=NOW, sale_due=date(2026, 9, 28))
    assert (verdict.grade, verdict.confidence, verdict.schedule) == ("fine", "sure", "on_time")
    assert (verdict.eta_source, verdict.margin_days, verdict.notes) == ("mof_planned", 4, [])


def test_same_named_ships_without_an_mrn_match_are_asked_about_not_picked():
    hits = vessel_candidates("TEST CARGO A")
    assert isinstance(hits, list) and len(hits) == 3
    found = match_vessel(cargo(), [Candidate(mmsi=h.mmsi, call_sign=h.call_sign) for h in hits], {})
    assert (found.status, found.mmsi) == ("ask", None)  # 호출부호 없는 후보가 있어 서류로도 가르지 못한다


def test_a_port_outside_the_table_still_gets_a_verdict_with_lower_confidence():
    facts = cargo(port_code="JPOSA")
    assert port(facts.port_code) is None  # 해수부를 부를 청코드가 없다. 부산 청코드로 부르지 않는다
    position = vessel_position(999000001)
    assert isinstance(position, Position)
    verdict = judge(facts, position, None, now=NOW)
    assert verdict.confidence == "partial" and verdict.notes == ["port_not_in_table", "no_schedule", "no_eta"]
    # 배 신호의 목적지(KRPUS)가 이 화물의 양륙항(JPOSA)이 아니다. 목적지 바뀜은 켜지고 그 ETA는 쓰지 않는다.
    # 도착 시각을 알 출처가 없어도 올라간 등급(경계)은 그대로 낸다
    assert verdict.grade == "alert" and verdict.trusted_eta is None
