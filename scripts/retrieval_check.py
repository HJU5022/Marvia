"""LLM 없이 평가셋 질문 글을 그대로 질의로 넣어 검색 R@8·MRR을 잰다 (계획 3b 측정). Voyage만 부른다.

실행: uv run python scripts/retrieval_check.py --tag hybrid --commit <커밋> --out <저장소 밖 폴더>
      uv run python scripts/retrieval_check.py --same <파일1> <파일2>   두 결과의 순위가 같은지 (키 없음)
결과: <out>/retrieval-<tag>.json. 문항별 상위 unit_id와 요약만 있고 글은 없다.
[왜] 에이전트 실행의 R@8은 모델이 쓴 질의에 따라 흔들린다(계획 4a-3 범위 0.38~0.46). 같은 질문 글을 넣으면
     검색 쪽 변화(별표 단위, 그래프, MCP 길)의 몫만 떼어 본다. 설정은 MARVIA_GRAPH·MARVIA_RAG_VIA로 고른다.
[주의] 질문 속 화물 번호는 가린 토큰으로 바꿔 보낸다(평가셋 번호는 가공값이지만 규칙을 지킨다).
"""

import argparse
import json
import sys
from functools import partial
from pathlib import Path

from marvia.eval.dataset import load_set
from marvia.eval.metrics import mrr, recall_at_k
from marvia.eval.run import inside_repo
from marvia.identify.mask import mask_text
from marvia.tools.rules import load_rules

parser = argparse.ArgumentParser()
parser.add_argument("--tag", default="")
parser.add_argument("--commit", default="")
parser.add_argument("--out", default="")
parser.add_argument("--same", nargs=2, help="두 결과 파일의 문항별 retrieved가 같은지 본다")
args = parser.parse_args()

if args.same:
    a, b = (json.loads(Path(p).read_text(encoding="utf-8"))["rows"] for p in args.same)
    diff = [x["id"] for x, y in zip(a, b, strict=True) if x["retrieved"] != y["retrieved"]]
    print("같음" if not diff else f"다름: {', '.join(diff)}")
    sys.exit(1 if diff else 0)
if not args.out or inside_repo(Path(args.out)):
    sys.exit("[멈춤] --out은 저장소 밖 폴더여야 한다")

# [왜] 키·DB가 필요한 모듈은 인자 검사 뒤에 읽는다
from marvia.config import Settings  # noqa: E402
from marvia.db import connect  # noqa: E402
from marvia.graph.rag import top_ranked  # noqa: E402
from marvia.rag.live import live_deps  # noqa: E402

data = load_set()
items = {i.id: i for i in data.items if i.gold}
k = load_rules("eval")["retrieval_k"]
settings = Settings()
with connect(settings.database_url) as conn:
    rag = live_deps(settings, conn)
    find = rag.ranked or partial(top_ranked, rag.search, rag.rerank)
    annex = conn.execute(
        "SELECT count(*) FROM corpus_units WHERE split_part(unit_id, '#', 2) LIKE '별표%'"
    ).fetchone()
    rows = []
    for item in items.values():
        found = find(mask_text(item.question)[0], data.as_of)
        rows.append(
            {
                "id": item.id,
                "retrieved": [e.unit_id for e in found],
                # [주의] 리랭커 상위 k 안의 그래프 단위 수다. 평가 실행의 graph_added와 다르다
                #        (graph_added는 리랭커 앞 그래프 후보 수)
                "graph": sum(e.origin == "graph" for e in found),
            }
        )
        print(item.id, rows[-1]["retrieved"][:3])
summary = {"r_at_k": recall_at_k(rows, items, k), "mrr": mrr(rows, items), "k": k}
meta = {
    "tag": args.tag,
    "commit": args.commit,
    "graph": settings.graph,
    "rag_via": settings.rag_via,
    "annex_units": annex[0] if annex else 0,
}
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
(out / f"retrieval-{args.tag}.json").write_text(
    json.dumps({"meta": meta, "summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
    encoding="utf-8",
)
print(json.dumps({"meta": meta, "summary": summary}, ensure_ascii=False))
