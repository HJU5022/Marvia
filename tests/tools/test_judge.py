"""판정 묶음 시험 (계획 8a): 화물 사실·배 위치·입항 일정 → 등급·확신·일정·단계. 값은 모두 가공값이다."""

from datetime import date, datetime, timedelta, timezone

from marvia.identify.models import CargoFacts
from marvia.tools.judge import Verdict, judge
from marvia.tools.rules import load_rules
from marvia.tools.signals import watches_ship
from marvia.tools.vessel import PortSchedule, Position, TrackPoint

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 22, 12, 0, tzinfo=KST)
PLANNED = datetime(2026, 9, 24, 12, 0, tzinfo=KST)


def cargo(
    stage: str = "입항적재화물목록 심사완료",
    port_code: str | None = "KRPUS",
    entry_date: date | None = date(2026, 9, 24),
) -> CargoFacts:
    return CargoFacts(
        number="TEST0001", stage=stage, port_code=port_code, entry_date=entry_date, fetched_at=NOW
    )


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
    verdict = judge(cargo(), ship(), plan(), now=NOW, sale_due=date(2026, 9, 28), first_eta=PLANNED)
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
    seen = judge(cargo(), both, plan(), now=NOW, first_eta=PLANNED)
    assert cells(seen) == ("alert", "sure", "concern")  # 주의 신호 둘


def test_input_error_signals_lower_confidence_not_grade():
    broken = ship(dest="XX QZQZZZZZ", dest_code=None)
    assert cells(judge(cargo(), broken, plan(), now=NOW, first_eta=PLANNED)) == ("fine", "partial", "on_time")
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
    ok = judge(cargo(), None, plan(), now=NOW, sale_due=date(2026, 9, 28), first_eta=PLANNED)
    assert cells(ok) == ("fine", "partial", "on_time") and ok.margin_days == 4
    # 포워더가 알려 준 날뿐이고 위치가 없으면 여유 일수를 세지 않는다. 판매 예정일과 견줄 수 없으니
    # 그 날이 판매 예정일 뒤든 앞이든 순항이라고도 정시라고도 하지 않는다 (11-13 덧붙임)
    for told_day in (date(2026, 9, 30), date(2026, 9, 20)):
        told = judge(cargo(), None, None, now=NOW, sale_due=date(2026, 9, 23), forwarder_eta=told_day)
        assert (told.eta_source, told.margin_days) == ("forwarder_eta", None)
        assert (told.grade, told.confidence, told.schedule) == (None, "unknown", None)
        assert told.notes == ["no_position", "no_schedule", "no_margin"]
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
    # 항만 표에 기간이 없는 항만은 해수부 신고를 쓰지 않는다(voyage_unchecked). 배 신호 ETA만으로 본다
    for code, name in (("JPOSA", "port_not_in_table"), ("KRINC", "port_unverified")):
        verdict = judge(cargo(port_code=code), ship(dest_code=code), plan(), now=NOW)
        assert verdict.confidence == "partial" and name in verdict.notes, code
        assert verdict.grade == "fine"  # 모르는 것으로 등급을 올리거나 내리지 않는다
        assert {"voyage_unchecked", name} <= set(verdict.notes) and verdict.eta_source == "ais_eta"
        assert name in notes  # 이유의 글은 rules/verdict.yaml에 있다
    nameless = judge(cargo(port_code=None), ship(dest_code=None), plan(), now=NOW)
    assert "port_unknown" in nameless.notes and nameless.grade is None  # 도착 시각을 알 출처가 없다
    assert judge(cargo(), ship(), plan(), now=NOW).notes == []


def test_without_a_sale_date_the_grade_comes_from_signals_and_says_so():
    # [왜] 판매 예정일을 주지 않은 질문은 견줄 날이 없다. 신호만으로 등급을 내고 그 사실을 참고 칸에 남긴다
    plain = judge(cargo(), ship(), plan(), now=NOW)
    assert cells(plain) == ("fine", "sure", None) and plain.margin_days is None
    assert plain.info == ["no_sale_date", "no_first_eta"] and plain.notes == []
    dated = judge(cargo(), ship(), plan(), now=NOW, sale_due=date(2026, 9, 28))
    assert dated.info == ["no_first_eta"] and dated.margin_days == 4
    # 판매 예정일이 없고 포워더 날짜뿐이어도 신호만으로 낸 등급은 그대로다(견줄 날이 없다)
    told = judge(cargo(), None, None, now=NOW, forwarder_eta=date(2026, 9, 30))
    assert (told.grade, told.info) == ("fine", ["no_sale_date", "no_first_eta"])
    rules = load_rules("verdict")
    assert "no_margin" in rules["notes"] and "no_sale_date" in rules["info"]


def test_a_raised_grade_survives_a_missing_margin():
    held = judge(
        cargo("검사지정"), None, None, now=NOW, sale_due=date(2026, 9, 23), forwarder_eta=date(2026, 9, 30)
    )
    assert (held.grade, held.schedule, held.margin_days) == ("act", None, None) and "no_margin" in held.notes


def test_schedule_cell_is_empty_without_a_first_known_eta_except_overdue():
    # [왜] 11-13 판정. 처음 알던 도착 예정이 없으면 "지연"이 나올 수 없다. 그 상태의 "정시"는 틀린 인상이다.
    #      정시·우려·지연은 견줄 처음 예정이 있을 때만 낸다. "초과"는 판매 예정일로 내므로 그대로다
    late_signal = ship(ais_eta=PLANNED + timedelta(hours=20))  # ETA 어긋남: 우려를 만드는 신호
    bare = judge(cargo(), late_signal, plan(), now=NOW)
    assert bare.schedule is None and "no_first_eta" in bare.info and bare.grade == "watch"  # 등급은 그대로
    assert judge(cargo(), late_signal, plan(), now=NOW, first_eta=PLANNED).schedule == "concern"
    known = judge(cargo(), ship(), plan(), now=NOW, first_eta=PLANNED)
    assert known.schedule == "on_time" and "no_first_eta" not in known.info
    over = judge(cargo(), ship(), plan(), now=NOW, sale_due=date(2026, 9, 23))
    assert over.schedule == "overdue" and over.info == ["no_first_eta"]
    assert "no_first_eta" in load_rules("verdict")["info"]


def test_an_arrived_ship_is_not_marked_down_for_having_no_planned_arrival_to_compare():
    # [왜] 11-13 판정. 입항이 끝난 배에 "입항 예정과 견주지 못함"으로 확신을 깎지 않는다.
    #      믿을 ETA의 출처가 실제 입항(관제 실적, 최종 입항 신고)이면 ETA 어긋남 신호는 꺼짐이다
    docked = ship(ais_eta=NOW - timedelta(hours=2))  # 지난 배 신호 ETA. 입항 예정은 없고 관제 실적이 있다
    arrived = plan(planned=None, actual=NOW - timedelta(hours=1))
    seen = judge(cargo(entry_date=date(2026, 9, 22)), docked, arrived, now=NOW)
    state = {s.id: s.state for s in seen.signals}
    assert seen.eta_source == "mof_actual" and state["eta_conflict"] == "clear" and seen.confidence == "sure"
    # 위치가 없어도 확신이 내려가지 않는다: 입항한 배는 배 신호를 보지 않는다(11-15). 위치가 없다는 사실은
    #      참고 글로 남는다
    blind = judge(cargo(entry_date=date(2026, 9, 22)), None, arrived, now=NOW)
    assert {s.id: s.state for s in blind.signals}["eta_conflict"] == "clear" and blind.confidence == "sure"
    assert "no_position" not in blind.notes and "no_schedule" not in blind.notes and "arrived" in blind.info
    # 입항 전이면 지금까지와 같다: 입항 예정이 없으면 모름
    before = judge(cargo(), ship(), plan(planned=None), now=NOW)
    assert {s.id: s.state for s in before.signals}["eta_conflict"] == "unknown"
    assert load_rules("verdict")["arrived_sources"] == ["mof_actual", "mof_final"]


def test_a_cargo_already_off_the_ship_is_judged_by_customs_only():
    # [왜] 11-13 판정. 배 신호는 화물이 배에 실려 있는 동안에만 판정에 쓴다. 내린 뒤에는 배가 다음 항구로
    #      떠나는 것이 정상이다. 그 배의 목적지·위치·ETA로 등급을 올리면 멀쩡한 화물이 "경계"가 된다
    gone = ship(dest="OSAKA", dest_code="JPOSA", last_time=NOW - timedelta(hours=30))  # 떠난 배, 위치도 끊김
    for stage in ("반입신고", "수입신고", "수입(사용소비) 심사진행", "수입신고 수리", "반출신고", "반출완료"):
        seen = judge(cargo(stage), gone, plan(), now=NOW, sale_due=date(2026, 9, 23), first_eta=PLANNED)
        assert cells(seen) == ("fine", "sure", None), stage
        assert {s.id for s in seen.signals if s.state != "clear"} == set(), stage
        assert (seen.trusted_eta, seen.eta_source, seen.margin_days, seen.notes) == (None, None, None, []), (
            stage
        )
        assert seen.info == ["landed"], stage
    # 배에 실려 있는 단계는 지금까지와 같다: 같은 배 신호로 경계다
    for stage in load_rules("verdict")["signals"]["ship_stages"]:
        assert judge(cargo(stage), gone, plan(), now=NOW).grade == "alert", stage
    # 통관이 멈춘 단계와 모르는 단계는 "내린 화물"로 보지 않는다. 배 신호를 싣고 모르는 단계는 확신이 내린다
    held = judge(cargo("검사지정"), gone, plan(), now=NOW)
    assert held.grade == "act" and "landed" not in held.info
    odd = judge(cargo("TEST 낯선 단계"), gone, plan(), now=NOW)
    assert (odd.grade, odd.confidence) == ("alert", "partial") and "landed" not in odd.info


def test_ship_stages_are_known_stages_and_the_rest_of_the_known_ones_are_landed():
    cuts = load_rules("verdict")["signals"]
    assert set(cuts["ship_stages"]) < set(cuts["known_stages"])
    assert set(cuts["known_stages"]) - set(cuts["ship_stages"]) == {
        "반입신고",
        "수입신고",
        "수입(사용소비) 심사진행",
        "수입신고수리",
        "반출신고",
        "반출완료",
    }
    assert (
        watches_ship("입항")
        and watches_ship("검사지정")
        and watches_ship("TEST 낯선 단계")
        and watches_ship(None)
    )
    assert not watches_ship("반입신고") and not watches_ship("수입신고 수리")  # 띄어쓰기만 다른 이름도 같다
    assert "landed" in load_rules("verdict")["info"]


def test_a_report_of_another_voyage_is_never_this_cargos_arrival():
    # [왜] 11-15 판정. 같은 배의 지난 항차 입항 예정(-2일)이 믿을 ETA로 들어오면 등급이 좋아진다(경계가
    #      주의가 된다).
    #      해수부 신고(실적, 최종, 예정)는 화물의 세관 입항일 앞뒤 며칠(rules/ports.yaml voyage_window_days)
    #      안의
    #      것만 이 항차의 것으로 쓴다
    old = datetime(2026, 9, 22, 8, 0, tzinfo=KST)  # 세관 입항일(09-24)보다 이틀 앞
    for position in (ship(ais_eta=None), None):
        seen = judge(cargo(), position, plan(planned=old), now=NOW, sale_due=date(2026, 9, 28))
        assert (seen.trusted_eta, seen.eta_source) == (None, None), position
        assert seen.grade != "fine" and "other_voyage" in seen.notes, position
        assert "no_eta" in seen.notes and seen.confidence != "sure"
    # 같은 입력이 이번 항차의 값이면(세관 입항일 앞뒤 하루 안) 쓴다
    mine = judge(cargo(), ship(ais_eta=None), plan(planned=PLANNED + timedelta(days=1)), now=NOW)
    assert mine.eta_source == "mof_planned" and "other_voyage" not in mine.notes
    edge = judge(cargo(), None, plan(planned=PLANNED - timedelta(days=1)), now=NOW)  # 앞뒤 하루는 경계 안
    assert edge.eta_source == "mof_planned"
    out = judge(
        cargo(), None, plan(planned=PLANNED - timedelta(days=1, hours=13)), now=NOW
    )  # 한국 날짜로 이틀 앞
    assert out.eta_source is None and "other_voyage" in out.notes
    # 실적과 최종 신고도 같은 가드를 지난다
    for field in ("actual", "final"):
        schedule = PortSchedule(**{f"{field}_arrival": old}, fetched_at=NOW)
        seen = judge(cargo(), ship(ais_eta=None), schedule, now=NOW, sale_due=date(2026, 9, 28))
        assert seen.eta_source is None and "other_voyage" in seen.notes, field


def test_without_a_customs_entry_date_no_ministry_report_is_used_and_the_confidence_drops():
    # 세관 입항일이 없으면 어느 줄도 입항 시각으로 쓰지 않는다(여러 줄 가운데 고르지도 않는다). 이유를 적고
    #      확신을 낮춘다
    for schedule in (plan(), plan(planned=None, actual=NOW - timedelta(hours=1))):
        seen = judge(
            cargo(entry_date=None), ship(ais_eta=None), schedule, now=NOW, sale_due=date(2026, 9, 28)
        )
        assert seen.eta_source is None and "no_entry_date" in seen.notes
        assert seen.confidence != "sure" and seen.grade != "fine"
    # 배 신호의 ETA는 해수부 신고가 아니라 이 가드를 받지 않는다
    ais = judge(cargo(entry_date=None), ship(), plan(), now=NOW)
    assert ais.eta_source == "ais_eta" and "no_entry_date" in ais.notes and ais.confidence == "partial"
    # 해수부 신고가 없으면 가드가 말할 것이 없다
    quiet = judge(cargo(entry_date=None), ship(), None, now=NOW)
    assert "no_entry_date" not in quiet.notes
    # 항만 표에 항차 기간이 없는 항만은 신고를 쓰지 않는다
    unknown = judge(cargo(port_code="KRINC"), ship(dest_code="KRINC", ais_eta=None), plan(), now=NOW)
    assert unknown.eta_source is None and "voyage_unchecked" in unknown.notes
    for name in ("no_entry_date", "other_voyage", "voyage_unchecked"):
        assert name in load_rules("verdict")["notes"]


def test_once_the_ship_has_really_arrived_its_signals_are_not_read_any_more():
    # [왜] 11-15 판정. 이 항차의 실제 입항(관제 실적, 최종 신고)이 믿을 ETA의 출처면 그 배는 도착했다.
    #      그 뒤 다음 항구로 떠나거나 부두에 오래 서 있는 것은 이 화물의 위험이 아니다. 배 신호 다섯(목적지,
    #      항구 앞 정지, ETA 어긋남, 위치 끊김, 항해 상태)은 모두 해당 없음이고 통관 단계와 통관 멈춤만 본다
    here = date(2026, 9, 22)
    arrived = plan(planned=None, actual=NOW - timedelta(hours=1))
    gone = ship(dest="OSAKA", dest_code="JPOSA", last_time=NOW - timedelta(hours=30), navstat=5, sog=9.0)
    for stage in ("입항", "하선신고 수리"):
        seen = judge(cargo(stage, entry_date=here), gone, arrived, now=NOW, sale_due=date(2026, 9, 28))
        assert seen.eta_source == "mof_actual" and seen.grade == "fine" and seen.confidence == "sure", stage
        states = {s.id: s.state for s in seen.signals}
        assert set(states.values()) == {"clear"}, (stage, states)
    # 관제 실적이 아니라 최종 입항 신고여도 같다
    final = PortSchedule(final_arrival=NOW - timedelta(hours=1), fetched_at=NOW)
    assert judge(cargo(entry_date=here), gone, final, now=NOW).grade == "fine"
    # 배 위치가 없어도 확신이 내려가지 않는다(배 신호를 보지 않으니 모름이 없다). 위치가 없다는 사실은
    #      확신을 낮춘 이유가 아니라서 notes에 두지 않는다
    blind = judge(cargo(entry_date=here), None, arrived, now=NOW)
    assert blind.confidence == "sure" and blind.notes == [] and "arrived" in blind.info
    # [왜] notes는 확신을 낮춘 이유다. 낮추지 않았으니 위치가 없다는 말은 참고 글로 적는다
    assert "arrived" in load_rules("verdict")["info"]
    # 통관이 멈춘 단계는 입항 뒤에도 긴급이다
    held = judge(cargo("검사지정", entry_date=here), gone, arrived, now=NOW)
    assert held.grade == "act"
    # 입항 전(실적 없음)에 항구 앞 묘박지에서 오래 서 있는 배는 그대로 켜진다
    anchored = judge(
        cargo(entry_date=here),
        ship(lat=35.0, lng=129.1, sog=0.0, navstat=1),
        plan(planned=NOW + timedelta(hours=6)),
        now=NOW,
        history=[TrackPoint(at=NOW - timedelta(hours=30), lat=35.0, lng=129.1, sog=0.0)],
    )
    assert {s.id: s.state for s in anchored.signals}[
        "anchor_wait"
    ] == "triggered" and anchored.grade == "alert"


def test_a_future_arrival_is_not_an_arrival():
    # [왜] 11-15 판정(R-127). 실적이나 최종 신고의 시각이 지금보다 허용 오차 넘게 뒤면 입항한 것이 아니다.
    #      입항 예정과 같은 경계다: 출처가 아니고 배 신호를 읽는다
    here = date(2026, 9, 23)
    anchored = ship(lat=35.1, lng=129.05, sog=0.0, navstat=5, ais_eta=None)
    history = [TrackPoint(at=NOW - timedelta(hours=30), lat=35.1, lng=129.05, sog=0.0)]
    tomorrow = PortSchedule(final_arrival=NOW + timedelta(hours=24), fetched_at=NOW)
    seen = judge(
        cargo(entry_date=here), anchored, tomorrow, now=NOW, sale_due=date(2026, 9, 28), history=history
    )
    assert seen.eta_source is None and seen.grade == "alert" and "arrived" not in seen.info
    soon = PortSchedule(final_arrival=NOW + timedelta(minutes=5), fetched_at=NOW)
    assert judge(cargo(entry_date=here), anchored, soon, now=NOW).eta_source == "mof_final"


def test_a_ship_signal_that_contradicts_the_arrival_report_keeps_the_ship_signals_on(monkeypatch):
    # [왜] 11-15 판정(R-128). 입항 신고가 있어도 새 배 신호가 이 항만행이고 ETA가 입항 시각보다 12시간 넘게
    #      뒤면 두 출처가 어긋난 것이다. 입항으로 치지 않고 ETA 어긋남을 켜며 확신은 부분이다
    here = date(2026, 9, 22)
    report = PortSchedule(final_arrival=NOW - timedelta(hours=5), fetched_at=NOW)
    far = ship(lat=32.4, lng=129.05, ais_eta=NOW + timedelta(hours=24))
    seen = judge(cargo(entry_date=here), far, report, now=NOW, sale_due=date(2026, 9, 28))
    states = {s.id: s.state for s in seen.signals}
    assert states["eta_conflict"] == "triggered" and seen.confidence == "partial" and seen.grade != "fine"
    assert "arrived" not in seen.info
    # [왜] 11-16 판정(R-129). 어긋나면 믿을 ETA는 늦은 쪽(배 신호 ETA)이고 여유 일수도 그 값으로 센다
    assert seen.eta_source == "ais_eta" and seen.margin_days == 5
    # 배 신호가 입항 시각과 맞으면 입항으로 본다
    near = ship(lat=32.4, lng=129.05, ais_eta=NOW - timedelta(hours=4))
    assert "arrived" in judge(cargo(entry_date=here), near, report, now=NOW).info
    # 배 신호가 오래됐거나 다른 항구행이면 어긋남으로 보지 않는다
    stale = ship(ais_eta=NOW + timedelta(hours=24), last_time=NOW - timedelta(hours=9))
    assert "arrived" in judge(cargo(entry_date=here), stale, report, now=NOW).info
    gone = ship(ais_eta=NOW + timedelta(hours=24), dest="OSAKA", dest_code="JPOSA")
    assert "arrived" in judge(cargo(entry_date=here), gone, report, now=NOW).info
    # [왜] 11-15 판정. 배가 항만 기준점 반경 안(실제로 항구에 있음)이면 ETA를 고치지 않은 것이라 두 출처가
    #      맞는 것으로 본다. 반경 밖이거나 거리를 볼 수 없는 항만이면 어긋남이다
    docked = ship(lat=35.1, lng=129.05, sog=0.0, navstat=5, ais_eta=NOW + timedelta(hours=24))
    assert "arrived" in judge(cargo(entry_date=here), docked, report, now=NOW).info
    from marvia.tools import judge as judge_module

    real = judge_module.port
    monkeypatch.setattr(
        judge_module,
        "port",
        lambda code: (row := real(code)) and row.model_copy(update={"ref": None, "stop_radius_nm": None}),
    )
    blind = judge(cargo(entry_date=here), docked, report, now=NOW)
    assert "arrived" not in blind.info and "arrival_report_differs" in blind.notes


def test_only_the_voyage_guard_keeps_the_final_report_of_an_earlier_voyage_out():
    # [왜] 검증 N1. 지난 항차의 최종 신고는 이미 지난 시각이라 "지난 예정 거르기"에 걸리지 않는다.
    #      항차 가드만이 이것을 막는다
    old = PortSchedule(final_arrival=datetime(2026, 9, 22, 8, 0, tzinfo=KST), fetched_at=NOW)
    seen = judge(
        cargo(entry_date=date(2026, 9, 24)), ship(ais_eta=None), old, now=NOW, sale_due=date(2026, 9, 28)
    )
    assert seen.eta_source is None and seen.grade is None and "other_voyage" in seen.notes


def test_a_conflicting_arrival_report_never_makes_the_grade_better_than_having_no_report():
    # [왜] 11-16 판정(R-129). 신고와 배 신호가 어긋나면 늦은 쪽을 믿는다. 신고가 있다고 신고가 없을 때보다
    #      등급이 좋아지면 안 된다
    here, due = date(2026, 9, 22), date(2026, 9, 28)
    morning = datetime(2026, 9, 22, 9, 0, tzinfo=KST)
    far = ship(lat=32.4, lng=129.05, ais_eta=datetime(2026, 9, 23, 8, 0, tzinfo=KST))
    with_report = judge(
        cargo(entry_date=here),
        far,
        PortSchedule(final_arrival=morning, fetched_at=NOW),
        now=NOW,
        sale_due=due,
    )
    without = judge(cargo(entry_date=here), far, None, now=NOW, sale_due=due)
    order = ["fine", "watch", "alert", "act"]
    assert order.index(with_report.grade or "fine") >= order.index(without.grade or "fine")
    assert with_report.eta_source == "ais_eta" and with_report.margin_days == without.margin_days == 5


def test_a_ship_inside_the_radius_counts_as_at_the_port_only_when_it_is_stopped(monkeypatch):
    # [왜] 11-16 판정(N7, N5). 반경 안이어도 움직이면 항구에 선 것이 아니다. 거리가 반경과 같으면 안이다
    #      (항구 앞 정지 신호와 같은 뜻). 멈춤은 stop_speed_kn 이하다
    here = date(2026, 9, 22)
    report = PortSchedule(final_arrival=NOW - timedelta(hours=5), fetched_at=NOW)
    late = NOW + timedelta(hours=24)

    def seen(lat: float, sog: float) -> Verdict:
        return judge(
            cargo(entry_date=here), ship(lat=lat, lng=129.05, sog=sog, ais_eta=late), report, now=NOW
        )

    assert "arrived" in seen(34.7, 0.5).info  # 24해리, 0.5노트(멈춤 기준과 같음)는 멈춘 것
    moving = seen(34.7, 14.0)
    assert "arrived" not in moving.info and "arrival_report_differs" in moving.notes
    assert "arrived" in seen(34.6, 0.0).info  # 30.0해리: 반경과 같으면 안
    assert "arrival_report_differs" in seen(34.5985, 0.0).notes  # 30.1해리: 밖
