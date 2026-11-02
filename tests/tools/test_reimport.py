from datetime import date
from typing import get_args

from marvia.tools.reimport import Category, Flag, ItemFacts, SameField, reimport_check
from marvia.tools.rules import load_rules

TODAY = date(2026, 11, 2)
CHILI = ["생산국", "품명", "수출업소", "포장장소"]  # 농산물·임산물의 같아야 할 칸


def facts(**changes) -> ItemFacts:
    """건고추를 5년 안에 다시 들여오고 조건을 모두 채운 사실. 바꿀 칸만 넘긴다."""
    base = {
        "category": "농산물·임산물",
        "same": CHILI,
        "different": [],
        "prior_precise": "받음",
        "prior_result": "적합",
        "prior_cert_on": date(2026, 3, 10),
        "flags": [],
    }
    return ItemFacts(**(base | changes))


def test_all_conditions_met_is_document_check():
    result = reimport_check(facts(), TODAY)
    assert result.verdict == "서류검사 요건 충족"
    assert result.failed == [] and result.missing == []
    assert result.window_end == date(2031, 3, 10)
    assert result.basis == ["시행규칙 별표 9 제2호가목7)", "시행규칙 별표 10 제4호다목"]
    # [왜] 확인하지 않은 정밀검사 사유와 재량 검사는 단정 대신 단서로 남긴다
    assert any("반송품" in c for c in result.caveats)
    assert any("무작위표본검사" in c for c in result.caveats)


def test_never_says_exempt():
    assert "면제" not in reimport_check(facts(), TODAY).model_dump_json()


def test_different_field_means_precise_check():
    utensil = facts(
        category="기구·용기·포장", same=["제조국", "해외제조업소", "바탕색상"], different=["재질"]
    )
    result = reimport_check(utensil, TODAY)
    assert result.verdict == "정밀검사 대상"
    assert result.failed == ["재질 다름"]


def test_unknown_facts_are_missing():
    result = reimport_check(facts(same=["생산국"], prior_precise="모름", prior_cert_on=None), TODAY)
    assert result.verdict == "사실 부족"
    assert result.missing == [
        "품명 같은지",
        "수출업소 같은지",
        "포장장소 같은지",
        "이전 정밀검사를 받았는지",
        "이전 정밀검사 뒤 수입신고확인증 발급일",
    ]


def test_forced_reason_means_precise_check():
    result = reimport_check(facts(flags=["특별관리 영업자"]), TODAY)
    assert result.verdict == "정밀검사 대상"
    assert result.failed == ["특별관리 영업자 (시행규칙 별표 10 제3호가목)"]
    assert "시행규칙 별표 10 제3호가목" in result.basis


def test_same_flag_twice_counts_once():
    result = reimport_check(facts(flags=["특별관리 영업자", "특별관리 영업자"]), TODAY)
    assert result.failed == ["특별관리 영업자 (시행규칙 별표 10 제3호가목)"]


def test_returned_goods_flag_keeps_document_check_exception():
    # [왜] 별표 10 제1호나목은 별표 9 제2호가목12)의 서류검사 반송품
    #      (재가공 수출용, 변질·위해 아닌 반송)을 뺀다
    result = reimport_check(facts(flags=["정밀검사 대상 반송품"]), TODAY)
    assert result.verdict == "정밀검사 대상"
    assert "별표 9 제2호가목12)" in result.failed[0]


def test_prior_failure_means_precise_check():
    result = reimport_check(facts(prior_result="부적합"), TODAY)
    assert result.verdict == "정밀검사 대상"
    assert result.failed == ["이전 정밀검사 부적합 (시행규칙 별표 10 제2호나목)"]


def test_window_passed_means_precise_check():
    result = reimport_check(facts(prior_cert_on=date(2021, 10, 30)), TODAY)
    assert result.verdict == "정밀검사 대상"
    assert result.window_end == date(2026, 10, 30)  # 금요일
    assert result.failed == ["5년 지남 (2026-10-30까지)"]


def test_window_ending_on_weekend_moves_to_monday():
    # 민법 제161조: 끝날 2026-10-31이 토요일이라 다음 쉬지 않는 날(11-02 월)에 끝난다
    result = reimport_check(facts(prior_cert_on=date(2021, 10, 31)), TODAY)
    assert result.window_end == date(2026, 11, 2)
    assert result.verdict == "서류검사 요건 충족"


def test_future_cert_date_is_asked_again():
    # [왜] 발급일이 오늘보다 뒤일 수는 없다. 연도를 잘못 읽었을 수 있어 판정에 쓰지 않고 다시 묻는다
    result = reimport_check(facts(prior_cert_on=date(2027, 1, 1)), TODAY)
    assert result.verdict == "사실 부족" and result.window_end is None
    assert result.missing == ["이전 정밀검사 뒤 수입신고확인증 발급일 (오늘보다 뒤라 다시 확인)"]


def test_window_from_leap_day_ends_on_month_end():
    # 민법 제160조제3항: 마지막 달에 그날이 없으면 그달 말일에 끝난다
    assert reimport_check(facts(prior_cert_on=date(2024, 2, 29)), TODAY).window_end == date(2029, 2, 28)


def test_other_category_is_out_of_scope():
    result = reimport_check(facts(category="그 외"), TODAY)
    assert result.verdict == "대상 아님" and result.basis == []


def test_yaml_names_match_schema():
    # [왜] yaml 이름표와 LLM 스키마의 선택지가 어긋나면 사실을 받아도 표에서 못 찾는다
    rules = load_rules("reimport")
    assert set(rules["categories"]) <= set(get_args(Category))
    for category in rules["categories"].values():
        assert set(category["fields"]) <= set(get_args(SameField))
    assert set(rules["forced"]) == set(get_args(Flag))
