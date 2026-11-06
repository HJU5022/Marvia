"""평가셋 v1을 길(planner·agent) × 모델로 돌려 문항별 파생 값과 요약을 남긴다 (done 3.2·3.7). run은 돈이 든다.

실행: uv run python scripts/run_eval.py run --out <저장소 밖 폴더> --commit <커밋> [--loops planner,agent]
          [--models claude-haiku-5-5] [--ids R01,R12] [--limit 3] [--max-cost 1.0] [--dry-run]
      uv run python scripts/run_eval.py report <결과.json> ...   (키 없음: 요약 표를 마크다운으로)
run은 먼저 어림 비용을 찍는다. --dry-run이면 거기서 멈추고 키도 DB도 쓰지 않는다.
키 두 개(MARVIA_ANTHROPIC_API_KEY, MARVIA_VOYAGE_API_KEY), 로컬 DB, 색인이 필요하다.
묻는 질문에는 권장안(시간 초과)으로, 승인 요청에는 거절로 답한다. 대화 기록은 메모리에만 둔다.
결과: <out>/<길>-<모델>.json(파생 값과 요약, 저장소에 올릴 수 있다),
      <out>/<길>-<모델>.raw.json(답 글, 저장소 밖에만 둔다).
하지 않는 일: ragas(scripts/ragas_score.py), 정답 확인(평가셋은 eval/set_v1.yaml).
"""

import argparse
import json
from datetime import date
from pathlib import Path

from marvia.eval.dataset import SET_PATH, file_sha256, load_set
from marvia.eval.metrics import compare_table, summarize
from marvia.eval.run import (
    estimate,
    evaluate_item,
    existing_results,
    inside_repo,
    preflight,
    result_name,
    stop_reason,
)
from marvia.tools.rules import load_rules

parser = argparse.ArgumentParser(description="평가셋 실행과 요약")
sub = parser.add_subparsers(dest="command", required=True)
run = sub.add_parser("run", help="평가셋을 돌린다 (돈이 든다)")
run.add_argument("--out", required=True, help="결과 폴더. 저장소 밖(scratch)에 둔다")
run.add_argument("--commit", required=True, help="돌린 코드의 커밋 (내보낸 사본에는 .git이 없다)")
run.add_argument("--loops", default="planner,agent")
run.add_argument("--models", default="claude-haiku-5-5")
run.add_argument("--ids", default="", help="이 문항만 (쉼표로)")
run.add_argument("--limit", type=int, default=0, help="앞에서 이만큼만")
run.add_argument("--max-cost", type=float, default=load_rules("eval")["run"]["max_cost_usd"])
run.add_argument("--dry-run", action="store_true", help="어림 비용만 찍고 끝낸다")
run.add_argument("--tag", default="", help="결과 파일 이름 뒤에 붙일 말 (예: ctx는 맥락 문장 색인)")
report = sub.add_parser("report", help="결과 파일들을 지금 코드로 다시 채점해 표로 (키 없음)")
report.add_argument("files", nargs="+")
report.add_argument("--common", action="store_true", help="모든 파일에 있는 문항만으로 비교한다")
args = parser.parse_args()

if args.command == "report":
    results = [json.loads(Path(f).read_text(encoding="utf-8")) for f in args.files]
    by_id = {i.id: i for i in load_set().items}
    common = set.intersection(*({r["id"] for r in result["rows"]} for result in results))
    for result in results:
        if result["meta"]["set_sha256"] != file_sha256(SET_PATH):
            print(
                f"[주의] {result['meta']['loop']}-{result['meta']['model']}: 평가셋이 바뀐 뒤의 결과가 아니다"
            )
        # [왜] 저장한 요약 대신 지금 지표 코드로 다시 센다. 지표를 더하면 지난 실행도 새 지표로 보인다
        rows = [r for r in result["rows"] if not args.common or r["id"] in common]
        result["summary"] = summarize(rows, by_id, result["meta"]["k"])
    print(compare_table(results))
    raise SystemExit(0)

data = load_set()
items = [i for i in data.items if not args.ids or i.id in args.ids.split(",")]
items = items[: args.limit] if args.limit else items
loops, models = args.loops.split(","), args.models.split(",")
prices = load_rules("pricing")
plan = estimate(len(items), loops, models, prices)
for line in plan:
    print(f"어림 비용 {line['loop']} {line['model']} {line['items']}문항: ${line['usd']}")
print(f"합계 약 ${sum(line['usd'] or 0 for line in plan):.3f} (실행 상한 ${args.max_cost})")
problems = preflight(len(items), loops, models, prices, args.max_cost)
problems += [
    f"결과 파일이 이미 있다: {path}" for path in existing_results(Path(args.out), loops, models, args.tag)
]
if inside_repo(Path(args.out)):
    problems.append(f"--out은 저장소 밖이어야 한다: {args.out}")
for problem in problems:
    print(f"[멈춤] {problem}")
if problems:
    raise SystemExit(1)
if args.dry_run:
    raise SystemExit(0)

# [왜] 키·DB가 필요한 모듈은 dry-run 뒤에 읽는다. 어림 비용은 키 없이 볼 수 있다
import psycopg  # noqa: E402

from marvia.config import Settings  # noqa: E402
from marvia.db import connect  # noqa: E402
from marvia.graph.live import agent_deps  # noqa: E402

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
by_id = {i.id: i for i in data.items}
k = load_rules("eval")["retrieval_k"]
spent = 0.0
for model in models:
    settings = Settings(chat_model=model)
    with (
        connect(settings.database_url) as conn,
        # [왜] agent_deps는 감시 목록용 연결을 따로 받는다 (R-041). 평가 실행은 감시를 끄므로 쓰지 않는다
        psycopg.connect(settings.database_url, autocommit=True) as watch_conn,
    ):
        deps = agent_deps(settings, conn, watch_conn)
        for loop in loops:
            rows, raws, halt = [], [], None
            for item in items:
                if spent >= args.max_cost:
                    print(f"상한 ${args.max_cost}에 닿아 {item.id}부터 돌리지 않았다")
                    break
                row, raw = evaluate_item(deps, item, loop, data.as_of, prices)
                row["model"] = model
                rows.append(row)
                raws.append(raw)
                spent += row["cost_usd"] or 0
                halt = stop_reason(row)
                print(
                    loop,
                    model,
                    item.id,
                    row["behaviour"],
                    row["real_llm_calls"],
                    row["cost_usd"],
                    row["seconds"],
                )
                if halt:
                    print(f"[멈춤] {item.id}: {halt}")
                    break
            meta = {
                "tag": args.tag,
                "set": data.version,
                "set_sha256": file_sha256(SET_PATH),
                "commit": args.commit,
                "loop": loop,
                "model": model,
                "as_of": data.as_of.isoformat(),
                "run_on": date.today().isoformat(),
                "k": k,
                "price": prices.get(model),
            }
            result = {"meta": meta, "summary": summarize(rows, by_id, k), "rows": rows}
            name = result_name(loop, model, args.tag)
            (out / f"{name}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            (out / f"{name}.raw.json").write_text(
                json.dumps(raws, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            print(json.dumps(result["summary"], ensure_ascii=False))
            if halt:  # [왜] 이미 쓴 줄은 위에서 파일로 남겼다. 더 돌리지 않는다
                print(f"쓴 돈 약 ${spent:.4f}")
                raise SystemExit(1)
print(f"쓴 돈 약 ${spent:.4f}")
