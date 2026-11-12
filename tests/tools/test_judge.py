"""판정 묶음 시험 (계획 8a): 화물 사실·배 위치·입항 일정 → 등급·확신·일정·단계. 값은 모두 가공값이다."""

from datetime import date, datetime, timedelta, timezone

from marvia.identify.models import CargoFacts
from marvia.tools.judge import Verdict, judge
from marvia.tools.rules import load_rules
from marvia.tools.vessel import PortSchedule, Position

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 22, 12, 0, tzinfo=KST)
PLANNED = datetime(2026, 9, 24, 12, 0, tzinfo=KST)


def cargo(stage: str = "입항적재화물목록 심사완료", port_code: str | None = "KRPUS") -> CargoFacts:
    return CargoFacts(number="TEST0001", stage=stage, port_code=port_code, fetched_at=NOW)


def ship(**changes) -> Position:
    base = {
        "mmsi": 999000001,
        "lat": 33.0,
        "lng": 128.0,
        "sog": 12.0,
        "navstat": 0,
        "dest_code": "KRPUS",
        "ais_eta": PLANNED,
        "last_time": NOW - timedelta(minutes=30),
        "fetched_at": NOW,
    }
    return Position.model_validate({**base, **changes})


def plan(planned: datetime | None = PLANNED, actual: datetime | None = None) -> PortSchedule:
    return PortSchedule(planned_arrival=planned, actual_arrival=actual, fetched_at=NOW)


def cells(verdict: Verdict) -> tuple[str | None, str, str | None]:
    return verdict.grade, verdict.confidence, verdict.schedule


def test_all_known_and_clear_is_fine_sure_on_time():
    verdict = judge(cargo(), ship(), plan(), now=NOW, sale_due=date(2026, 9, 28))
    assert cells(verdict) == ("fine", "sure", "on_time")
    assert (verdict.stage, verdict.eta_source, verdict.margin_days) == (
        "입항적재화물목록 심사완료",
        "mof_planned",
        4,
    )
    assert verdict.trusted_eta == PLANNED and verdict.notes == []
    assert [s.id for s in verdict.signals] == load_rules("verdict")["signal_ids"]


def test_grade_comes_from_signals_and_margin_only():
    assert cells(judge(cargo("검사지정"), ship(), plan(), now=NOW))[0] == "act"
    assert cells(judge(cargo(), ship(), plan(), now=NOW, sale_due=date(2026, 9, 23))) == (
        "act",
        "sure",
        "overdue",
    )
    assert (
        cells(judge(cargo(), ship(), plan(), now=NOW, sale_due=date(2026, 9, 25)))[0] == "alert"
    )  # 여유 1일
    stale = ship(last_time=NOW - timedelta(hours=7))
    assert cells(judge(cargo(), stale, plan(), now=NOW))[0] == "watch"
    both = stale.model_copy(update={"ais_eta": PLANNED + timedelta(hours=20)})
    assert cells(judge(cargo(), both, plan(), now=NOW)) == ("alert", "sure", "concern")  # 주의 신호 둘


def test_input_error_signals_lower_confidence_not_grade():
    broken = ship(dest="XX QZQZZZZZ", dest_code=None)
    assert cells(judge(cargo(), broken, plan(), now=NOW)) == ("fine", "partial", "on_time")
    odd = ship(navstat=1, sog=3.0)
    assert cells(judge(cargo(), odd, plan(), now=NOW))[:2] == ("fine", "partial")


def test_a_later_eta_than_first_known_is_delayed():
    first = PLANNED - timedelta(days=1)
    assert judge(cargo(), ship(), plan(), now=NOW, first_eta=first).schedule == "delayed"
    assert (
        judge(cargo(), ship(), plan(), now=NOW, first_eta=PLANNED - timedelta(hours=23)).schedule == "on_time"
    )


def test_less_data_never_makes_the_grade_better():
    # 위치가 없어도 해수부 입항 예정이 있으면 그 시각으로 여유 일수를 센다. 판매 예정일을 넘기면 긴급이다
    late = judge(cargo(), None, plan(), now=NOW, sale_due=date(2026, 9, 23))
    assert (late.margin_days, late.eta_source) == (-1, "mof_planned")
    assert cells(late) == ("act", "partial", "overdue") and late.notes == ["no_position"]
    ok = judge(cargo(), None, plan(), now=NOW, sale_due=date(2026, 9, 28))
    assert cells(ok) == ("fine", "partial", "on_time") and ok.margin_days == 4
    # 포워더가 알려 준 날뿐이고 위치가 없으면 여유 일수를 세지 않는다. 믿을 ETA는 있으니 등급은 낸다
    told = judge(cargo(), None, None, now=NOW, sale_due=date(2026, 9, 23), forwarder_eta=date(2026, 9, 30))
    assert (told.eta_source, told.margin_days, told.grade) == ("forwarder_eta", None, "fine")
    # 위치가 있으면 배 신호 ETA로도 센다
    seen = judge(cargo(), ship(), None, now=NOW, sale_due=date(2026, 9, 23))
    assert (seen.eta_source, seen.margin_days, seen.grade) == ("ais_eta", -1, "act")


def test_no_eta_source_means_no_grade_but_a_raised_grade_is_kept():
    # [왜] 도착 시각을 알 출처가 없는데 "순항"이라고 하면 자료가 없는 화물이 가장 좋아 보인다
    blank = judge(cargo(), None, None, now=NOW, sale_due=date(2026, 9, 23))
    assert (blank.grade, blank.confidence, blank.schedule) == (None, "unknown", None)
    assert blank.notes == ["no_position", "no_schedule", "no_eta"] and blank.trusted_eta is None
    nothing = judge(None, None, None, now=NOW)
    assert (nothing.grade, nothing.confidence, nothing.schedule) == (None, "unknown", None)
    # 통관이 멈춘 화물은 도착 시각을 몰라도 긴급이다. 올라간 등급을 비우지 않는다
    held = judge(cargo("검사지정"), None, None, now=NOW)
    assert (held.grade, held.confidence, held.schedule) == ("act", "partial", None) and "no_eta" in held.notes
    assert "no_eta" in load_rules("verdict")["notes"]


def test_port_that_is_missing_or_unverified_lowers_confidence_and_says_why():
    notes = load_rules("verdict")["notes"]
    for code, name in ((None, "port_unknown"), ("JPOSA", "port_not_in_table"), ("KRINC", "port_unverified")):
        verdict = judge(cargo(port_code=code), ship(dest_code=code), plan(), now=NOW)
        assert verdict.confidence == "partial" and name in verdict.notes, code
        assert verdict.grade == "fine"  # 모르는 것으로 등급을 올리거나 내리지 않는다
        assert name in notes  # 이유의 글은 rules/verdict.yaml에 있다
    assert judge(cargo(), ship(), plan(), now=NOW).notes == []
