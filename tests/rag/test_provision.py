from datetime import date

import pytest

from marvia.rag.index import index_units
from marvia.rag.provision import find_provision, parse_label


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("관세법 제241조제3항", ("관세법", "제241조.3항")),
        ("관세법 제9조제1항제1호", ("관세법", "제9조.1항.1호")),
        ("관세법 시행령 제247조", ("관세법 시행령", "제247조")),
        ("관세법 제241조의2", ("관세법", "제241조의2")),
        ("시행규칙 별표 9 제2호가목7)", ("수입식품안전관리 특별법 시행규칙", "별표9.2호.가목.7)")),
        ("시행규칙 별표 9 제2호다목2)나)", ("수입식품안전관리 특별법 시행규칙", "별표9.2호.다목.2).나)")),
        ("시행규칙 별표 10 제4호다목", ("수입식품안전관리 특별법 시행규칙", "별표10.4호.다목")),
        ("보세화물관리에 관한 고시 별표 1", ("보세화물관리에 관한 고시", "별표1")),
        ("시행규칙 별표 10 제1호가목1)·3)", None),  # 여럿을 묶은 이름표는 읽지 않는다
        ("별표 9", None),
        ("", None),
    ],
)
def test_parse_label(label, expected):
    assert parse_label(label) == expected


def _index(db, make_unit, fake_embed):
    units = [
        make_unit("제2조.3항", "셋째 항"),
        make_unit("제2조.4항", "넷째 항"),
        make_unit("제2조의2", "다른 조"),
        make_unit("제20조.1항", "스무째 조"),
    ]
    index_units(db, units, fake_embed)


def test_find_provision_narrows_to_the_cited_paragraph(db, make_unit, fake_embed):
    _index(db, make_unit, fake_embed)
    hits = find_provision(db, "시험법 제2조제3항", date(2026, 10, 30))
    assert [h.unit_id for h in hits] == ["LTEST@20261002#제2조.3항"]


def test_find_provision_whole_article_excludes_look_alike_articles(db, make_unit, fake_embed):
    _index(db, make_unit, fake_embed)
    hits = find_provision(db, "시험법 제2조", date(2026, 10, 30))
    assert [h.unit_id for h in hits] == ["LTEST@20261002#제2조.3항", "LTEST@20261002#제2조.4항"]


def test_find_provision_unknown_or_not_yet_effective_is_empty(db, make_unit, fake_embed):
    _index(db, make_unit, fake_embed)
    assert find_provision(db, "없는법 제2조", date(2026, 10, 30)) == []
    assert find_provision(db, "시험법 제2조제3항", date(2020, 1, 1)) == []
    assert find_provision(db, "시험법 별표 1", date(2026, 10, 30)) == []


def test_find_provision_reads_annex_labels_down_to_the_sub_items(db, make_unit, fake_embed):
    units = [
        make_unit("별표9.2호.가목.7)", "동일사 동일수입식품등"),
        make_unit("별표9.2호.가목.12).가)", "재가공 수출"),
        make_unit("별표9.2호.나목.1)", "현장검사"),
    ]
    index_units(db, units, fake_embed)
    hits = find_provision(db, "시험법 별표 9 제2호가목", date(2026, 10, 30))
    assert [h.unit_id for h in hits] == [
        "LTEST@20261002#별표9.2호.가목.12).가)",
        "LTEST@20261002#별표9.2호.가목.7)",
    ]
