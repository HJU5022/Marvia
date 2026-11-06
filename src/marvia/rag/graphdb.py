"""법령 그래프를 Neo4j에 넣고, 검색 때 이웃 단위의 unit_id를 찾는다 (설계 5.5, 계획 3b Task 3·4).

하지 않는 일: 간선 만들기(edges.py), 글·시행일 고르기. 그래프는 unit_id만 돌려주고 글과 시행일 거르기는
Postgres가 한다(search.py). 그래서 두 저장소가 어긋나도 없는 단위를 근거로 내지 않는다.
[왜] Postgres가 하이브리드 검색을 맡고 Neo4j는 관계 확장만 한다. neo4j-graphrag의 HybridRetriever는
     Neo4j 안에 벡터·전문 색인을 한 벌 더 만들므로 쓰지 않는다(설계 15절의 2차 비교 실험).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import LiteralString

from neo4j import Driver, GraphDatabase, RoutingControl
from neo4j.exceptions import DriverError, Neo4jError

from marvia.config import Settings
from marvia.rag.edges import Edges
from marvia.rag.models import SearchFailed, Unit
from marvia.tools.rules import load_rules

# [왜] 제약을 먼저 만들어야 MERGE가 색인으로 찾는다. 없으면 7천 번의 MERGE가 매번 전체를 훑는다
CONSTRAINTS: list[LiteralString] = [
    "CREATE CONSTRAINT unit_id IF NOT EXISTS FOR (u:Unit) REQUIRE u.unit_id IS UNIQUE",
    "CREATE CONSTRAINT law_doc_id IF NOT EXISTS FOR (l:Law) REQUIRE l.doc_id IS UNIQUE",
    "CREATE CONSTRAINT graph_name IF NOT EXISTS FOR (g:Graph) REQUIRE g.name IS UNIQUE",
]
LAWS: LiteralString = "UNWIND $rows AS r MERGE (l:Law {doc_id: r.doc_id}) SET l.name = r.name"
UNITS: LiteralString = """
UNWIND $rows AS r
MERGE (u:Unit {unit_id: r.unit_id}) SET u.doc_id = r.doc_id
WITH u, r
MATCH (l:Law {doc_id: r.doc_id})
MERGE (u)-[:PART_OF]->(l)
"""
DELEGATES: LiteralString = """
UNWIND $rows AS r
MATCH (a:Law {doc_id: r[0]}), (b:Law {doc_id: r[1]})
MERGE (a)-[:DELEGATES_TO]->(b)
"""
REFERS: LiteralString = """
UNWIND $rows AS r
MATCH (a:Unit {unit_id: r[0]}), (b:Unit {unit_id: r[1]})
MERGE (a)-[:REFERS_TO]->(b)
"""
META: LiteralString = "MERGE (g:Graph {name: $name}) SET g.units_sha256 = $sha, g.built_at = $built_at"
READ_META: LiteralString = """
MATCH (g:Graph {name: $name})
OPTIONAL MATCH (u:Unit) WHERE u.doc_id IN $docs
OPTIONAL MATCH (u)-[r:REFERS_TO]->()
RETURN g.units_sha256 AS sha, g.built_at AS built_at, count(DISTINCT u) AS units, count(r) AS refers
"""


def connect_graph(settings: Settings) -> Driver:
    """설정의 Neo4j에 붙는 드라이버. 만들 때는 접속하지 않고 첫 질의 때 접속한다."""
    cfg = load_rules("graph")["driver"]
    return GraphDatabase.driver(
        settings.neo4j_url,
        auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
        # [왜] Neo4j가 꺼져 있으면 기본값으로는 검색 한 번이 30초씩 기다린다. 짧게 끊고 검색 실패로 남긴다
        connection_timeout=cfg["connection_timeout_s"],
        max_transaction_retry_time=cfg["max_retry_s"],
    )


def _batches(rows: list, size: int):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def load_graph(
    driver: Driver, units: list[Unit], edges: Edges, *, name: str, sha: str, built_at: str
) -> None:
    """단위·법령 노드와 간선을 넣는다. MERGE라 두 번 넣어도 수가 같다. 메타 노드에 단위 파일 sha를 남긴다."""
    size = load_rules("graph")["load"]["batch"]
    for statement in CONSTRAINTS:
        driver.execute_query(statement)
    laws = {u.doc_id: u.law_name for u in units}
    driver.execute_query(LAWS, {"rows": [{"doc_id": d, "name": n} for d, n in laws.items()]})
    rows = [{"unit_id": u.unit_id, "doc_id": u.doc_id} for u in units]
    for chunk in _batches(rows, size):
        driver.execute_query(UNITS, {"rows": chunk})
    driver.execute_query(DELEGATES, {"rows": [list(pair) for pair in edges.delegates]})
    for chunk in _batches([list(pair) for pair in edges.refers], size):
        driver.execute_query(REFERS, {"rows": chunk})
    driver.execute_query(META, {"name": name, "sha": sha, "built_at": built_at})


def graph_meta(driver: Driver, name: str, docs: list[str]) -> dict:
    """메타 노드의 sha·만든 시각과 문서들의 단위 수·참조 간선 수. 그래프가 없으면 빈 dict."""
    params = {"name": name, "docs": docs}
    records = driver.execute_query(READ_META, params, routing_=RoutingControl.READ).records
    return dict(records[0]) if records else {}


def units_sha256(folder: Path) -> str:
    """단위 파일들(*.jsonl)을 이름 순서로 이어 붙인 sha256. 그래프가 어느 코퍼스로 만들어졌는지 남긴다."""
    return hashlib.sha256(b"".join(p.read_bytes() for p in sorted(folder.glob("*.jsonl")))).hexdigest()


# --- 검색 때 이웃 찾기 (Task 4) ---

# [왜] 방향 없이 1단계: 시드가 가리키는 단위(제30조.1항 → 별표 9)와 시드를 가리키는 단위(별표 9 → 제30조)
NEIGHBORS: LiteralString = """
MATCH (s:Unit)-[:REFERS_TO]-(t:Unit)
WHERE s.unit_id IN $seeds
RETURN DISTINCT t.unit_id AS unit_id
"""


def neighbors(driver: Driver, seeds: list[str]) -> list[str]:
    """시드와 REFERS_TO로 이어진 단위의 unit_id. 못 닿으면 SearchFailed."""
    if not seeds:
        return []
    try:
        params = {"seeds": seeds}
        records = driver.execute_query(NEIGHBORS, params, routing_=RoutingControl.READ).records
    except (Neo4jError, DriverError) as error:
        # [왜] 조용히 하이브리드만 쓰면 "그래프 켬" 실행이 실제로는 꺼진 채 돈다(사전 부검 F1)
        raise SearchFailed("graph_unavailable") from error
    return [r["unit_id"] for r in records]


def graph_expand(settings: Settings) -> Callable[[list[str], str], list[str]]:
    """검색이 부를 그래프 확장 함수. 드라이버는 프로세스가 끝날 때까지 하나를 쓴다."""
    driver = connect_graph(settings)
    return lambda seeds, query: neighbors(driver, seeds)
