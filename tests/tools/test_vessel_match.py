"""배 확정 시험 (계획 8a): 코드가 서류로 가르거나 되묻는다. LLM은 고르지 않는다. 값은 모두 가공값이다."""

from datetime import date, datetime, timedelta, timezone

from marvia.identify.models import CargoFacts
from marvia.tools.vessel import SailingPlan
from marvia.tools.vessel_match import Candidate, match_vessel

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
    found = match_vessel(cargo(), [A], {"QQTST1": [plan("QQTST1")]})
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
    assert match_vessel(cargo(), [A, B], plans).basis == [
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
