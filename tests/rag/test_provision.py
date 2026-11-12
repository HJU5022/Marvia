from datetime import date

import pytest

from marvia.rag.index import index_units
from marvia.rag.provision import find_provision, named_labels, named_targets, parse_label


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


LAWS = ["시험 특별법", "시험 특별법 시행규칙", "관세법", "관세법 시행령"]


@pytest.mark.parametrize(
    ("query", "labels"),
    [
        # 검색 전용 평가셋의 질의 틀 네 가지
        ("관세법 시행령 제216조의6 내용", ["관세법 시행령 제216조의6"]),
        ("관세법 제241조", ["관세법 제241조"]),
        ("시험 특별법 시행규칙 제18조에는 무엇이 규정되어 있나요?", ["시험 특별법 시행규칙 제18조"]),
        ("시험 특별법 제45조 조문 알려줘", ["시험 특별법 제45조"]),
        # 띄어쓰기가 달라도 색인의 이름으로 돌려준다. "제9조의 규정"의 "의"는 조 번호가 아니다
        ("관세법시행령  제 5 조 의 2 와 관세법 제9조의 규정", ["관세법 시행령 제5조의2", "관세법 제9조"]),
        ("관세법 제241조제3항 가산세", ["관세법 제241조"]),  # 항·호는 떼고 조문으로 찾는다
        ("관세법 제241조와 관세법 제241조", ["관세법 제241조"]),  # 같은 조문은 한 번만
        # 조 번호가 없거나, 색인에 없는 법령이거나, 다른 법령 이름의 끝부분일 뿐이면 지목이 아니다
        ("관세법 수입신고 기한", []),
        ("제241조 내용", []),
        ("식품위생법 제5조", []),
        ("신관세법 제5조", []),
    ],
)
def test_named_labels_finds_law_plus_article_inside_a_query(query, labels):
    assert named_labels(query, LAWS) == labels


@pytest.mark.parametrize(
    ("query", "targets"),
    [
        # 조 뒤에 "제M항"이 있으면 그 항의 이름표를 함께 돌려준다 (띄어 쓰든 붙여 쓰든)
        ("관세법 제241조 제4항 가산세", [("관세법 제241조", "관세법 제241조제4항")]),
        ("관세법 제241조제3항 가산세", [("관세법 제241조", "관세법 제241조제3항")]),
        ("관세법 시행령 제5조의2 제 1 항은?", [("관세법 시행령 제5조의2", "관세법 시행령 제5조의2제1항")]),
        # 항이 없으면 조문만이다
        ("관세법 제241조 내용", [("관세법 제241조", None)]),
        # 같은 조문의 다른 항은 따로 센다. 같은 조문·항은 한 번만
        (
            "관세법 제241조 제3항과 관세법 제241조 제4항, 관세법 제241조 제3항",
            [("관세법 제241조", "관세법 제241조제3항"), ("관세법 제241조", "관세법 제241조제4항")],
        ),
        ("관세법 수입신고 기한", []),
        # 법령 이름을 싼 낫표와 따옴표는 떼고 맞춘다 (법령 글과 공문이 쓰는 꼴)
        ("「관세법」 제241조 제3항의 기한", [("관세법 제241조", "관세법 제241조제3항")]),
        ("『관세법 시행령』제5조의2", [("관세법 시행령 제5조의2", None)]),
        ('"시험 특별법 시행규칙" 제18조 내용', [("시험 특별법 시행규칙 제18조", None)]),
        ("「신관세법」 제5조", []),  # 낫표 안의 이름이 색인의 이름과 달라야 다른 법령이다
    ],
)
def test_named_targets_reads_the_paragraph_after_the_article(query, targets):
    assert named_targets(query, LAWS) == targets
    # 조문 이름표만 보는 쪽은 그대로다: 항을 떼고, 같은 조문은 한 번만
    assert named_labels(query, LAWS) == list(dict.fromkeys(article for article, _ in targets))
