"""LLM 없이 문항의 질의 글을 그대로 넣어 검색 단계만 잰다 (설계 11절, 계획 3b·7c 측정). Voyage만 부른다.

실행: uv run python scripts/retrieval_check.py --tag <이름> --commit <커밋> --out eval/results
          [--set v2|rset_v1|rset_a2|<문항 파일>] [--leg rrf|vector|keyword] [--rerank on|off]
          [--article-cap N]
      uv run python scripts/retrieval_check.py --same <파일1> <파일2>   (두 결과의 상위 k 순위가 같은지)
결과: <out>/retrieval-<tag>.json. 층별·전체 요약(단위 기준, 조문 기준, 엄격 값의 R@k·MRR, 후보 포함률)과
      문항별 후보·순위 unit_id만 있고 글은 없다. 그래서 저장소(eval/results)에 둘 수 있다.
선택지:
  --set          문항 파일. 평가셋(set_v*.yaml)은 정답 근거가 있는 문항만, 검색 전용 평가셋(rset_*.yaml)은
                 모두 쓴다.
  --leg          후보를 만드는 다리. rrf(기본)는 제품의 검색 길 그대로다(벡터 + 키워드 RRF, 조문 지목 조회,
                 MARVIA_GRAPH=on이면 그래프). vector·keyword는 그 다리 하나의 순위만 본다.
  --rerank       리랭커로 다시 줄 세울지. off면 후보 순서가 곧 순위다.
  --article-cap  같은 조·항의 단위를 N개까지만 앞에 둔다(0 = 묶지 않음). 한 조문의 호들이 상위를
                 채우는지 본다.
그래프와 검색 길(직접·MCP)은 MARVIA_GRAPH·MARVIA_RAG_VIA로 고른다. MCP 길은 기본 설정으로만 잰다.
[왜] 에이전트 실행의 R@8은 모델이 쓴 질의에 따라 흔들린다(계획 4a-3 범위 0.38~0.46). 같은 질의 글을 넣으면
     검색 쪽 변화의 몫만 떼어 본다. 계산 규칙은 marvia.eval.retrieval에 있다.
하지 않는 일: 임베딩 모델 비교(색인을 따로 만들어야 한다), 답 채점.
"""

import argparse
import json
import sys
from pathlib import Path

from marvia.eval.dataset import CORPUS_UNITS, ROOT, file_sha256
from marvia.eval.retrieval import load_items, measure, summarize_layers
from marvia.eval.run import index_problem
from marvia.rag.index import read_units
from marvia.tools.rules import load_rules

parser = argparse.ArgumentParser()
parser.add_argument("--tag", default="")
parser.add_argument("--commit", default="")
parser.add_argument("--out", default="")
parser.add_argument("--set", default="v2", help="v1, v2, rset_v1, rset_a2 또는 문항 파일 경로")
parser.add_argument("--leg", choices=["rrf", "vector", "keyword"], default="rrf")
parser.add_argument("--rerank", choices=["on", "off"], default="on")
parser.add_argument(
    "--article-cap", type=int, default=0, help="같은 조·항의 단위를 앞에 둘 수 (0 = 묶지 않음)"
)
parser.add_argument("--same", nargs=2, help="두 결과 파일의 문항별 상위 k 순위가 같은지 본다")
args = parser.parse_args()

if args.same:
    a, b = (json.loads(Path(p).read_text(encoding="utf-8"))["rows"] for p in args.same)
    # [왜] 직접 길의 줄은 후보 전체의 순위를, MCP 길의 줄은 서버가 준 상위 n개만 갖는다. 상위 k끼리 견준다
    top = load_rules("eval")["retrieval_k"]
    diff = [x["id"] for x, y in zip(a, b, strict=True) if x["retrieved"][:top] != y["retrieved"][:top]]
    print("같음" if not diff else f"다름: {', '.join(diff)}")
    sys.exit(1 if diff else 0)
if not args.out or not args.tag:
    sys.exit("[멈춤] --out과 --tag가 있어야 한다")
target = Path(args.out) / f"retrieval-{args.tag}.json"
if target.exists():
    # [왜] 덮어쓰면 앞서 잰 결과를 잃는다 (평가 실행과 같은 규칙)
    sys.exit(f"[멈춤] 결과 파일이 이미 있다: {target}")
# 판 이름이면 eval/ 아래 파일이다. set_v1.yaml, rset_v1.yaml처럼 이름 꼴이 둘이다
named = [ROOT / "eval" / f"{stem}.yaml" for stem in (args.set, f"set_{args.set}")]
set_path = next((p for p in named if p.exists()), Path(args.set))
if not set_path.exists():
    sys.exit(f"[멈춤] 문항 파일이 없다: {args.set}")

# [왜] 키·DB가 필요한 모듈은 인자 검사 뒤에 읽는다
from marvia.config import Settings  # noqa: E402
from marvia.db import connect, read_pool  # noqa: E402
from marvia.rag import voyage  # noqa: E402
from marvia.rag.live import live_deps  # noqa: E402
from marvia.rag.search import leg_search  # noqa: E402

settings = Settings()
default_path = args.leg == "rrf" and args.rerank == "on" and not args.article_cap
if settings.rag_via == "mcp" and not default_path:
    # [왜] MCP 서버는 검색과 리랭커를 함께 돌려 상위 n개만 준다. 다리를 고르거나 리랭커를 끌 자리가 없다
    sys.exit("[멈춤] MARVIA_RAG_VIA=mcp는 기본 설정(--leg rrf --rerank on, 묶기 없음)으로만 잰다")
items, as_of, set_name = load_items(set_path)
k = load_rules("eval")["retrieval_k"]
with connect(settings.database_url) as conn, read_pool(settings.database_url) as pool:
    rag = live_deps(settings, pool)
    annex = conn.execute(
        "SELECT count(*) FROM corpus_units WHERE split_part(unit_id, '#', 2) LIKE '별표%'"
    ).fetchone()
    index_units = conn.execute("SELECT count(*) FROM corpus_units").fetchone()
    conn.commit()  # [왜] 읽은 뒤 트랜잭션을 닫는다 (R-066)

    def one_leg(query, day):
        # [왜] 검색은 부를 때마다 풀에서 연결을 빌린다 (live_deps의 search와 같다)
        with pool.connection() as leg_conn:
            return leg_search(
                leg_conn, query, lambda texts: voyage.embed(texts, settings, "query"), day, args.leg
            )

    rows = measure(
        items,
        as_of,
        rag.search if args.leg == "rrf" else one_leg,
        rag.rerank,
        rerank=args.rerank == "on",
        cap=args.article_cap,
        ranked=rag.ranked,  # MCP 길이면 순위는 서버가 준 상위 n개다. 직접 길이면 None
    )
for row in rows:
    print(row["id"], row["retrieved"][:3])
summary = summarize_layers(rows, k)
meta = {
    "tag": args.tag,
    "commit": args.commit,
    "set": set_name,
    "set_sha256": file_sha256(set_path),
    "as_of": as_of.isoformat(),
    "k": k,
    "leg": args.leg,
    "rerank": args.rerank,
    "article_cap": args.article_cap,
    "graph": settings.graph,
    "rag_via": settings.rag_via,
    "named_article": load_rules("rag")["search"]["named_article"],
    "embed_model": settings.embed_model,
    "rerank_model": settings.rerank_model,
    "annex_units": annex[0] if annex else 0,
    "index_units": index_units[0] if index_units else 0,
    "file_units": len(read_units(CORPUS_UNITS)),
}
# [왜] 색인이 단위 파일과 다르면(시험이 남긴 줄 등) 후보가 달라진다. 그 측정은 무효로 표시한다
meta["problems"] = [p for p in [index_problem(meta)] if p]
for problem in meta["problems"]:
    print(f"[무효] {problem}")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(
    json.dumps({"meta": meta, "summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
    encoding="utf-8",
)
print(json.dumps({"meta": meta, "summary": summary}, ensure_ascii=False))
