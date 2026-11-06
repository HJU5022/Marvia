"""품목 요건 그래프 데이터 시험 (계획 3b Task 5). 키·DB 없이 돈다."""

from datetime import date

import pytest

from marvia.eval.dataset import CORPUS_UNITS
from marvia.rag.index import read_units
from marvia.rag.items import (
    Grounding,
    Item,
    ItemGraph,
    Requirement,
    check_items,
    item_names,
    known_cost,
    load_items,
)
from marvia.rag.models import Unit

UNIT = Unit(
    unit_id="LTEST@20261002#제1조",
    doc_id="LTEST",
    law_name="시험법",
    kind="법률",
    effective=date(2026, 10, 2),
    source_url="https://example.test",
    heading="제1조",
    text="수입하려는 자는 수입신고를 하여야 한다.",
    sha256="0",
)


def _graph(unit_id: str, quote: str) -> ItemGraph:
    req = Requirement(name="수입신고", grounded_in=[Grounding(unit_id=unit_id, quote=quote)])
    return ItemGraph(reviewed="시험", items=[Item(name="건고추", aliases=["마른 고추"], requires=[req])])


def test_check_items_flags_missing_units_and_quotes_not_in_the_text():
    units = {UNIT.unit_id: UNIT}
    assert check_items(_graph(UNIT.unit_id, "수입신고를 하여야"), units) == []
    assert check_items(_graph(UNIT.unit_id, "정밀검사를 받아야"), units) == [
        "건고추/수입신고: 구절이 LTEST@20261002#제1조 글에 없다"
    ]
    assert check_items(_graph("LTEST@20261002#제9조", "아무"), units) == [
        "건고추/수입신고: 코퍼스에 없는 단위 LTEST@20261002#제9조"
    ]


def test_check_items_flags_document_and_agency_names_missing_from_the_grounding_text():
    # [왜] 근거 구절이 맞아도 서류·기관 이름을 LLM이 지어낼 수 있다. 이름도 근거 단위 글에 그대로 있어야 한다
    units = {UNIT.unit_id: UNIT}
    grounding = Grounding(unit_id=UNIT.unit_id, quote="수입신고를 하여야")

    def graph(needs: list[str], by: list[str]) -> ItemGraph:
        req = Requirement(name="수입신고", grounded_in=[grounding], needs=needs, by=by)
        return ItemGraph(reviewed="시험", items=[Item(name="건고추", requires=[req])])

    assert check_items(graph(["수입신고"], ["한국"]), units) == [
        "건고추/수입신고: 기관 이름이 근거 글에 없다: 한국"
    ]
    assert check_items(graph(["지어낸 서류"], []), units) == [
        "건고추/수입신고: 서류 이름이 근거 글에 없다: 지어낸 서류"
    ]
    assert check_items(graph(["수입신고"], ["수입"]), units) == []


def test_known_cost_stops_when_the_model_has_no_price():
    # [왜] 단가를 모르는 모델이면 누계가 0으로 남아 --max-cost가 한 번도 걸리지 않는다
    assert known_cost(0.0123) == 0.0123
    with pytest.raises(SystemExit, match="단가를 모르는 모델이다"):
        known_cost(None)


def test_item_names_match_names_and_aliases_ignoring_spaces():
    items = _graph(UNIT.unit_id, "x").items
    assert item_names("마른고추 재수입 정밀검사", items) == ["건고추"]
    assert item_names("실리콘 주방 매트 수입신고", items) == []


def test_committed_items_file_is_grounded_in_the_corpus_and_labelled():
    graph = load_items()
    assert {i.name for i in graph.items} == {"실리콘 주방 매트", "건고추"}  # 설계 5.5의 1차 대표 품목
    assert "사람 검토 전" in graph.reviewed  # [왜] 사람 검토는 아직이다. 표시가 남아야 한다
    units = {u.unit_id: u for u in read_units(CORPUS_UNITS)}
    assert check_items(graph, units) == []
