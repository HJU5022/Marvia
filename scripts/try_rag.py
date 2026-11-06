"""질문 하나로 RAG 서브그래프를 돌려 근거 묶음을 본다 (계획 2 Task 10). 키·로컬 DB·색인 필요, 질문당 약 $0.01.

실행: uv run python scripts/try_rag.py "같은 제품을 다시 수입하면 정밀검사가 면제되나요?"
"""

import sys
from datetime import date

from marvia.config import Settings
from marvia.db import read_pool
from marvia.graph.rag import build_rag_graph
from marvia.rag.live import live_deps

settings = Settings()
with read_pool(settings.database_url) as pool:
    out = build_rag_graph(live_deps(settings, pool)).invoke({"question": sys.argv[1], "as_of": date.today()})

print(
    "질문 유형:",
    out["question_type"],
    "/ 마지막 질의:",
    out["search_query"],
    "/ 고쳐 쓴 횟수:",
    out["rewrites"],
)
print("충분" if out["sufficient"] else f"부족: {out['missing']}")
for e in out["evidence"]:
    print(f"{e['score']:.3f}  {e['unit_id']}  {e['heading']}")
