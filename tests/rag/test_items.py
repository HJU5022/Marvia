"""품목 요건 그래프 데이터 시험 (계획 3b Task 5). 키·DB 없이 돈다."""

from datetime import date

from marvia.eval.dataset import CORPUS_UNITS
from marvia.rag.index import read_units
from marvia.rag.items import Grounding, Item, ItemGraph, Requirement, check_items, item_names, load_items
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
