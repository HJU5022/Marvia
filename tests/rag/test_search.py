from datetime import date

import psycopg
import pytest

from marvia.rag import search as search_module
from marvia.rag.index import index_units
from marvia.rag.models import SearchFailed
from marvia.rag.search import hybrid_search, rrf


def test_rrf_score_formula():
    assert rrf([["a"]], k=60) == [("a", 1 / 61)]


def test_rrf_rewards_units_found_by_both():
    # b는 두 목록에 다 있어서 한 목록 1등인 a보다 앞선다
    assert [unit_id for unit_id, _ in rrf([["a", "b"], ["b", "c"]], k=60)] == ["b", "a", "c"]


def test_hybrid_puts_matching_unit_first(db, make_unit, fake_embed):
    units = [
        make_unit("제1조", "수입신고는 입항 후에 한다"),
        make_unit("제2조", "정밀검사를 면제할 수 있다"),
        make_unit("제3조", "보세구역에 반입한다"),
    ]
    index_units(db, units, fake_embed)
    hits = hybrid_search(db, "정밀검사 면제 조건", fake_embed, as_of=date(2026, 10, 30))
    assert hits[0].unit_id == "LTEST@20261002#제2조"
    assert hits[0].law_name == "시험법"


def test_hybrid_skips_units_effective_after_as_of(db, make_unit, fake_embed):
    index_units(db, [make_unit("제2조", "정밀검사를 면제할 수 있다")], fake_embed)  # 시행 2026-10-02
    assert hybrid_search(db, "정밀검사", fake_embed, as_of=date(2020, 1, 1)) == []


def test_search_recovers_after_db_error(db, make_unit, fake_embed):
    # [왜] 한 번 DB 오류가 나면 트랜잭션이 실패 상태로 남아 같은 연결의 다음 검색이 모두 죽었다
    index_units(db, [make_unit("제2조", "정밀검사를 면제할 수 있다")], fake_embed)

    def bad_embed(texts):
        return [[0.0] * 3 for _ in texts]  # 차원이 달라 VECTOR_SQL이 DB 오류를 낸다

    with pytest.raises(psycopg.Error):
        hybrid_search(db, "정밀검사", bad_embed, as_of=date(2026, 10, 30))
    hits = hybrid_search(db, "정밀검사 면제", fake_embed, as_of=date(2026, 10, 30))
    assert hits[0].unit_id == "LTEST@20261002#제2조"


@pytest.fixture
def narrow(monkeypatch):
    """하이브리드가 벡터·키워드 한 개씩만 찾게 줄인다. [왜] 단위가 적으면 벡터 검색이 모든 단위를 돌려준다"""
    real = search_module.load_rules

    def fake(name: str) -> dict:
        cfg = real(name)
        return cfg | {"search": cfg["search"] | {"vector_k": 1, "keyword_k": 1}} if name == "rag" else cfg

    monkeypatch.setattr(search_module, "load_rules", fake)


def test_graph_neighbors_join_after_hybrid_without_duplicates_future_or_unknown_units(
    db, make_unit, fake_embed, narrow
):
    units = [
        make_unit("제1조", "정밀검사를 면제할 수 있다"),
        make_unit("제2조", "보세구역에 반입한다"),
        make_unit("제3조", "보세구역 반입 신고", effective=date(2027, 1, 1)),
    ]
    index_units(db, units, fake_embed)
    seen: dict = {}

    def expand(seeds: list[str], query: str) -> list[str]:
        seen["seeds"] = seeds
        return [u.unit_id for u in units] + ["LTEST@20261002#없는조"]

    hits = hybrid_search(db, "정밀검사 면제", fake_embed, as_of=date(2026, 10, 30), expand=expand)
    assert [(h.unit_id, h.origin) for h in hits] == [
        ("LTEST@20261002#제1조", "hybrid"),
        ("LTEST@20261002#제2조", "graph"),
    ]
    assert hits[1].score == 0.0 and hits[1].text == "보세구역에 반입한다"
    assert seen["seeds"] == ["LTEST@20261002#제1조"]


def test_graph_candidates_are_capped_and_closest_to_the_query_first(db, make_unit, fake_embed, narrow):
    units = [make_unit("제1조", "정밀검사 면제")]
    units += [make_unit(f"제{i}조", "검사 반입" if i % 2 == 0 else "보세") for i in range(2, 15)]
    index_units(db, units, fake_embed)
    ids = [u.unit_id for u in units[1:]]
    hits = hybrid_search(db, "정밀검사 면제", fake_embed, as_of=date(2026, 10, 30), expand=lambda s, q: ids)
    graph = [h for h in hits if h.origin == "graph"]
    assert len(graph) == 10  # rules/graph.yaml expand.max_candidates
    assert all(h.text == "검사 반입" for h in graph[:7])  # 질의 벡터("검사")에 가까운 7개가 먼저


def test_graph_failure_is_raised_not_hidden(db, make_unit, fake_embed):
    index_units(db, [make_unit("제1조", "정밀검사를 면제할 수 있다")], fake_embed)

    def down(seeds: list[str], query: str) -> list[str]:
        raise SearchFailed("graph_unavailable")

    with pytest.raises(SearchFailed):
        hybrid_search(db, "정밀검사", fake_embed, as_of=date(2026, 10, 30), expand=down)
    assert (
        hybrid_search(db, "정밀검사", fake_embed, as_of=date(2026, 10, 30))[0].unit_id
        == "LTEST@20261002#제1조"
    )
