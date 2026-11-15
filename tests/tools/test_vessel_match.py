"""배 확정 시험 (계획 8a): 코드가 서류로 가르거나 되묻는다. LLM은 고르지 않는다. 값은 모두 가공값이다."""

from datetime import date, datetime, timedelta, timezone

from marvia.identify.models import CargoFacts
from marvia.tools.judge import judge
from marvia.tools.vessel import PortSchedule, Position, SailingPlan
from marvia.tools.vessel_match import Candidate, check_candidate, match_vessel

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 22, 12, 0, tzinfo=KST)
A = Candidate(mmsi=999000001, call_sign="QQTST1", flag="PA")
B = Candidate(mmsi=999000002, call_sign="QQTST2", flag="PA")


def cargo(**changes) -> CargoFacts:
    base = {
        "number": "TEST0001",
        "stage": "입항적재화물목록 심사완료",
        "port_code": "KRPUS",
        "entry_date": date(2026, 9, 24),
        "loading_port": "QINGDAO",
        "vessel_flag": "PA",
        "fetched_at": NOW,
    }
    return CargoFacts.model_validate({**base, **changes})


def plan(call_sign: str, day: int = 24, previous_port: str = "Qingdao", hour: int = 12) -> SailingPlan:
    arrival = datetime(2026, 9, day, hour, 0, tzinfo=KST)
    return SailingPlan(call_sign=call_sign, planned_arrival=arrival, previous_port=previous_port)


def result(*args, **kwargs) -> tuple[str, int | None, str]:
    # [왜] 서류 대조 시험은 MRN 조회가 성공했고 그 신고에 호출부호가 없는 경우(found_unsigned)를 기본으로
    #      한다.
    #      MRN 호출부호를 준 시험은 match_vessel이 found_signed로 읽는다
    if len(args) < 4 and "mrn_call_sign" not in kwargs:
        kwargs.setdefault("mrn_lookup", "found_unsigned")
    found = match_vessel(*args, **kwargs)
    return found.status, found.mmsi, found.reason


def test_no_candidate_is_none():
    assert result(cargo(), [], {}) == ("none", None, "no_candidate")


def test_one_candidate_is_never_confirmed_by_being_alone():
    # [왜] 11-13 판정. 이름이 같거나 비슷한 한 척은 근거가 아니다. 자동 확정은 (가) MRN 호출부호와 같음,
    #      (나) MRN 호출부호가 없을 때 그 배의 입항 신고에서 입항일과 적재항이 둘 다 맞음, 둘뿐이다
    assert result(cargo(), [A], {}) == ("ask", None, "schedule_lookup_failed")  # 입항 신고를 받지 못했다
    assert result(cargo(), [A], {"QQTST1": None}) == ("ask", None, "schedule_lookup_failed")
    assert result(cargo(), [A], {"QQTST1": []}) == ("ask", None, "papers_match_none")  # 신고가 없다
    assert result(cargo(entry_date=None), [A], {}) == ("ask", None, "no_papers")
    assert result(cargo(), [A.model_copy(update={"call_sign": None})], {}) == (
        "ask",
        None,
        "candidate_without_call_sign",
    )


def test_one_candidate_is_confirmed_by_the_mrn_call_sign_or_by_both_papers():
    found = match_vessel(cargo(), [A], {}, "qqtst 1")  # 글자까지 같다(공백과 대소문자는 가린다)
    assert (found.status, found.mmsi, found.reason, found.basis) == (
        "confirmed",
        999000001,
        "mrn_call_sign",
        ["call_sign"],
    )
    found = match_vessel(cargo(), [A], {"QQTST1": [plan("QQTST1")]}, mrn_lookup="found_unsigned")
    assert (found.status, found.reason, found.basis) == (
        "confirmed",
        "papers_match",
        ["entry_date", "loading_port"],
    )
    # 입항일이 하루 다르거나 직전 기항지가 다르면 맞는 칸이 없다
    assert result(cargo(), [A], {"QQTST1": [plan("QQTST1", day=25)]})[2] == "papers_match_none"
    assert (
        result(cargo(), [A], {"QQTST1": [plan("QQTST1", previous_port="NINGBO")]})[2] == "papers_match_none"
    )


def test_one_candidate_that_contradicts_the_papers_is_asked_not_confirmed():
    # [왜] 한 척뿐이어도 MRN 서류의 호출부호나 세관 국적과 어긋나면 남의 배일 수 있다 (v1 평가 문항 B07, B14)
    assert result(cargo(), [A], {}, mrn_call_sign="QQTST9") == ("ask", None, "mrn_call_sign_differs")
    assert result(cargo(vessel_flag="KR"), [A], {"QQTST1": [plan("QQTST1")]}) == ("ask", None, "flag_differs")
    # MRN 호출부호가 있는데 후보의 호출부호가 비어 있으면 확정하지 않는다
    nameless = A.model_copy(update={"call_sign": None})
    assert result(cargo(), [nameless], {}, mrn_call_sign="QQTST1") == (
        "ask",
        None,
        "candidate_without_call_sign",
    )
    # 국적을 모르면 어긋난다는 근거가 없다
    assert result(cargo(vessel_flag=None), [A], {}, mrn_call_sign="QQTST1")[0] == "confirmed"


def test_mrn_call_sign_picks_the_ship_among_same_named_ships():
    assert result(cargo(), [A, B], {}, mrn_call_sign="qqtst 2") == ("confirmed", 999000002, "mrn_call_sign")
    twin = B.model_copy(update={"mmsi": 999000003})
    assert result(cargo(), [A, B, twin], {}, mrn_call_sign="QQTST2") == (
        "ask",
        None,
        "same_call_sign_many_mmsi",
    )


def test_papers_confirm_only_when_exactly_one_ship_matches_both_conditions():
    plans = {"QQTST1": [plan("QQTST1")], "QQTST2": [plan("QQTST2", day=25)]}
    assert result(cargo(), [A, B], plans) == ("confirmed", 999000001, "papers_match")
    assert match_vessel(cargo(), [A, B], plans, mrn_lookup="found_unsigned").basis == [
        "entry_date",
        "loading_port",
    ]  # 호출부호는 맞춰 보지 않았다
    # 하루 차이는 같은 날이 아니다. 직전 기항지가 다른 항구여도 아니다
    assert result(cargo(), [A, B], {"QQTST1": [plan("QQTST1", day=25)], "QQTST2": []}) == (
        "ask",
        None,
        "papers_match_none",
    )
    other_port = {"QQTST1": [plan("QQTST1", previous_port="NINGBO")], "QQTST2": []}
    assert result(cargo(), [A, B], other_port)[2] == "papers_match_none"
    both = {"QQTST1": [plan("QQTST1")], "QQTST2": [plan("QQTST2")]}
    assert result(cargo(), [A, B], both) == ("ask", None, "papers_match_many")


def test_port_names_match_by_prefix_and_the_day_is_the_korean_day():
    assert result(
        cargo(loading_port="NINGBO"),
        [A, B],
        {"QQTST1": [plan("QQTST1", previous_port="Ningbo Pt")], "QQTST2": []},
    )[0] == ("confirmed")
    late = {"QQTST1": [plan("QQTST1", day=24, hour=23)], "QQTST2": []}
    assert result(cargo(), [A, B], late)[0] == "confirmed"  # 한국 시각 24일 23시는 24일이다


def test_anything_unchecked_means_ask():
    plans = {"QQTST1": [plan("QQTST1")], "QQTST2": []}
    assert result(cargo(entry_date=None), [A, B], plans) == ("ask", None, "no_papers")
    assert result(cargo(loading_port=None), [A, B], plans) == ("ask", None, "no_papers")
    nameless = B.model_copy(update={"call_sign": None})
    assert result(cargo(), [A, nameless], plans) == ("ask", None, "candidate_without_call_sign")
    assert result(cargo(), [A, B], {"QQTST1": [plan("QQTST1")], "QQTST2": None}) == (
        "ask",
        None,
        "schedule_lookup_failed",
    )
    assert result(cargo(), [A, B], {"QQTST1": [plan("QQTST1")]}) == ("ask", None, "schedule_lookup_failed")
    # 해수부가 다른 배의 신고를 돌려줘도 그 호출부호의 신고로 치지 않는다
    wrong = {"QQTST1": [plan("QQTST9")], "QQTST2": []}
    assert result(cargo(), [A, B], wrong)[2] == "papers_match_none"


def test_a_ship_of_another_flag_is_left_out_before_matching():
    korean = B.model_copy(update={"flag": "KR"})
    both = {"QQTST1": [plan("QQTST1")], "QQTST2": [plan("QQTST2")]}
    assert result(cargo(), [A, korean], both) == ("confirmed", 999000001, "papers_match")
    assert (
        result(cargo(), [A, B.model_copy(update={"flag": None})], both)[2] == "papers_match_many"
    )  # 모르면 빼지 않는다


def ship(**changes) -> Position:
    base = {
        "mmsi": 999000001,
        "lat": 33.0,
        "lng": 128.0,
        "sog": 12.0,
        "navstat": 0,
        "dest_code": "KRPUS",
        "ais_eta": datetime(2026, 9, 24, 12, 0, tzinfo=KST),
        "last_time": NOW - timedelta(minutes=30),
        "fetched_at": NOW,
    }
    return Position.model_validate({**base, **changes})


def schedule() -> PortSchedule:
    return PortSchedule(planned_arrival=datetime(2026, 9, 24, 12, 0, tzinfo=KST), fetched_at=NOW)


def test_papers_confirm_only_when_the_mrn_lookup_worked_and_its_report_has_no_call_sign():
    # [왜] 11-15 판정. 입항일과 적재항으로 확정하는 길은 MRN 조회가 성공했고 그 신고에 호출부호가 없을
    #      때만이다.
    #      MRN이 없거나 조회가 실패했거나(too_many, 모양 오류 포함) 그 MRN의 신고가 없으면 서류가 맞아도
    #      고르는 카드다
    plans = {"QQTST1": [plan("QQTST1")]}
    assert result(cargo(), [A], plans, mrn_lookup="found_unsigned") == (
        "confirmed",
        999000001,
        "papers_match",
    )
    assert result(cargo(), [A], plans, mrn_lookup="failed") == ("ask", None, "mrn_lookup_failed")
    assert result(cargo(), [A], plans, mrn_lookup="not_found") == ("ask", None, "mrn_report_missing")
    assert result(cargo(), [A], plans, mrn_lookup="none") == ("ask", None, "mrn_report_missing")
    both = {"QQTST1": [plan("QQTST1")], "QQTST2": [plan("QQTST2", day=25)]}
    assert result(cargo(), [A, B], both, mrn_lookup="found_unsigned") == (
        "confirmed",
        999000001,
        "papers_match",
    )
    assert result(cargo(), [A, B], both, mrn_lookup="failed") == ("ask", None, "mrn_lookup_failed")
    # MRN 호출부호가 있으면 서류로 가르지 않는다: 후보 가운데 같은 호출부호가 없으면 서류가 맞아도 묻는다
    assert result(cargo(), [A, B], both, "QQTST9") == ("ask", None, "mrn_call_sign_differs")
    blank = B.model_copy(update={"call_sign": None})
    assert result(cargo(), [A, blank], both, "QQTST9") == ("ask", None, "candidate_without_call_sign")


def test_ships_sharing_a_call_sign_are_never_confirmed_automatically():
    twin = A.model_copy(update={"mmsi": 999000009})
    assert result(cargo(), [A, twin], {}, "QQTST1") == ("ask", None, "same_call_sign_many_mmsi")
    plans = {"QQTST1": [plan("QQTST1")]}
    assert result(cargo(), [A, twin], plans, mrn_lookup="found_unsigned") == (
        "ask",
        None,
        "same_call_sign_many_mmsi",
    )


def test_a_confirmation_without_the_call_sign_check_carries_a_partial_cap():
    # [왜] 호출부호를 코드로 맞추지 못한 확정(서류만)은 확신이 부분을 넘지 못한다. 그 상한이 judge까지 닿는다
    papers = match_vessel(cargo(), [A], {"QQTST1": [plan("QQTST1")]}, mrn_lookup="found_unsigned")
    assert papers.status == "confirmed" and papers.cap == "partial"
    sign = match_vessel(cargo(), [A], {}, "QQTST1")
    assert sign.status == "confirmed" and sign.cap is None
    first = datetime(2026, 9, 24, 12, 0, tzinfo=KST)
    kw = {"now": NOW, "first_eta": first}
    clear = judge(cargo(), ship(), schedule(), cap=sign.cap, cap_note="ship_unchecked", **kw)
    assert (clear.confidence, "ship_unchecked" in clear.notes) == ("sure", False)
    capped = judge(cargo(), ship(), schedule(), cap=papers.cap, cap_note="ship_unchecked", **kw)
    assert (capped.grade, capped.confidence) == ("fine", "partial") and "ship_unchecked" in capped.notes


def test_a_pick_among_ships_sharing_a_call_sign_is_capped_even_though_the_call_sign_matches():
    # 사용자가 같은 호출부호의 두 배 가운데 하나를 골랐다. 호출부호는 맞지만 배를 가르지 못했으니 확신은
    #      부분이다
    twin = A.model_copy(update={"mmsi": 999000009})
    picked = check_candidate(cargo(), A, [A, twin], {}, "QQTST1", "found_signed")
    assert (picked.status, picked.mmsi, picked.reason, picked.cap) == (
        "confirmed",
        999000001,
        "same_call_sign_many_mmsi",
        "partial",
    )
    assert "call_sign" not in picked.basis
    alone = check_candidate(cargo(), A, [A, B], {}, "QQTST1", "found_signed")
    assert (alone.reason, alone.cap) == (
        "mrn_call_sign",
        None,
    )  # 같은 호출부호의 다른 배가 없으면 상한이 없다
    # 서류와 어긋나는 후보를 골라도 사용자의 선택은 받되, 어긋난 까닭을 이유로 달고 확신 상한을 건다
    differs = check_candidate(cargo(), B, [A, B], {}, "QQTST1", "found_signed")
    assert (differs.status, differs.mmsi, differs.reason, differs.cap, differs.basis) == (
        "confirmed",
        999000002,
        "mrn_call_sign_differs",
        "partial",
        [],
    )


def test_every_pick_not_matched_by_call_sign_is_capped_and_cannot_reach_sure_in_the_verdict():
    # [왜] 11-15 판정(R-126). 사용자가 고른 배는 호출부호를 코드로 맞추지 못했으면 늘 상한이 걸린다:
    #      MRN 없음, 조회 실패, 서류 불일치, 호출부호 다름, 같은 호출부호 여럿
    wrong_papers = {"QQTST1": [plan("QQTST1", day=27)]}
    picks = [
        check_candidate(cargo(), A, [A, B], {}, None, "none"),
        check_candidate(cargo(), A, [A, B], {}, None, "failed"),
        check_candidate(cargo(), A, [A, B], wrong_papers, None, "found_unsigned"),
        check_candidate(cargo(), B, [A, B], {}, "QQTST1", "found_signed"),
        check_candidate(
            cargo(), A, [A, A.model_copy(update={"mmsi": 999000009})], {}, "QQTST1", "found_signed"
        ),
    ]
    first = datetime(2026, 9, 24, 12, 0, tzinfo=KST)
    for pick in picks:
        assert pick.status == "confirmed" and pick.cap == "partial" and "call_sign" not in pick.basis
        seen = judge(
            cargo(), ship(), schedule(), now=NOW, first_eta=first, cap=pick.cap, cap_note="ship_unchecked"
        )
        assert seen.confidence != "sure" and "ship_unchecked" in seen.notes, pick.reason
