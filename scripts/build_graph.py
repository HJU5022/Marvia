"""코퍼스 단위로 법령 그래프를 만들어 로컬 Neo4j에 넣는다 (설계 5.5, 계획 3b Task 2·3·5).

실행: uv run python scripts/build_graph.py              넣고 수를 찍는다 (docker compose up -d neo4j)
      uv run python scripts/build_graph.py --sample 30  넣지 않고 참조 간선 30개를 찍는다 (표본 대조)
[주의] 다시 돌려도 MERGE라 수가 늘지 않는다. 단위 파일이 바뀌면 다시 돌린다(메타 노드의 sha가 바뀐다).
"""

import argparse
import random
from datetime import UTC, datetime

from marvia.config import Settings
from marvia.eval.dataset import CORPUS_UNITS
from marvia.rag.edges import build_edges
from marvia.rag.graphdb import connect_graph, graph_meta, load_graph, units_sha256
from marvia.rag.index import read_units
from marvia.rag.items import items_sha256, load_items

parser = argparse.ArgumentParser()
parser.add_argument("--sample", type=int, default=0, help="넣지 않고 무작위 간선 n개를 찍는다")
parser.add_argument("--seed", type=int, default=1106)
args = parser.parse_args()

units = read_units(CORPUS_UNITS)
edges = build_edges(units)
print(f"단위 {len(units)}, 참조 간선 {len(edges.refers)}, 위임 {len(edges.delegates)}")
print(f"버린 참조 {dict(edges.dropped)}")
if args.sample:
    by_id = {u.unit_id: u for u in units}
    for a, b in random.Random(args.seed).sample(edges.refers, args.sample):
        print(f"\n{a} -> {b}\n  가리키는 글: {by_id[a].text[:400]}\n  가리켜진 단위: {by_id[b].heading}")
    raise SystemExit(0)
driver = connect_graph(Settings())
built_at = datetime.now(UTC).isoformat(timespec="seconds")
load_graph(
    driver,
    units,
    edges,
    name="main",
    sha=units_sha256(CORPUS_UNITS),
    items_sha=items_sha256(),
    built_at=built_at,
    items=load_items(),
    items_owner="main",
)
print(graph_meta(driver, "main", sorted({u.doc_id for u in units})))
driver.close()
