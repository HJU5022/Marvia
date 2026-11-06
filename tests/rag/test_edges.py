"""법령 그래프 간선 만들기 시험 (계획 3b Task 2, 사전 부검 F4). Neo4j·DB·키 없이 돈다."""

from collections import Counter
from datetime import date

from marvia.eval.dataset import CORPUS_UNITS
from marvia.rag.edges import build_edges, references
from marvia.rag.index import read_units
from marvia.rag.models import Unit

LAWS = {"관세법": "L001556", "관세법 시행령": "L002421", "수입식품안전관리 특별법 시행규칙": "L012500"}


def _unit(key: str, text: str) -> Unit:
    return Unit(
        unit_id=f"LTEST@20261002#{key}",
        doc_id="LTEST",
        law_name="시험법",
        kind="법률",
        effective=date(2026, 10, 2),
        source_url="https://example.test",
        heading=key,
        text=text,
        sha256="0",
    )


def test_references_read_abbreviations_quoted_and_plain_law_names():
    text = "법 제241조제1항에 따라 「관세법 시행령」 제246조 및 관세법 제226조, 제5조"
    found, dropped = references(text, "L002421", LAWS, {"법": "관세법"})
    assert found == [
        ("L001556", "제241조.1항"),
        ("L002421", "제246조"),
        ("L001556", "제226조"),
        ("L002421", "제5조"),
    ]
    assert not dropped


def test_references_drop_same_as_and_laws_outside_the_corpus():
    alias = {"법": "수입식품안전관리 특별법", "영": "수입식품안전관리 특별법 시행령"}
    text = "같은 법 제7조, 「대외무역법 시행령」 제26조, 영 제3조, 식품위생법 제37조"
    found, dropped = references(text, "L012500", LAWS, alias)
    assert found == []
    assert dropped == Counter({"same_as": 1, "outside_corpus": 2, "qualified": 1})


def test_edges_spread_to_sub_units_and_never_point_into_their_own_article():
    units = [
        _unit("제30조.1항", "제30조(검사) ① 별표 9의 검사방법에 따라 검사한다. 제30조제2항도 본다."),
        _unit("제30조.2항", "제30조(검사) ② 제32조에 따른다."),
        _unit("제32조", "제32조(구분) 별표 10에 따른다."),
        _unit("별표9.2호.가목.7)", "[별표 9] 검사방법(제30조 관련) 2. 가. 7) 별표 10 제4호의 조건"),
        _unit("별표10.4호.다목", "[별표 10] 구분기준(제32조 관련) 4. 다. 농산물"),
    ]
    edges = build_edges(units)
    got = {(a.split("#")[1], b.split("#")[1]) for a, b in edges.refers}
    assert ("제30조.1항", "별표9.2호.가목.7)") in got
    assert ("제30조.2항", "제32조") in got
    assert ("별표9.2호.가목.7)", "별표10.4호.다목") in got  # 별표 10 제4호 → 그 아래 목
    assert ("별표9.2호.가목.7)", "제30조.1항") in got  # 별표 제목의 "(제30조 관련)"
    assert all(a.split(".")[0] != b.split(".")[0] for a, b in got)  # 자기 조(별표) 참조는 없다
    assert edges.dropped["self"] == 6
    assert len(edges.part_of) == len(units)


def test_real_corpus_links_the_inspection_article_to_annex_9_without_self_edges():
    edges = build_edges(read_units(CORPUS_UNITS))
    pairs = set(edges.refers)
    assert ("L012500@20260930#제30조.1항", "L012500@20260930#별표9.2호.가목.7)") in pairs
    assert ("L012500@20260930#제32조", "L012500@20260930#별표10.4호.다목") in pairs
    root = lambda u: (u.split("@")[0], u.split("#")[1].split(".")[0])  # noqa: E731
    assert not [(a, b) for a, b in pairs if root(a) == root(b)]
