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
        ("시행규칙 별표 9 제2호가목7)", None),
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
