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


def test_article_with_branch_number_is_another_article(check):
    # [왜] 제241조의2는 제241조와 다른 조문이다. 앞부분이 같다고 통과시키지 않는다
    assert check(answer=GOOD.answer + " 제241조의2도 보세요.") == ["인용한 근거에 없는 조문: 제241조의2"]


def test_date_not_from_calc(check):
    assert check(answer=GOOD.answer + " 2026-12-01에 다시 보세요.") == ["계산 결과에 없는 날짜: 2026-12-01"]


def test_korean_date_form(check):
    assert check(answer=GOOD.answer + " 11월 26일까지예요.") == ["날짜는 YYYY-MM-DD로 쓴다: 11월 26일"]


def test_day_count_not_from_calc(check):
    assert check(answer=GOOD.answer + " 보통 45일 걸려요.") == ["계산 결과·인용 근거에 없는 일수: 45일"]


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
        ("관세는 약 120,000원이에요.", True),
        ("관세는 약 50만원이에요.", True),
        ("가산세율은 과세가격의 0.5%예요.", False),
    ],
)
def test_forbidden_patterns(text, hit):
    draft = Draft(answer=text, citations=[], next_options=[], forwarder_message="")
    assert any(v.startswith("금지 표현") for v in verify(draft, [], {}, [], {}, TODAY)) is hit
