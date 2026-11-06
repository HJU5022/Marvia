from datetime import date

import pytest

from marvia.graph.schemas import Draft
from marvia.graph.verify import verify

TODAY = date(2026, 11, 2)
MASK = {"[BL1]": "DEMO0001", "[BL2]": "NOPE12345678"}
GOOD = Draft(
    answer=(
        "[BL1]은 2026-10-27에 반입신고됐어요. 관세법 제241조제3항에 따라 반입일부터 30일 안인 "
        "2026-11-26까지 수입신고해야 해요. 오늘(2026-11-02) 기준 24일 남았어요."
    ),
    citations=["L001556@20261002#제241조.3항"],
    next_options=["관세사에게 수입신고를 맡기기"],
    forwarder_message="",
)


@pytest.fixture
def check(evidence, calc, cargos):
    """GOOD에서 바꿀 칸만 넘겨 검증한다."""
    return lambda **changes: verify(GOOD.model_copy(update=changes), evidence, calc, cargos, MASK, TODAY)


def test_good_draft_passes(check):
    assert check() == []


def test_citation_outside_evidence(check):
    bad = ["L001556@20261002#제241조.3항", "LNOPE@20260101#제1조"]
    assert check(citations=bad) == ["근거 묶음에 없는 인용: LNOPE@20260101#제1조"]


def test_evidence_without_citation(check):
    assert "근거가 있는데 인용이 없다" in check(citations=[])


def test_article_must_be_in_cited_evidence(check):
    assert check(answer=GOOD.answer + " 관세법 제9조도 보세요.") == ["인용한 근거에 없는 조문: 제9조"]


def test_article_without_je_is_checked_too(check):
    # [왜] "관세법 9조"처럼 "제"를 빼고 써도 같은 조문이다
    assert check(answer=GOOD.answer + " 관세법 9조도 보세요.") == ["인용한 근거에 없는 조문: 제9조"]


def test_article_with_branch_number_is_another_article(check):
    # [왜] 제241조의2는 제241조와 다른 조문이다. 앞부분이 같다고 통과시키지 않는다
    assert check(answer=GOOD.answer + " 제241조의2도 보세요.") == ["인용한 근거에 없는 조문: 제241조의2"]


def test_date_not_from_calc(check):
    assert check(answer=GOOD.answer + " 2026-12-01에 다시 보세요.") == ["계산 결과에 없는 날짜: 2026-12-01"]


@pytest.mark.parametrize("written", ["11월 26일", "2026.11.26", "11/26"])
def test_other_date_forms(check, written):
    assert check(answer=GOOD.answer + f" {written}까지예요.") == [f"날짜는 YYYY-MM-DD로 쓴다: {written}"]


def test_cited_effective_date_allowed(check):
    # 인용한 근거의 시행일은 근거 묶음에 있는 값이라 써도 된다
    assert check(answer=GOOD.answer + " 이 조문은 2026-10-02부터 시행됐어요.") == []


@pytest.mark.parametrize("written", ["45일", "2주", "6개월", "3년", "3%", "48시간", "24개월"])
def test_number_with_unit_not_from_calc(check, written):
    assert check(answer=GOOD.answer + f" 보통 {written}예요.") == [
        f"계산 결과·인용 근거에 없는 수: {written}"
    ]


def test_rate_from_calc_as_percent(evidence, cargos):
    # 계산 결과의 율 0.015는 답에 1.5%로 쓴다
    calc = {"deadlines": [{"surcharge": {"rate": 0.015, "cap_krw": 5000000}}]}
    draft = Draft(
        answer="지금 신고하면 가산세율은 1.5%예요.", citations=[], next_options=[], forwarder_message=""
    )
    assert verify(draft, [], calc, cargos, MASK, TODAY) == []


def test_day_count_from_cited_evidence(evidence, cargos):
    # 계산 결과가 없어도 인용한 조문 글에 있는 일수(30일)는 쓸 수 있다
    draft = GOOD.model_copy(update={"answer": "반입일부터 30일 안에 수입신고해야 해요."})
    assert verify(draft, evidence, {}, cargos, MASK, TODAY) == []


def test_cargo_stage_date_allowed(cargos):
    draft = Draft(
        answer="[BL1]은 2026-10-27에 반입신고됐어요.", citations=[], next_options=[], forwarder_message=""
    )
    assert verify(draft, [], {}, cargos, MASK, TODAY) == []


def test_real_number_leaks(check):
    assert check(forwarder_message="DEMO0001 서류 부탁드려요") == ["실제 번호가 들어 있다 ([BL1] 자리)"]


# 금지 표현: 패턴마다 걸리는 예와 걸리지 않는 예 (rules/verify.yaml)
@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("이 화물은 통관이 됩니다.", True),
        ("통관이 될지는 관세사에게 확인하세요.", False),
        ("HS 코드는 3924.10입니다.", True),
        ("HS 코드는 관세사가 정해요.", False),
        ("이 화물은 통관이 가능해요.", True),
        ("문제없이 통관될 것 같아요.", True),
        ("통관이 가능한지는 관세사에게 물어보세요.", False),
        ("HS 코드가 3924.10입니다.", True),
        ("HS 3924.10-0000으로 분류돼요.", True),
        ("품목번호는 3924.10.0000입니다.", True),
        ("관세는 약 120,000원이에요.", True),
        ("관세는 약 50만원이에요.", True),
        ("관세로 12만 원 정도 나와요.", True),
        ("관세는 12만 5천원이에요.", True),
        ("관세는 3천만원이에요.", True),
        ("관세는 1억 2천만원이에요.", True),
        ("가산세는 5백만원이에요.", True),
        ("관세는 ₩120,000이에요.", True),
        ("통관될 수 있어요.", True),
        ("통관에 문제없어요.", True),
        ("통관 가능성은 관세사에게 물어보세요.", False),
        ("통관이 가능하신지 관세사에게 확인해 보세요.", False),
        ("HS 코드는 2027년 1월에 바뀌어요.", False),
        ("원산지 표시를 확인하세요.", False),
        ("가산세율은 과세가격의 0.5%예요.", False),
    ],
)
def test_forbidden_patterns(text, hit):
    draft = Draft(answer=text, citations=[], next_options=[], forwarder_message="")
    assert any(v.startswith("금지 표현") for v in verify(draft, [], {}, [], {}, TODAY)) is hit


def test_amount_from_calc_allowed(cargos):
    # [왜] 가산세 상한(cap_krw)처럼 계산 결과에 있는 금액은 세액 계산이 아니라 옮겨 쓴 값이다
    calc = {"deadlines": [{"surcharge": {"rate": 0.005, "cap_krw": 5000000}}]}
    draft = Draft(
        answer="가산세는 500만원을 넘을 수 없어요.", citations=[], next_options=[], forwarder_message=""
    )
    assert verify(draft, [], calc, cargos, MASK, TODAY) == []


def test_numbers_and_articles_written_in_calc_allowed(cargos):
    # [왜] 계산 결과 글은 코드와 rules/*.yaml이 만든 값이다. 작성자가 그 안의 수와 조문 이름을 옮겨도 된다.
    #      인용(unit_id)은 여전히 근거 묶음에서만 온다
    calc = {"reimport": {"verdict": "서류검사 요건 충족", "caveats": ["규정 제7조제1항: 5년 안에 다시 수입"]}}
    draft = Draft(
        answer="이전 정밀검사 뒤 5년 안이라 서류검사 요건을 채워요. 규정 제7조도 함께 보세요.",
        citations=[],
        next_options=[],
        forwarder_message="",
    )
    assert verify(draft, [], calc, cargos, MASK, TODAY) == []


# 재수입 검사 결과는 코드 판정(calc.reimport.verdict)에서만 온다 (R-019, 설계 7.1)
REIMPORT = {"reimport": {"verdict": "서류검사 요건 충족", "basis": [], "caveats": []}}


def _say(text, calc, cargos):
    draft = Draft(answer=text, citations=[], next_options=[], forwarder_message="")
    return verify(draft, [], calc, cargos, MASK, TODAY)


def test_reimport_verdict_without_code_check_is_a_violation(cargos):
    out = _say("같은 제품이라 서류검사 요건 충족이에요.", {}, cargos)
    assert any("재수입" in v for v in out)


def test_reimport_verdict_matching_the_code_check_passes(cargos):
    assert _say("이전 정밀검사 뒤라 서류검사 요건을 채워요.", REIMPORT, cargos) == []


def test_reimport_verdict_differing_from_the_code_check_is_a_violation(cargos):
    out = _say("이 품목은 정밀검사 대상이에요.", REIMPORT, cargos)
    assert any("재수입" in v for v in out)


@pytest.mark.parametrize("text", ["면제받을 수 있어요.", "정밀검사는 면제됩니다.", "검사가 면제돼요."])
def test_reimport_exemption_is_never_asserted(cargos, text):
    assert any("재수입" in v for v in _say(text, REIMPORT, cargos))


@pytest.mark.parametrize(
    "text",
    [
        "면제라고 단정할 수 없어요.",
        "서류검사 요건을 충족하는지는 확인이 필요해요.",
        "정밀검사 대상이 되는 조건은 별표 10에 있어요.",
        "서류검사 요건을 충족한다고 단정할 수 없어요.",
    ],
)
def test_reimport_negation_and_conditions_are_not_flagged(cargos, text):
    assert _say(text, {}, cargos) == []


@pytest.mark.parametrize(
    "text",
    [
        "5년이 지나지 않았으니 서류검사 요건을 충족해요.",
        "이전 검사에서 부적합이 아니었으니 서류검사 요건을 충족해요.",
        "다시 정밀검사를 받지 않아도 되니 면제됩니다.",
        "정밀검사 대상이 아니라 서류검사 요건 충족이에요.",
    ],
)
def test_reimport_verdict_after_an_earlier_negation_is_still_flagged(cargos, text):
    # [왜] 한국어 부정은 서술어 뒤에 온다. 결과 말 앞의 부정은 그 말을 지우지 못한다
    assert any("재수입" in v for v in _say(text, {}, cargos))


@pytest.mark.parametrize(
    "text",
    [
        "서류검사 요건을 충족해요, 하지만 확정은 아니에요.",
        "서류검사 요건을 충족하지만 확정은 아니에요.",
        "서류검사 요건을 충족한다고 해도, 확정은 아니에요.",
    ],
)
def test_reimport_verdict_followed_by_a_negation_in_another_clause_is_flagged(cargos, text):
    # [왜] 부정은 같은 절 안에서만 결과 말을 지운다.
    #      절 경계(rules/verify.yaml clause_end) 뒤의 부정은 세지 않는다.
    #      알려진 한계: "충족한다고 해도, 단정할 수 없어요"도 위반으로 본다 (안전한 쪽)
    assert any("재수입" in v for v in _say(text, {}, cargos))


def test_not_in_evidence_skips_the_missing_citation_rule(check):
    # [왜] 근거에 물은 것이 없다는 답에 인용을 강요하면 상관없는 근거를 끌어다 쓰게 된다
    assert "근거가 있는데 인용이 없다" not in check(citations=[], not_in_evidence=True)
    assert "근거가 있는데 인용이 없다" in check(citations=[], not_in_evidence=False)


def test_not_in_evidence_still_checks_given_citations(evidence):
    draft = GOOD.model_copy(
        update={"not_in_evidence": True, "answer": "근거에 없어요.", "citations": ["LNOPE@20260101#제1조"]}
    )
    assert verify(draft, evidence, {}, [], MASK, TODAY) == ["근거 묶음에 없는 인용: LNOPE@20260101#제1조"]


CONTRADICTION = "근거에 없다고 했는데 코드가 계산하거나 찾은 결과가 있다"


def test_not_in_evidence_with_calc_result_is_a_violation(check):
    assert CONTRADICTION in check(not_in_evidence=True)  # calc 픽스처에 기한 계산이 있다


def test_not_in_evidence_with_found_cargo_is_a_violation(evidence, cargos):
    draft = GOOD.model_copy(update={"not_in_evidence": True})
    assert CONTRADICTION in verify(draft, evidence, {}, cargos, MASK, TODAY)


def test_not_in_evidence_alone_is_not_a_violation(evidence):
    draft = GOOD.model_copy(update={"not_in_evidence": True, "citations": [], "answer": "근거에 없어요."})
    assert verify(draft, evidence, {}, [], MASK, TODAY) == []
