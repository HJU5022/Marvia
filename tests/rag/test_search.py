from datetime import date

import psycopg
import pytest

from marvia.graph.rag import top_ranked
from marvia.rag import search as search_module
from marvia.rag.index import index_units
from marvia.rag.mcp import build_server, mcp_ranked
from marvia.rag.models import SearchFailed
from marvia.rag.search import hybrid_search, leg_search, rrf


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


AS_OF = date(2026, 10, 30)


def in_law(unit, law: str, doc: str):
    """make_unit이 만든 단위를 다른 법령의 단위로 바꾼다."""
    unit_id = unit.unit_id.replace("LTEST", doc)
    heading = unit.heading.replace("시험법", law)
    return unit.model_copy(update={"unit_id": unit_id, "doc_id": doc, "law_name": law, "heading": heading})


@pytest.fixture
def named_article(monkeypatch):
    """rules/rag.yaml search.named_article의 값을 바꾸는 함수."""
    real = search_module.load_rules

    def change(**values):
        def fake(name: str) -> dict:
            cfg = real(name)
            if name != "rag":
                return cfg
            return cfg | {
                "search": cfg["search"] | {"named_article": cfg["search"]["named_article"] | values}
            }

        monkeypatch.setattr(search_module, "load_rules", fake)

    return change


def test_a_query_that_names_an_article_gets_that_article_first(db, make_unit, fake_embed, narrow):
    units = [
        make_unit("제1조", "정밀검사를 면제할 수 있다"),
        make_unit("제45조", "영업의 승계"),
        make_unit("제45조.1항", "영업자가 사망한 경우"),
        make_unit("제45조의2", "다른 조문이다"),
        make_unit("제45조.2항", "아직 시행 전이다", effective=date(2027, 1, 1)),
    ]
    index_units(db, units, fake_embed)
    # [왜] 벡터·키워드 다리는 조 번호를 잘 가르지 못한다(11-12 실측). 조문을 지목한 질의는 직접 조회로 잇는다
    hits = hybrid_search(db, "시험법 제45조에는 무엇이 규정되어 있나요?", fake_embed, as_of=AS_OF)
    assert [(h.unit_id, h.origin) for h in hits[:2]] == [
        ("LTEST@20261002#제45조", "provision"),
        ("LTEST@20261002#제45조.1항", "provision"),
    ]
    ids = [h.unit_id for h in hits]
    assert len(ids) == len(set(ids))  # 하이브리드가 찾은 같은 단위는 한 번만 둔다
    assert "LTEST@20270101#제45조.2항" not in ids  # 조회에도 기준 날짜를 그대로 적용한다
    assert all(h.origin != "provision" for h in hits[2:])


def test_the_longer_law_name_wins_when_one_name_starts_with_the_other(db, make_unit, fake_embed, narrow):
    act = in_law(make_unit("제45조", "법의 제45조"), "시험 특별법", "LACT")
    rule = in_law(make_unit("제45조", "시행규칙의 제45조"), "시험 특별법 시행규칙", "LRULE")
    index_units(db, [act, rule, make_unit("제1조", "정밀검사를 면제할 수 있다")], fake_embed)

    def first(query: str) -> list[str]:
        hits = hybrid_search(db, query, fake_embed, as_of=AS_OF)
        return [h.unit_id for h in hits if h.origin == "provision"]

    assert first("시험 특별법 시행규칙 제45조 내용") == [rule.unit_id]
    assert first("시험 특별법 제45조 내용") == [act.unit_id]


@pytest.mark.parametrize(
    "query",
    ["정밀검사 면제 조건", "시험법에서 보세구역 반입은 어떻게 하나요", "제45조 내용", "없는법 제45조"],
)
def test_a_query_without_a_named_article_is_not_changed_at_all(
    db, make_unit, fake_embed, named_article, query
):
    units = [
        make_unit("제1조", "정밀검사를 면제할 수 있다"),
        make_unit("제45조", "보세구역에 반입한다"),
        make_unit("제3조", "수입신고는 입항 후에 한다"),
    ]
    index_units(db, units, fake_embed)
    on = hybrid_search(db, query, fake_embed, as_of=AS_OF)
    named_article(enabled=False)
    off = hybrid_search(db, query, fake_embed, as_of=AS_OF)
    assert on == off and on  # 단위, 순서, 점수, origin까지 같다


def test_named_article_lookup_has_a_switch_and_a_cap(db, make_unit, fake_embed, narrow, named_article):
    units = [make_unit("제45조", "영업의 승계")] + [make_unit(f"제45조.{n}항", "본문") for n in range(1, 6)]
    index_units(db, [*units, make_unit("제1조", "정밀검사를 면제할 수 있다")], fake_embed)
    query = "시험법 제45조 정밀검사"
    named_article(max_units=3)
    capped = [h.unit_id for h in hybrid_search(db, query, fake_embed, as_of=AS_OF) if h.origin == "provision"]
    assert capped == [u.unit_id for u in units[:3]]
    named_article(enabled=False)
    assert all(h.origin != "provision" for h in hybrid_search(db, query, fake_embed, as_of=AS_OF))


def test_direct_and_mcp_paths_both_carry_the_named_article(db, make_unit, fake_embed, narrow):
    units = [make_unit("제1조", "정밀검사를 면제할 수 있다"), make_unit("제45조", "영업의 승계")]
    index_units(db, units, fake_embed)

    def direct(query: str, as_of: date):
        # 리랭커는 뒤 후보일수록 높게 준다: 맨 앞에 둔 조회 단위가 리랭커를 거쳐도 남는지 본다
        return top_ranked(
            lambda q, d: hybrid_search(db, q, fake_embed, as_of=d),
            lambda q, texts: [float(i) for i in range(len(texts))],
            query,
            as_of,
        )

    got = direct("시험법 제45조 조문 알려줘", AS_OF)
    assert "LTEST@20261002#제45조" in [e.unit_id for e in got]
    assert mcp_ranked(build_server(direct))("시험법 제45조 조문 알려줘", AS_OF) == got


def test_one_leg_alone_can_be_searched_for_measurement(db, make_unit, fake_embed, narrow):
    units = [
        make_unit("제1조", "보세구역 반입"),  # 가짜 벡터로는 "보세 반입"에 가장 가깝다
        make_unit("제2조", "정밀검사를 면제할 수 있다"),  # 낱말 "정밀검사"가 있다
    ]
    index_units(db, units, fake_embed)
    query = "정밀검사 보세 반입"
    assert [e.unit_id for e in leg_search(db, query, fake_embed, AS_OF, "vector")] == ["LTEST@20261002#제1조"]
    assert [e.unit_id for e in leg_search(db, query, fake_embed, AS_OF, "keyword")] == [
        "LTEST@20261002#제2조"
    ]
    # [주의] 한 다리만 재는 길에는 조문 직접 조회와 그래프가 붙지 않는다. 그 다리의 순위 그대로다
    named = leg_search(db, "시험법 제2조 보세 반입", fake_embed, AS_OF, "vector")
    assert [(e.unit_id, e.origin) for e in named] == [("LTEST@20261002#제1조", "hybrid")]
    assert (
        leg_search(db, "정밀검사", fake_embed, date(2020, 1, 1), "keyword") == []
    )  # 기준 날짜는 그대로 건다
    with pytest.raises(ValueError):
        leg_search(db, query, fake_embed, AS_OF, "rrf")


def provision_ids(hits) -> list[str]:
    return [h.unit_id.split("#")[1] for h in hits if h.origin == "provision"]


def test_a_named_paragraph_comes_first_and_the_rest_of_the_article_fills_the_cap(
    db, make_unit, fake_embed, narrow, named_article
):
    labels = [
        "제45조.1항",
        "제45조.2항.1호",
        "제45조.2항.2호",
        "제45조.3항",
        "제45조.4항.1호",
        "제45조.4항.2호",
    ]
    index_units(
        db, [make_unit(label, "본문") for label in labels] + [make_unit("제1조", "정밀검사")], fake_embed
    )
    named_article(max_units=4)
    plain = provision_ids(hybrid_search(db, "시험법 제45조 내용", fake_embed, as_of=AS_OF))
    # 항을 지목하지 않은 질의는 지금까지와 같다: 조문의 단위를 unit_id 순서로, 상한까지
    assert plain == labels[:4]
    # [왜] 상한에서 자르면 지목한 항이 잘려 나갔다(13단위 조문의 제4항은 10번째였다). 지목한 항을 먼저 둔다
    fourth = provision_ids(hybrid_search(db, "시험법 제45조 제4항 가산세", fake_embed, as_of=AS_OF))
    assert fourth == ["제45조.4항.1호", "제45조.4항.2호", "제45조.1항", "제45조.2항.1호"]
    joined = provision_ids(hybrid_search(db, "시험법 제45조제3항", fake_embed, as_of=AS_OF))
    assert joined == ["제45조.3항", "제45조.1항", "제45조.2항.1호", "제45조.2항.2호"]
    # 색인에 없는 항을 지목하면 조문 단위로 돌려준다(항이 없는 질의와 같은 결과)
    missing = provision_ids(hybrid_search(db, "시험법 제45조 제9항 내용", fake_embed, as_of=AS_OF))
    assert missing == plain
