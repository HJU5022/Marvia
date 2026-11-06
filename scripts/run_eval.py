"""평가셋(--set v1|v2)을 길(planner·agent) × 모델로 돌려 문항별 파생 값과 요약을 남긴다 (done 3.2·3.7).
run은 돈이 든다.

실행: uv run python scripts/run_eval.py run --out <저장소 밖 폴더> --commit <커밋> [--loops planner,agent]
          [--set v1|v2] [--models claude-haiku-5-5]
          [--ids R01,R12] [--limit 3] [--max-cost 1.0] [--dry-run]
      uv run python scripts/run_eval.py report [--set v1|v2] <결과.json> ...   (키 없음: 요약 표)
      uv run python scripts/run_eval.py sheet <결과.json> <결과.raw.json> --out <채점지.md>   (사람 채점 10건)
      uv run python scripts/run_eval.py agree eval/human_v1.yaml <ragas 점수.json>   (사람·LLM 채점 일치율)
      uv run python scripts/run_eval.py floors eval/results/<결과.json> --write   (CI 문 바닥값)
      uv run python scripts/run_eval.py domain-prompts --out <저장소 밖 폴더>   (범용 도구에게 줄 질문 글)
      uv run python scripts/run_eval.py domain <도구 폴더> ... --marvia <결과.raw.json>   (범용 도구 비교 표)
run은 먼저 어림 비용을 찍는다. --dry-run이면 거기서 멈추고 키도 DB도 쓰지 않는다.
키 두 개(MARVIA_ANTHROPIC_API_KEY, MARVIA_VOYAGE_API_KEY), 로컬 DB, 색인이 필요하다.
묻는 질문에는 권장안(시간 초과)으로, 승인 요청에는 거절로 답한다. 대화 기록은 메모리에만 둔다.
결과: <out>/<길>-<모델>.json(파생 값과 요약, 저장소에 올릴 수 있다),
      <out>/<길>-<모델>.raw.json(답 글, 저장소 밖에만 둔다).
하지 않는 일: ragas(scripts/ragas_score.py), 정답 확인(평가셋은 eval/set_v1.yaml).
"""

import argparse
import json
import os
import shutil
from datetime import date
from pathlib import Path

import yaml

from marvia.eval.dataset import ROOT, SETS, file_sha256, load_set
from marvia.eval.metrics import (
    agreement,
    cargo_count_lines,
    compare_table,
    domain_table,
    floors,
    gate_block,
    gate_uncovered,
    human_faithful,
    rag_table,
    ragas_means,
    set_view,
    spread,
    spread_groups,
    spread_table,
    summarize,
    unscored,
    with_base_behaviour,
)
from marvia.eval.run import (
    estimate,
    evaluate_item,
    existing_results,
    graph_setting_problem,
    inside_repo,
    preflight,
    result_name,
    run_problems,
    save_result,
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
# [왜] v2를 동결(f09fe11)해서 기본이 v2다. meta의 set·set_sha256이 어느 판인지 남긴다
run.add_argument("--set", choices=list(SETS), default="v2", help="평가셋 판 (eval/set_<판>.yaml)")
run.add_argument(
    "--graph",
    choices=["off", "on"],
    required=True,
    help="이 실행이 재려는 그래프 설정. 실제 설정(MARVIA_GRAPH)과 다르면 돈을 쓰기 전에 멈춘다",
)
run.add_argument("--tag", default="", help="결과 파일 이름 뒤에 붙일 말 (예: ctx는 맥락 문장 색인)")
report = sub.add_parser("report", help="결과 파일들을 지금 코드로 다시 채점해 표로 (키 없음)")
report.add_argument("files", nargs="+")
report.add_argument(
    "--set",
    choices=list(SETS),
    default="v2",
    help="이 판의 정답으로 다시 채점한다 (v1이면 behaviour_base로 센다)",
)
report.add_argument("--common", action="store_true", help="모든 파일에 있는 문항만으로 비교한다")
spread_cmd = sub.add_parser("spread", help="같은 설정의 결과 파일들을 지표마다 평균과 범위로 (키 없음)")
spread_cmd.add_argument("files", nargs="+")
spread_cmd.add_argument(
    "--set",
    choices=list(SETS),
    default="v2",
    help="이 판으로 채점한다 (v1이면 v2 실행을 behaviour_base로 센다)",
)
sheet = sub.add_parser("sheet", help="사람 채점지 (키 없음). 답 글이 들어 있어 저장소 밖에 쓴다")
sheet.add_argument("result")
sheet.add_argument("raw")
sheet.add_argument("--out", required=True)
agree = sub.add_parser("agree", help="사람 채점과 ragas faithfulness의 일치율 (키 없음)")
agree.add_argument("human", help="eval/human_v1.yaml")
agree.add_argument("scores", help="scripts/ragas_score.py가 쓴 점수 파일")
gate = sub.add_parser(
    "floors", help="저장소에 둔 결과 파일로 CI 문의 바닥값을 rules/eval.yaml 모양으로 찍는다"
)
gate.add_argument("result", help="저장소 안의 결과 파일 (예: eval/results/agent-claude-haiku-5-5.json)")
gate.add_argument(
    "--set", choices=list(SETS), help="이 문 파일을 채점할 평가셋 판. 없으면 rules/eval.yaml gate.set"
)
gate.add_argument("--ruling", help="바닥이 내려가거나 천장이 올라갈 때 남기는 판정 이유 (gate.rulings)")
gate.add_argument("--write", action="store_true", help="rules/eval.yaml의 gate 묶음을 바꾸거나 끝에 더한다")
prompts = sub.add_parser(
    "domain-prompts", help="범용 도구 비교 문항의 질문 글과 가공 화물 파일을 폴더에 쓴다"
)
prompts.add_argument("--out", required=True, help="저장소 밖 폴더. 범용 도구를 이 폴더에서 돌린다")
domain = sub.add_parser("domain", help="범용 도구 답 폴더(<문항 id>.txt)와 Marvia 답을 같은 자로 잰다")
domain.add_argument("folders", nargs="*", help="도구마다 한 폴더. 폴더 이름이 표의 도구 이름이다")
domain.add_argument("--marvia", help="scripts/run_eval.py run이 쓴 .raw.json")
args = parser.parse_args()

if args.command == "domain-prompts":
    if inside_repo(Path(args.out)):
        raise SystemExit(f"저장소 안에는 쓰지 않는다: {args.out}")
    data, out = load_set(), Path(args.out)
    (out / "unipass").mkdir(parents=True, exist_ok=True)
    # [왜] 범용 도구도 같은 가공 화물 상태를 본다. UNI-PASS 화면을 사용자가 옮겨 주는 경우와 같다
    for path in sorted((ROOT / "fixtures" / "unipass").glob("*.json")):
        shutil.copy(path, out / "unipass" / path.name)
    template = load_rules("eval")["domain"]["prompt"]
    picked = [i for i in data.items if i.domain]
    for item in picked:
        text = template.format(as_of=data.as_of.isoformat(), question=item.question)
        (out / f"{item.id}.txt").write_text(text, encoding="utf-8")
    print(f"{len(picked)}문항: {', '.join(i.id for i in picked)} → {out}")
    raise SystemExit(0)

if args.command == "domain":
    items = {i.id: i for i in load_set().items}
    answers = {}
    if args.marvia:
        raws = json.loads(Path(args.marvia).read_text(encoding="utf-8"))
        answers["Marvia"] = {r["id"]: r.get("answer", "") for r in raws if items[r["id"]].domain}
    for folder in map(Path, args.folders):
        answers[folder.name] = {p.stem: p.read_text(encoding="utf-8") for p in sorted(folder.glob("*.txt"))}
    print(domain_table(answers, items))
    raise SystemExit(0)

if args.command == "floors":
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    set_name = args.set or load_rules("eval").get("gate", {}).get("set", "v1")
    # [왜] 다른 평가셋 파일에서 돌린 결과를 이 판의 정답으로 채점하면 바닥값이 엉뚱하다
    if result["meta"]["set_sha256"] != file_sha256(SETS[set_name]):
        raise SystemExit(
            f"{args.result}는 평가셋 {set_name} 파일에서 돌린 결과가 아니다 (--set으로 판을 고른다)"
        )
    summary = summarize(
        result["rows"], {i.id: i for i in load_set(SETS[set_name]).items}, result["meta"]["k"]
    )
    new_floors = floors(summary, result["meta"]["k"], set_name)
    old_gate = load_rules("eval").get("gate", {})
    try:
        block = {
            "gate": gate_block(
                args.result, new_floors, old_gate, args.ruling, date.today().isoformat(), set_name
            )
        }
    except ValueError as error:
        if args.write:
            raise SystemExit(str(error)) from None
        block = {
            "gate": {"file": args.result, "set": set_name, "floors": new_floors}
        }  # 찍기만 할 때는 막지 않는다
    mark = "# CI 문 (done 3.6)"  # rules/eval.yaml에서 gate 묶음을 알아보는 표식
    text = (
        f"{mark}: 기준 실행(커밋 {result['meta']['commit']})에서 한 문항만큼 둔 바닥·천장값.\n"
        "# 새 기준 실행을 커밋할 때만 다시 만든다. 결과를 보고 값을 낮추지 않는다\n"
        + yaml.safe_dump(block, allow_unicode=True, sort_keys=False)
    )
    if not args.write:
        print(text, end="")
        raise SystemExit(0)
    rules = ROOT / "rules" / "eval.yaml"
    old = rules.read_text(encoding="utf-8")
    start = old.find(mark)
    if start < 0:
        new = old.rstrip("\n") + "\n\n" + text
    else:
        # [왜] gate 묶음 안에는 빈 줄이 없다. 묶음은 표식 줄부터 다음 빈 줄(없으면 파일 끝)까지다
        end = old.find("\n\n", start)
        new = old[:start] + text + (old[end + 1 :] if end >= 0 else "")
    rules.write_text(new, encoding="utf-8")
    print(f"rules/eval.yaml의 gate 묶음을 썼다 ({args.result})")
    raise SystemExit(0)

if args.command == "spread":
    results = [json.loads(Path(f).read_text(encoding="utf-8")) for f in args.files]
    try:
        groups = spread_groups(results)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    set_path = SETS[args.set]
    items = {i.id: i for i in load_set(set_path).items}
    blocks = []
    for group in groups.values():
        summaries = []
        for result in group:
            label, warn = set_view(result["meta"], result["rows"], args.set, file_sha256(set_path))
            tag = result["meta"].get("tag") or "(태그 없음)"
            if warn:
                # [왜] 다른 평가셋 파일의 결과이거나 behaviour_base가 없는 v2 실행은 이 판으로 셀 수 없다
                raise SystemExit(
                    f"{tag}: --set {args.set}로 채점할 수 없다 ({label}). "
                    "v2 실행을 v1로 세려면 줄에 behaviour_base가 있어야 한다"
                )
            rows = with_base_behaviour(result["rows"]) if args.set == "v1" else result["rows"]
            # [왜] 저장한 요약 대신 지금 지표 코드로 다시 센다 (report와 같다)
            summaries.append(summarize(rows, items, result["meta"]["k"]))
        blocks.append(spread_table(group, label, spread(summaries)) + f"\n\n실행 {len(group)}번")
    print("\n\n".join(blocks))
    raise SystemExit(0)

if args.command == "sheet":
    if inside_repo(Path(args.out)):
        raise SystemExit(f"답 글이 들어 있어 저장소 안에는 쓰지 않는다: {args.out}")
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    raws = {r["id"]: r for r in json.loads(Path(args.raw).read_text(encoding="utf-8"))}
    rows = {r["id"]: r for r in result["rows"]}
    picked = [i for i in load_set(SETS[load_rules("eval").get("gate", {}).get("set", "v1")]).items if i.human]
    meta = result["meta"]
    lines = [
        f"# 사람 채점지: {meta['loop']}-{meta['model']} (커밋 {meta['commit']})",
        "",
        "칸마다 1(그렇다), 0.5(일부), 0(아니다)을 적는다.",
        "- faithful: 답의 모든 주장이 인용한 조문이나 계산·화물 줄에 있다",
        "- correct: 답이 정답 글과 같은 내용이다",
        "",
    ]
    for item in picked:
        raw, row = raws.get(item.id, {}), rows.get(item.id, {})
        lines += [f"## {item.id} {item.question}", "", "답:", "", raw.get("answer", "(답 없음)"), ""]
        lines += [f"인용: {', '.join(row.get('cited', [])) or '없음'}", "", f"정답 글: {item.reference}", ""]
    lines += ["## 채점 (eval/human_v1.yaml에 옮긴다)", "", "```yaml", f"run: {Path(args.result).stem}"]
    lines += (
        ["grader:", "graded_on:", "grades:"]
        + [f"  {i.id}: {{faithful: , correct: }}" for i in picked]
        + ["```"]
    )
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(picked)}문항 채점지: {args.out}")
    raise SystemExit(0)

if args.command == "agree":
    cfg = load_rules("eval")
    grades = yaml.safe_load(Path(args.human).read_text(encoding="utf-8"))["grades"]
    score_file = json.loads(Path(args.scores).read_text(encoding="utf-8"))
    scores = score_file["scores"]
    # [왜] 계산·화물 줄이 맥락에 없던 옛 점수 파일(contexts_rule 없음)은
    #      계산 문항 충실도가 낮게 나온다. 일치율에서 뺀다
    rule = score_file.get("meta", {}).get("contexts_rule")
    calc_ids = set() if rule == cfg["ragas"]["contexts_rule"] else {i.id for i in load_set().items if i.calc}
    judge = {s["id"]: s.get("faithfulness") for s in scores if s["id"] not in calc_ids}
    try:
        human = human_faithful(grades)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    excluded = sorted(set(human) & calc_ids)
    human = {i: g for i, g in human.items() if i not in calc_ids}
    rate = agreement(human, judge, cfg["judge"]["buckets"])
    missing = unscored(human, judge)
    trusted = not missing and rate["value"] is not None and rate["value"] >= cfg["judge"]["min_agreement"]
    # [왜] 사람 채점은 충실도에만 있다. 일치율은 충실도의 것이라 정밀도·재현율 라벨은 늘 미확인이다 (R-063)
    unchecked = cfg["judge"]["unchecked_label"]
    means = ragas_means(scores, cfg["ragas"]["metrics"], calc_ids)
    # [왜] 출력의 모든 ragas 칸에 라벨을 단다 (옛 규칙 파일의 faithfulness_calc도 미확인)
    labels = {m: "LLM 채점, 사람 일치 확인" if m == "faithfulness" and trusted else unchecked for m in means}
    print(
        json.dumps(
            {
                "agreement": rate,
                "human_items": len(human),
                "missing": missing,
                "labels": labels,
                "calc_excluded": excluded,
                "contexts_rule": rule or "없음(옛 규칙: 계산 문항 충실도 제외)",
                "note": "계산·화물 줄은 ragas 맥락에 없어 낮게 나옴 (faithfulness_calc 따로, 일치율 제외)"
                if calc_ids
                else "계산·화물 줄이 맥락에 든 점수 파일: 모든 문항을 센다",
                "ragas": means,
            },
            ensure_ascii=False,
        )
    )
    raise SystemExit(0)

if args.command == "report":
    results = [json.loads(Path(f).read_text(encoding="utf-8")) for f in args.files]
    set_path = SETS[args.set]
    by_id = {i.id: i for i in load_set(set_path).items}
    common = set.intersection(*({r["id"] for r in result["rows"]} for result in results))
    for result in results:
        meta = result["meta"]
        # [왜] 같은 길·모델의 여러 실행(v2r1~v2r3)을 줄마다 가를 수 있게 태그를 붙인다
        name = f"{meta['loop']}-{meta['model']}" + (f"-{meta['tag']}" if meta.get("tag") else "")
        label, warn = set_view(result["meta"], result["rows"], args.set, file_sha256(set_path))
        print(f"- {name}: {label}")
        if warn:
            print(f"[주의] {name}: 평가셋이 바뀐 뒤의 결과가 아니다")
        # [왜] 저장한 요약 대신 지금 지표 코드로 다시 센다. 지표를 더하면 지난 실행도 새 지표로 보인다
        rows = [r for r in result["rows"] if not args.common or r["id"] in common]
        # [왜] v1 정답에는 찾지 못함이 없다. v2 실행 줄도 찾지 못함 규칙 없는 분류로 세야 v1 점수와 같다
        rows = with_base_behaviour(rows) if args.set == "v1" else rows
        result["summary"] = summarize(rows, by_id, result["meta"]["k"])
    print(compare_table(results))
    print()
    print(rag_table(results))
    print()
    print("\n".join(cargo_count_lines(results, ["R09", "R10"])))
    raise SystemExit(0)

set_path = SETS[args.set]
data = load_set(set_path)
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
from marvia.eval.dataset import CORPUS_UNITS  # noqa: E402
from marvia.graph.live import agent_deps  # noqa: E402
from marvia.rag.edges import build_edges  # noqa: E402
from marvia.rag.graphdb import connect_graph, graph_meta, units_sha256  # noqa: E402
from marvia.rag.index import read_units  # noqa: E402
from marvia.rag.items import items_sha256  # noqa: E402

# [왜] 평가는 늘 UNI-PASS 재생 데이터로 돈다. .env가 live여도 실제 API를 부르지 않는다 (계획 3b Task 7)
os.environ["MARVIA_UNIPASS_MODE"] = "replay"
# [왜] 평가의 graph_added는 리랭커 앞 그래프 후보 수여야 한다. mcp 길은 리랭커 뒤 상위 n개만 보이고 300자 넘는
#      질의를 거절한다. 두 길은 같은 상위 8개를 준다(계획 3b G7). 평가는 늘 direct로 돈다
os.environ["MARVIA_RAG_VIA"] = "direct"
# [왜] 실행 유효성(계획 3b 사전 등록)에 쓸 값: DB의 별표 단위 수, 단위 파일 sha, 그래프 메타
ANNEX_SQL = "SELECT count(*) FROM corpus_units WHERE split_part(unit_id, '#', 2) LIKE '별표%'"
faults = {i.id for i in items if i.fault}

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
by_id = {i.id: i for i in data.items}
k = load_rules("eval")["retrieval_k"]
spent = 0.0
# [왜] 인자와 실제 설정이 다르면 돈을 쓰기 전에 멈춘다. 모델 이름은 설정의 graph와 상관없다
mismatch = graph_setting_problem(args.graph, Settings().graph)
if mismatch:
    raise SystemExit(f"[멈춤] {mismatch}")
for model in models:
    settings = Settings(chat_model=model)
    with (
        connect(settings.database_url) as conn,
        # [왜] agent_deps는 감시 목록용 연결을 따로 받는다 (R-041). 평가 실행은 감시를 끄므로 쓰지 않는다
        psycopg.connect(settings.database_url, autocommit=True) as watch_conn,
    ):
        deps = agent_deps(settings, conn, watch_conn)
        annex_units = conn.execute(ANNEX_SQL).fetchone()[0]
        docs = sorted({p.name.split(".")[0] for p in CORPUS_UNITS.glob("*.jsonl")})
        graph = {}
        # [왜] 그래프가 지금 코드로 만든 간선 수와 같은지 대조한다. 켠 설정에서만 센다
        refers_expected = (
            len(build_edges(read_units(CORPUS_UNITS)).refers) if settings.graph == "on" else None
        )
        if settings.graph == "on":
            driver = connect_graph(settings)
            try:
                graph = graph_meta(driver, "main", docs)
            finally:
                driver.close()
        for loop in loops:
            rows, raws, halt = [], [], None
            meta = {
                "tag": args.tag,
                "set": data.version,
                "set_sha256": file_sha256(set_path),
                "commit": args.commit,
                "loop": loop,
                "model": model,
                "as_of": data.as_of.isoformat(),
                "run_on": date.today().isoformat(),
                "k": k,
                "price": prices.get(model),
                "graph": settings.graph,
                "graph_meta": graph,
                "annex_units": annex_units,
                "units_sha256": units_sha256(CORPUS_UNITS),
                "items_sha256": items_sha256(),
                "refers_expected": refers_expected,
                "unipass_mode": settings.unipass_mode,
                "rag_via": settings.rag_via,
            }
            name = result_name(loop, model, args.tag)
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
                # [왜] 문항마다 쓴다. Ctrl-C나 오류로 멈춰도 돈을 낸 줄이 남는다
                save_result(out, name, meta, summarize(rows, by_id, k), rows, raws)
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
            summary = summarize(rows, by_id, k)
            meta["problems"] = run_problems(meta, rows, summary, faults, gate_uncovered(rows, by_id))
            save_result(out, name, meta, summary, rows, raws)  # 문항이 하나도 없어도 빈 파일을 남긴다
            print(json.dumps(summary, ensure_ascii=False))
            for problem in meta["problems"]:
                print(f"[무효] {name}: {problem}")
            if halt:  # [왜] 이미 쓴 줄은 위에서 파일로 남겼다. 더 돌리지 않는다
                print(f"쓴 돈 약 ${spent:.4f}")
                raise SystemExit(1)
print(f"쓴 돈 약 ${spent:.4f}")
