"""Neo4j 적재와 이웃 찾기 시험 (계획 3b Task 3·4). 꺼져 있으면 건너뛴다(MARVIA_REQUIRE_NEO4J=1이면 실패)."""

import json
from datetime import date

import pytest

from marvia.config import Settings
from marvia.eval.dataset import CORPUS_UNITS
from marvia.rag.edges import build_edges
from marvia.rag.graphdb import connect_graph, graph_meta, load_graph, neighbors
from marvia.rag.models import SearchFailed, Unit


def _units(doc: str) -> list[Unit]:
    rows = [
        ("제30조.1항", "제30조(검사) ① 별표 9의 검사방법에 따라 검사한다."),
        ("제32조", "제32조(구분) 별표 10에 따른다."),
        ("별표9.2호.가목.7)", "[별표 9] 검사방법(제30조 관련) 7) 별표 10 제4호의 조건"),
        ("별표10.4호.다목", "[별표 10] 구분기준(제32조 관련) 다. 농산물"),
    ]
    return [
        Unit(
            unit_id=f"{doc}@20261002#{key}",
            doc_id=doc,
            law_name=f"시험법 {doc}",
            kind="법률",
            effective=date(2026, 10, 2),
            source_url="https://example.test",
            heading=key,
            text=text,
            sha256="0",
        )
        for key, text in rows
    ]


def _load(driver, doc: str):
    units = _units(doc)
    edges = build_edges(units)
    edges.delegates = []  # [왜] 위임 간선은 실제 문서 id 사이라 시험 그래프에 넣지 않는다
    load_graph(driver, units, edges, name=doc, sha="abc", built_at="2026-11-06T00:00:00+00:00")
    return units, edges


def test_loading_twice_keeps_the_same_counts_and_meta(graph_db):
    driver, doc = graph_db
    units, edges = _load(driver, doc)
    _load(driver, doc)
    assert graph_meta(driver, doc, [doc]) == {
        "sha": "abc",
        "built_at": "2026-11-06T00:00:00+00:00",
        "units": len(units),
        "refers": len(edges.refers),
    }


def test_fixture_doc_id_is_a_fixture_value_never_a_corpus_doc_id(graph_db):
    # [왜] 지우기 문이 doc_id 일치나 이름 앞머리로 고르므로, 실제 문서 id와 겹치면 실제 노드가 지워진다
    _, doc = graph_db
    manifest = json.loads((CORPUS_UNITS.parent / "manifest.json").read_text(encoding="utf-8"))
    real = {m["doc_id"] for m in manifest}
    assert doc.startswith("TEST") and doc not in real
    assert not any(r.startswith("TEST") for r in real)


def test_neighbors_follow_references_both_ways(graph_db):
    driver, doc = graph_db
    _load(driver, doc)
    near = set(neighbors(driver, [f"{doc}@20261002#제30조.1항"]))
    assert near == {f"{doc}@20261002#별표9.2호.가목.7)"}
    # [왜] 별표에서 출발하면 그 별표를 가리키는 조문(들어오는 간선)과 별표가 가리키는 단위를 함께 본다
    assert set(neighbors(driver, [f"{doc}@20261002#별표9.2호.가목.7)"])) == {
        f"{doc}@20261002#제30조.1항",
        f"{doc}@20261002#별표10.4호.다목",
    }
    assert neighbors(driver, []) == [] and neighbors(driver, [f"{doc}@20261002#없는조"]) == []


def test_unreachable_neo4j_is_a_search_failure_not_an_empty_result():
    driver = connect_graph(Settings(neo4j_url="bolt://127.0.0.1:1"))
    with pytest.raises(SearchFailed, match="graph_unavailable"):
        neighbors(driver, ["LTEST@20261002#제1조"])
    driver.close()


def test_reloading_replaces_edges_with_the_current_result(graph_db):
    driver, doc = graph_db
    units = _units(doc)
    edges = build_edges(units)
    edges.delegates = [(doc, doc)]  # [왜] 시험 문서 하나뿐이라 자기 위임으로 DELEGATES_TO 교체를 본다
    load_graph(driver, units, edges, name=doc, sha="x", built_at="2026-11-06T00:00:00+00:00")
    assert len(edges.refers) > 1
    kept = edges.refers[:1]
    edges.refers, edges.delegates = kept, []
    load_graph(driver, units, edges, name=doc, sha="y", built_at="2026-11-06T00:00:00+00:00")
    assert graph_meta(driver, doc, [doc]) == {
        "sha": "y",
        "built_at": "2026-11-06T00:00:00+00:00",
        "units": len(units),
        "refers": 1,
    }
    delegates = driver.execute_query(
        "MATCH (:Law {doc_id: $doc})-[r:DELEGATES_TO]->() RETURN count(r) AS n", {"doc": doc}
    ).records[0]["n"]
    assert delegates == 0
