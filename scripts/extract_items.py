"""대표 품목 2종의 요건 간선을 LLM으로 한 번 뽑아 초안 파일로 쓴다 (설계 5.5, 계획 3b Task 5). 돈이 든다.

실행: uv run python scripts/extract_items.py --out <저장소 밖>/items.draft.yaml --max-cost 0.05
결과: 초안 YAML. 대조(corpus/graph/items_check.md)를 거친 뒤 corpus/graph/items.yaml로 옮겨 동결한다.
[왜] 뽑기는 한 번만 하고 결과를 데이터로 둔다. 그래야 그래프 적재가 늘 같다.
[주의] 품목·질의 틀은 설계 5.5의 1차 품목에서 정했다. 평가 문항을 보고 고치지 않는다.
"""

import argparse
import sys
from datetime import date
from functools import partial
from pathlib import Path

import yaml
from langchain_core.callbacks import get_usage_metadata_callback
from pydantic import BaseModel

from marvia.config import Settings
from marvia.db import read_pool
from marvia.eval.run import cost_usd, inside_repo
from marvia.graph.rag import evidence_block, top_ranked
from marvia.llm import chat_model, structured
from marvia.prompts import render
from marvia.rag.items import Item, ItemGraph, Requirement, known_cost
from marvia.rag.live import live_deps
from marvia.tools.rules import load_rules

ITEMS = {"실리콘 주방 매트": ["실리콘 주방매트", "실리콘 매트"], "건고추": ["마른 고추", "건조 고추"]}
QUERIES = ["{} 수입신고 요건", "{} 수입 검사 종류와 대상", "{} 수입할 때 내는 서류"]


class Extracted(BaseModel):
    """LLM이 낸 요건 목록."""

    requires: list[Requirement]


parser = argparse.ArgumentParser()
parser.add_argument("--out", required=True)
parser.add_argument("--max-cost", type=float, default=0.05)
args = parser.parse_args()
if inside_repo(Path(args.out)):
    sys.exit("[멈춤] 초안은 저장소 밖에 쓴다. 대조 뒤에 옮긴다")

settings = Settings()
prices = load_rules("pricing")
items = []
with read_pool(settings.database_url) as pool, get_usage_metadata_callback() as usage:
    rag = live_deps(settings, pool)
    find = partial(top_ranked, rag.search, rag.rerank)
    extract = structured(chat_model(settings), Extracted)
    for name, aliases in ITEMS.items():
        found = {e.unit_id: e for q in QUERIES for e in find(q.format(name), date.today())}
        block = evidence_block([e.model_dump(mode="json") for e in found.values()])
        requires = extract(render("item_graph", item=name, evidence=block)).requires
        items.append(Item(name=name, aliases=aliases, requires=requires))
        tokens = {
            m: {"in": t["input_tokens"], "out": t["output_tokens"]} for m, t in usage.usage_metadata.items()
        }
        spent = known_cost(cost_usd(tokens, prices))
        print(f"{name}: 요건 {len(items[-1].requires)}개, 근거 후보 {len(found)}개, 누계 ${spent:.4f}")
        if spent > args.max_cost:
            sys.exit(f"[멈춤] 상한 ${args.max_cost}를 넘었다")
graph = ItemGraph(reviewed="초안, 대조 전", items=items)
Path(args.out).write_text(
    yaml.safe_dump(graph.model_dump(), allow_unicode=True, sort_keys=False), encoding="utf-8"
)
print(f"초안: {args.out}")
