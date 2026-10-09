"""Langfuse Cloud에 트레이스가 실제로 도착했는지 집계값만 읽어 docs/evidence/에 남기는 읽기 전용 스크립트.

왜: 저장소만 보는 채점자는 Langfuse 화면에 들어갈 수 없다. 그래서 개수·이름·버전·날짜 같은 집계만 뽑아
레포에 둔다 (EVAL_REPORT.md 1·2절 근거). 트레이스 입력·출력 원문은 읽지도 쓰지도 않는다.
화면에 B/L 가린 값, 모델 출력이 들어 있을 수 있어서다 (CLAUDE.md 보안 규칙, SDD 3.5).

쓰는 API (이 조직은 09-16 이후 생성이라 옛 /api/public/traces·scores·dataset runs는 410을 돌려준다):
  - GET /api/public/v2/metrics          관측(observation)·점수 집계
  - GET /api/public/v2/prompts          프롬프트 이름·버전 목록, 이름별 production 버전
  - GET /api/public/datasets            평가셋 이름·문항 수·실행 이름
  - GET /api/public/experiments         평가 실행(실험)별 시작·끝 시각·문항 수
키는 레포 .env의 LANGFUSE_HOST · LANGFUSE_PUBLIC_KEY · LANGFUSE_SECRET_KEY. 키는 출력하지 않는다.

실행: python scripts/eval/langfuse_evidence.py [--from 2026-09-01] [--to 2026-10-03]
결과: docs/evidence/langfuse_summary.json, docs/evidence/langfuse_summary.md
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "docs" / "evidence"

# 평가 실행기(evals/run_eval.py)는 문항마다 session_id를 "eval-<문항>"으로 붙인다 (evals/dataset.jsonl request.session_id)
EVAL_SESSION_PREFIX = "eval-"
GEN = {"column": "type", "operator": "=", "value": "GENERATION", "type": "string"}
TOOL = {"column": "type", "operator": "=", "value": "TOOL", "type": "string"}
EVAL_SESSION = {"column": "sessionId", "operator": "starts with", "value": EVAL_SESSION_PREFIX, "type": "string"}
COUNT = {"measure": "count", "aggregation": "count"}


def _ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _all_scores(c: "Client") -> list[dict] | dict:
    """v3 scores를 끝까지 넘겨 받는다. 이름·값·시각만 남긴다. 실패하면 {"error": ...}."""
    out, cursor = [], None
    for _ in range(100):  # 100개 x 100쪽이면 이 프로젝트 점수(780개)를 넉넉히 덮는다
        params = {"limit": 100, "fromTimestamp": c.since, "toTimestamp": c.until}
        if cursor:
            params["cursor"] = cursor
        page = c.get("/api/public/v3/scores", **params)
        if "error" in page:
            return page
        out += [{"name": x.get("name"), "value": x.get("value"), "timestamp": x.get("timestamp")} for x in page.get("data", [])]
        cursor = (page.get("meta") or {}).get("cursor")
        if not cursor or not page.get("data"):
            break
    return out


def _resets_soon(reset: str | None) -> bool:
    """429 응답의 x-ratelimit-reset(날짜 글)이 60초 안이면 True. 못 읽으면 기다려 본다."""
    if not reset:
        return True
    try:
        when = datetime.strptime(reset.split(" GMT")[0], "%a %b %d %Y %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (when - datetime.now(timezone.utc)).total_seconds() < 60


class Client:
    """Langfuse 공개 API를 Basic 인증으로 부르는 얇은 래퍼. 실패해도 예외 대신 {"error": ...}를 돌려준다."""

    def __init__(self, host: str, public_key: str, secret_key: str, since: str, until: str):
        self.host = host.rstrip("/")
        self.http = httpx.Client(auth=(public_key, secret_key), timeout=60)
        self.since, self.until = since, until

    def get(self, path: str, **params) -> dict:
        # 429는 한도가 1분 안에 풀릴 때만 기다렸다 다시 부른다. metrics API는 이 계정에서 하루 100번 한도라
        # (x-ratelimit-limit 100, reset 다음 날) 길게 기다려도 소용없다. 그때는 오류로 돌려주고
        # main()이 이전 실행에서 받은 값을 그대로 둔다(_merge_previous)
        for attempt in range(3):
            try:
                r = self.http.get(self.host + path, params=params or None)
            except httpx.HTTPError as e:
                return {"error": f"{type(e).__name__}"}
            if r.status_code != 429 or not _resets_soon(r.headers.get("x-ratelimit-reset")):
                break
            time.sleep(15 * (attempt + 1))
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "path": path}
        return r.json()

    def metrics(self, view: str, metrics: list[dict], dimensions: list[str] = (), filters: list[dict] = (),
                granularity: str | None = None, since: str | None = None, until: str | None = None) -> list[dict] | dict:
        """v2 metrics 질의 하나. 집계 행 목록을 돌려준다. since·until을 주면 그 구간만 센다."""
        q = {
            "view": view,
            "fromTimestamp": since or self.since,
            "toTimestamp": until or self.until,
            "dimensions": [{"field": d} for d in dimensions],
            "metrics": metrics,
            "filters": list(filters),
        }
        if granularity:
            q["timeDimension"] = {"granularity": granularity}
        res = self.get("/api/public/v2/metrics", query=json.dumps(q))
        return res.get("data", res) if isinstance(res, dict) else res


def _num(x):
    """metrics API는 정수를 문자열로 준다. 숫자로 바꾸고 실수는 6자리로 자른다."""
    if isinstance(x, str):
        try:
            return int(x)
        except ValueError:
            try:
                return round(float(x), 6)
            except ValueError:
                return x
    if isinstance(x, float):
        return round(x, 6)
    return x


def _clean(rows):
    if not isinstance(rows, list):
        return rows
    return [{k: _num(v) for k, v in r.items()} for r in rows]


def _nonzero(rows):
    """날짜별 집계는 호출이 없던 날도 0으로 채워 온다. 기록이 있는 날만 남긴다."""
    if not isinstance(rows, list):
        return rows
    return [r for r in rows if r.get("count_count")]


def _fold_eval_names(rows):
    """'eval N01' 같은 문항별 이름은 30개로 흩어져 읽기 어렵다. 'eval <문항>'으로 합친다."""
    if not isinstance(rows, list):
        return rows
    out: dict[str, int] = {}
    for r in rows:
        name = r.get("name") or "(이름 없음)"
        key = "eval <문항>" if name.startswith("eval ") else name
        out[key] = out.get(key, 0) + int(r.get("count_count", 0))
    return [{"name": k, "count": v} for k, v in sorted(out.items(), key=lambda kv: -kv[1])]


def collect(c: Client) -> dict:
    """집계를 모은다. 각 항목은 독립이라 하나가 실패해도 나머지는 남는다."""
    gen_metrics = [COUNT, {"measure": "inputTokens", "aggregation": "sum"},
                   {"measure": "outputTokens", "aggregation": "sum"}, {"measure": "totalCost", "aggregation": "sum"},
                   {"measure": "latency", "aggregation": "p50"}, {"measure": "latency", "aggregation": "p95"}]
    s: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": c.host,
        "window": {"from": c.since, "to": c.until},
        "observations_by_type": _clean(c.metrics("observations", [COUNT], ["type"])),
        "observations_by_environment": _clean(c.metrics("observations", [COUNT], ["environment"])),
        "observations_by_name": _fold_eval_names(_clean(c.metrics("observations", [COUNT], ["name"]))),
        "generations_total": _clean(c.metrics("observations", gen_metrics, filters=[GEN])),
        "generations_by_model": _clean(c.metrics("observations", gen_metrics, ["providedModelName"], [GEN])),
        "generations_by_prompt": _clean(c.metrics("observations", [COUNT], ["promptName", "promptVersion"], [GEN])),
        "generations_by_day": _nonzero(_clean(c.metrics("observations", [COUNT, {"measure": "totalCost", "aggregation": "sum"}],
                                               filters=[GEN], granularity="day"))),
        "generations_eval_sessions": _clean(c.metrics("observations", gen_metrics, filters=[GEN, EVAL_SESSION])),
        "tool_observations_by_name": _clean(c.metrics("observations", [COUNT, {"measure": "latency", "aggregation": "p95"}],
                                                      ["name"], [TOOL])),
        "tool_observations_by_day": _nonzero(_clean(c.metrics("observations", [COUNT], filters=[TOOL], granularity="day"))),
        "tool_observations_eval_sessions": _clean(c.metrics("observations", [COUNT], filters=[TOOL, EVAL_SESSION])),
        "distinct_ids": _clean(c.metrics("observations", [{"measure": "uniqueUserIds", "aggregation": "count"},
                                                           {"measure": "uniqueSessionIds", "aggregation": "count"},
                                                           {"measure": "traceId", "aggregation": "uniq"}])),
        "scores_by_name": _clean(c.metrics("scores-numeric", [COUNT, {"measure": "value", "aggregation": "avg"}], ["name"])),
    }

    # 프롬프트: 이름·버전 목록과 이름별 production 버전. 본문(prompt)은 받지만 저장하지 않는다
    prompts = c.get("/api/public/v2/prompts", limit=50)
    plist = []
    for p in prompts.get("data", []) if isinstance(prompts, dict) else []:
        prod = c.get(f"/api/public/v2/prompts/{p['name']}", label="production")
        plist.append({
            "name": p["name"],
            "versions": p.get("versions"),
            "production_version": prod.get("version"),
            "production_created_at": prod.get("createdAt"),
            "production_commit_message": prod.get("commitMessage"),
            "last_updated_at": p.get("lastUpdatedAt"),
        })
    s["prompts"] = plist or prompts

    # 평가셋과 실행 이름. 문항 ID만 쓰고 문항 내용(입력·정답)은 레포 evals/dataset.jsonl이 원본이다
    ds = c.get("/api/public/datasets")
    s["datasets"] = [
        {"name": d["name"], "item_count": len(d.get("items") or []), "created_at": d.get("createdAt"),
         "run_count": len(d.get("runs") or []), "runs": d.get("runs")}
        for d in (ds.get("data", []) if isinstance(ds, dict) else [])
    ] or ds

    ex = c.get("/api/public/experiments", fromStartTime=c.since, limit=100)
    s["experiments"] = [
        {"name": e.get("name"), "start": e.get("startTime"), "end": e.get("endTime"), "item_count": e.get("itemCount")}
        for e in (ex.get("data", []) if isinstance(ex, dict) else [])
    ] or ex
    # Dataset에는 실행 이름이 있는데 Experiments 목록에는 없는 것 (같은 이름으로 두 번 돈 실행 등). 숫자가 다른 이유를 남긴다
    if isinstance(s["datasets"], list) and isinstance(s["experiments"], list):
        ex_names = {e["name"] for e in s["experiments"]}
        runs = [r for d in s["datasets"] for r in (d.get("runs") or [])]
        s["dataset_runs_not_in_experiments"] = sorted({r for r in runs if r not in ex_names})
        s["dataset_runs_duplicate_names"] = sorted({r for r in runs if runs.count(r) > 1})

    # 실험(실행)별 점수: 평가 실행기는 한 실행의 score를 모두 실행 끝 시각으로 남긴다(score timestamp =
    # 실험 endTime). 그래서 v3 scores를 전부 받아 실행 시작 ~ 끝 + 5초 구간으로 나눠 센다. 실행은 한 번에 하나씩
    # 순서대로 돌아서(evals/run_eval.py max_concurrency=1) 구간이 겹치지 않는다. metrics API(하루 100번 한도)를
    # 실행마다 부르지 않으려고 v3 scores 목록(100개씩)을 쓴다. 점수 값만 쓰고 트레이스 내용은 읽지 않는다.
    # 예전 실행은 결과 JSON이 레포에 없어서 EVAL_REPORT.md 4절 전후 비교의 근거로 쓴다
    if isinstance(s["experiments"], list):
        scores = _all_scores(c)
        for e in s["experiments"]:
            if not (e.get("start") and e.get("end")) or isinstance(scores, dict):
                e["scores"] = scores if isinstance(scores, dict) else None
                continue
            lo = _ts(e["start"])
            hi = _ts(e["end"]) + timedelta(seconds=5)
            agg: dict[str, dict] = {}
            for sc in scores:
                if lo <= _ts(sc["timestamp"]) <= hi and isinstance(sc.get("value"), (int, float)):
                    a = agg.setdefault(sc["name"], {"n": 0, "pass": 0})
                    a["n"] += 1
                    a["pass"] += sc["value"]
            e["scores"] = agg

    # 옛 API가 막혀 있다는 사실도 근거로 남긴다 (EVAL_REPORT.md 1절)
    s["legacy_endpoints"] = {
        p: c.get(p, limit=1).get("error") for p in ("/api/public/traces", "/api/public/scores", "/api/public/sessions")
    }
    return s


def _md_table(rows, cols: list[tuple[str, str]]) -> str:
    if not isinstance(rows, list) or not rows:
        return f"(조회 실패: {rows})\n"
    head = "| " + " | ".join(h for _, h in cols) + " |\n|" + "---|" * len(cols) + "\n"
    body = "".join("| " + " | ".join(str(r.get(k, "")) for k, _ in cols) + " |\n" for r in rows)
    return head + body


SCORE_NAMES = ["exact_match", "verdict_match", "schema_pass", "customs_explanation"]


def _fmt_score(e: dict, name: str) -> str:
    sc = (e.get("scores") or {}).get(name) if isinstance(e.get("scores"), dict) else None
    if not sc:
        return ""
    v = sc.get("pass")
    return f"{int(v) if isinstance(v, (int, float)) and float(v).is_integer() else v}/{sc.get('n')}"


def to_markdown(s: dict) -> str:
    """사람이 읽는 요약. 숫자는 JSON과 같은 값이다."""
    by_type = {r.get("type"): r.get("count_count") for r in s["observations_by_type"]} if isinstance(s["observations_by_type"], list) else {}
    md = [
        "# Langfuse 도착 기록 (집계)",
        "",
        f"`python scripts/eval/langfuse_evidence.py`가 Langfuse Cloud 공개 API에서 읽은 집계값이다. 생성 {s['generated_at']} (UTC), 기간 {s['window']['from']} ~ {s['window']['to']}.",
        "트레이스 입력·출력 원문은 담지 않는다. 같은 값이 `langfuse_summary.json`에 있다.",
        "",
        (f"이번 실행에서 API 한도(429)로 못 받아 이전 실행 값을 그대로 둔 항목과 그 값을 받은 시각: {s['carried_over']}" if s.get("carried_over") else ""),
        "",
        "## 관측 종류별 개수",
        "",
        _md_table(s["observations_by_type"], [("type", "종류"), ("count_count", "개수")]),
        f"GENERATION은 LLM 호출, TOOL은 MCP 도구 호출(services/mcp_client.py가 남김), EVALUATOR·SPAN 대부분은 평가 실험(run_experiment)이 문항마다 연 기록이다. TOOL {by_type.get('TOOL', '?')}개가 MCP 도구 span 도착 근거다.",
        "",
        "## 환경별 (평가 실험 vs 그 밖)",
        "",
        _md_table(s["observations_by_environment"], [("environment", "environment"), ("count_count", "개수")]),
        "sdk-experiment는 평가 실행기가 남긴 것, default는 서버·스크립트 호출이다.",
        "",
        "## LLM 호출 합계",
        "",
        _md_table(s["generations_total"], [("count_count", "호출"), ("sum_inputTokens", "입력 토큰"), ("sum_outputTokens", "출력 토큰"),
                                          ("sum_totalCost", "비용 합 (USD)"), ("p50_latency", "p50 지연 (ms)"), ("p95_latency", "p95 지연 (ms)")]),
        "평가 세션(session_id가 eval-로 시작)만:",
        "",
        _md_table(s["generations_eval_sessions"], [("count_count", "호출"), ("sum_inputTokens", "입력 토큰"), ("sum_outputTokens", "출력 토큰"),
                                                  ("sum_totalCost", "비용 합 (USD)"), ("p50_latency", "p50 지연 (ms)"), ("p95_latency", "p95 지연 (ms)")]),
        "## 모델별 LLM 호출",
        "",
        _md_table(s["generations_by_model"], [("providedModelName", "모델"), ("count_count", "호출"), ("sum_inputTokens", "입력 토큰"),
                                             ("sum_outputTokens", "출력 토큰"), ("sum_totalCost", "비용 합 (USD)"), ("p95_latency", "p95 지연 (ms)")]),
        "## 프롬프트 이름·버전별 LLM 호출",
        "",
        _md_table(s["generations_by_prompt"], [("promptName", "프롬프트"), ("promptVersion", "버전"), ("count_count", "호출")]),
        "프롬프트가 비어 있는 행은 Langfuse Prompt를 못 읽고 레포 파일(local)로 돈 호출이거나 프롬프트를 쓰지 않는 호출이다.",
        "",
        "## 날짜별 LLM 호출",
        "",
        _md_table(s["generations_by_day"], [("time_dimension", "날짜 (UTC)"), ("count_count", "호출"), ("sum_totalCost", "비용 합 (USD)")]),
        "## MCP 도구 호출 (TOOL)",
        "",
        _md_table(s["tool_observations_by_name"], [("name", "도구"), ("count_count", "호출"), ("p95_latency", "p95 지연 (ms)")]),
        _md_table(s["tool_observations_by_day"], [("time_dimension", "날짜 (UTC)"), ("count_count", "호출")]),
        "## 관측 이름별 개수",
        "",
        _md_table(s["observations_by_name"], [("name", "이름"), ("count", "개수")]),
        "## 고유 ID 수",
        "",
        _md_table(s["distinct_ids"], [("count_uniqueUserIds", "user_id"), ("count_uniqueSessionIds", "session_id"), ("uniq_traceId", "trace")]),
        "## 평가 점수 (Dataset 실험이 남긴 score)",
        "",
        _md_table(s["scores_by_name"], [("name", "점수 이름"), ("count_count", "개수"), ("avg_value", "평균")]),
        "기간 전체 실험(모델·프롬프트가 다른 실행 포함)을 합친 평균이라 한 실행의 성적이 아니다. 실행별 수치는 evals/results/*.json.",
        "",
        "## Prompt Management",
        "",
        _md_table(s["prompts"], [("name", "프롬프트"), ("versions", "버전 목록"), ("production_version", "production"),
                                 ("production_created_at", "production 등록"), ("production_commit_message", "커밋 메시지")]),
        "## Dataset",
        "",
        _md_table(s["datasets"], [("name", "이름"), ("item_count", "문항"), ("created_at", "생성"), ("run_count", "실행 수")]),
        "## 평가 실험 (Experiments)",
        "",
        _md_table([{**e, **{k: _fmt_score(e, k) for k in SCORE_NAMES}} for e in s["experiments"]] if isinstance(s["experiments"], list) else s["experiments"],
                  [("name", "실행 이름"), ("start", "시작 (UTC)"), ("item_count", "문항")] + [(k, k) for k in SCORE_NAMES]),
        "점수 칸은 맞은 수/채점한 수다. 실행 구간(시작 ~ 끝 + 5초)에 남은 score를 metrics API로 센 값이다.",
        "",
        f"Dataset 실행 이름 중 Experiments 목록에 없는 것: {s.get('dataset_runs_not_in_experiments')}, 이름이 겹친 실행: {s.get('dataset_runs_duplicate_names')}",
        "",
        "## 막힌 옛 API",
        "",
        "".join(f"- `{k}`: {v}\n" for k, v in s["legacy_endpoints"].items()),
    ]
    return "\n".join(md) + "\n"


def _failed(v) -> bool:
    return isinstance(v, dict) and "error" in v


def _merge_previous(new: dict, path: Path) -> dict:
    """이번에 못 받은 항목(429 등)은 이전 실행 파일의 값을 그대로 두고, 어느 항목이 언제 값인지 적는다.

    metrics API 한도(하루 100번) 때문에 한 번에 모든 항목을 다시 받지 못할 수 있다. 값을 지어내지 않고,
    이전에 실제로 받은 값만 옮긴다. carried_over에 항목 이름과 그 값을 받은 시각이 남는다.
    """
    if not path.exists():
        return new
    old = json.loads(path.read_text(encoding="utf-8"))
    carried = dict(old.get("carried_over") or {})
    for key, value in new.items():
        if _failed(value) and key in old and not _failed(old[key]):
            new[key] = old[key]
            carried[key] = carried.get(key) or old.get("generated_at")
        elif key in carried:
            carried.pop(key)
    # 실행별 점수: 이번에 못 받은 실행은 이전 값을 쓴다
    if isinstance(new.get("experiments"), list) and isinstance(old.get("experiments"), list):
        prev = {e.get("name"): e for e in old["experiments"]}
        for e in new["experiments"]:
            if not e.get("scores") and (prev.get(e.get("name")) or {}).get("scores"):
                e["scores"] = prev[e["name"]]["scores"]
                carried.setdefault("experiments.scores", old.get("generated_at"))
    if carried:
        new["carried_over"] = carried
    return new


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="since", default="2026-09-01")
    ap.add_argument("--to", dest="until", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()
    env = dotenv_values(ROOT / ".env")
    host = env.get("LANGFUSE_HOST") or env.get("LANGFUSE_BASE_URL")
    if not (host and env.get("LANGFUSE_PUBLIC_KEY") and env.get("LANGFUSE_SECRET_KEY")):
        raise SystemExit(".env에 LANGFUSE_HOST · LANGFUSE_PUBLIC_KEY · LANGFUSE_SECRET_KEY가 필요하다")
    until = args.until if "T" in args.until else f"{args.until}T23:59:59Z"
    c = Client(host, env["LANGFUSE_PUBLIC_KEY"], env["LANGFUSE_SECRET_KEY"], f"{args.since}T00:00:00Z", until)
    summary = _merge_previous(collect(c), OUT_DIR / "langfuse_summary.json")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "langfuse_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "langfuse_summary.md").write_text(to_markdown(summary), encoding="utf-8")
    print(f"썼다: {OUT_DIR / 'langfuse_summary.json'}, {OUT_DIR / 'langfuse_summary.md'}")


if __name__ == "__main__":
    main()
