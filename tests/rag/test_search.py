from datetime import date

import psycopg
import pytest

from marvia.rag.index import index_units
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
