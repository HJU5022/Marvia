"""평가 실행기 (D8, SDD 5.12, PRD 8절).

    python -m evals.run_eval --config a     # 규칙만 (evals/baseline_rules.py)
    python -m evals.run_eval --config b     # 규칙 + LLM 모델 A (.env MODEL_A)
    python -m evals.run_eval --config c     # 규칙 + LLM 모델 B (.env MODEL_B)

하는 일:
  1. dataset.jsonl 30건을 문항마다 REPLAY 재생 파일로 풀고 (evals/replay_fixtures.py)
  2. 시계를 문항의 clock(09-22 12:00)으로 맞춘 채 실제 라우터(run_agent)에 요청을 넣고
  3. 응답을 정답과 대조해 축별 점수와 게이트를 계산해 evals/results/<config>.json에 쓴다
서버 코드는 고치지 않는다. 바꿔 끼우는 것(판정기, 재생 transport, 시계)은 이 실행 안에서만 유효하다.

외부 API는 키 없이 재생한다. (b)(c)만 진짜 LLM을 부른다(비용이 든다). (a)는 LLM을 한 번도 부르지 않는다.
DB(DATABASE_URL)는 쓰지 않는다. 조회 이력 저장은 실패해도 응답이 나가게 돼 있다 (routers/agent.py _logged).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from freezegun import freeze_time

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "dataset.jsonl"
RESULTS = ROOT / "evals" / "results"

CONFIGS = {"a": "규칙만 (baseline_rules)", "b": "규칙 + LLM 모델 A (MODEL_A)", "c": "규칙 + LLM 모델 B (MODEL_B)"}

# 게이트 (PRD 8절, SDD 5.12). 하나라도 걸리면 배포하지 않는다
SCHEMA_PASS_GATE = 0.95

# 시계를 멈출 때 제외할 모듈. 트레이스·토큰 발급은 진짜 시각을 써야 Langfuse에서 찾기 쉽고 인증이 안 꼬인다
FREEZE_IGNORE = ["langfuse", "opentelemetry", "google.auth"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Marvia 평가셋 30건 실행과 채점")
    parser.add_argument("--config", choices=sorted(CONFIGS), required=True)
    parser.add_argument("--only", nargs="*", help="이 id만 돌린다 (예: N01 B03). 결과 파일은 쓰지 않는다")
    args = parser.parse_args()

    _setup_env()
    # 환경변수를 정한 뒤에 import한다. 클라이언트가 만들어질 때 REPLAY_MODE를 읽는다
    from evals.replay_fixtures import use_error_replay
    use_error_replay()
    _setup_config(args.config)

    records = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.only:
        records = [r for r in records if r["id"] in args.only]

    work = Path(tempfile.mkdtemp(prefix="marvia_eval_"))
    try:
        rows = [_run_one(rec, args.config, work) for rec in records]
    finally:
        shutil.rmtree(work, ignore_errors=True)

    summary = score(rows)
    _print(args.config, rows, summary)
    if not args.only:
        RESULTS.mkdir(parents=True, exist_ok=True)
        result = {
            "config": args.config,
            "description": CONFIGS[args.config],
            "model": os.environ.get("MODEL_A") if args.config != "a" else "baseline/rules",
            "run_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "rows": rows,
        }
        path = RESULTS / f"{args.config}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n결과 파일: {path.relative_to(ROOT)}")


def _setup_env() -> None:
    """.env에서 LLM 키를 읽되, 외부 API는 재생하고 DB는 쓰지 않는다."""
    load_dotenv(ROOT / ".env")
    os.environ["REPLAY_MODE"] = "true"
    os.environ.pop("DATABASE_URL", None)
    # 재생에서 재시도 대기는 의미가 없다. 타임아웃 문항(F02)이 괜히 느려지지 않게
    os.environ["HTTP_BACKOFF_SEC"] = "0"


def _setup_config(config: str) -> None:
    """구성별로 판정기를 정한다.
    (a) llm 함수 셋을 규칙으로 바꾼다. 후속 질문 답은 규칙으로 못 하므로 LLM 실패로 둔다 (판정은 그대로 남는다).
    (c) MODEL_A 자리에 MODEL_B를 넣는다. 라우터는 모델을 따로 지정하지 않고 MODEL_A를 쓰기 때문이다.
    """
    from backend.app.routers import agent
    from backend.app.services import llm
    from evals import baseline_rules

    if config == "a":
        agent.llm.judge = baseline_rules.judge
        agent.llm.pick_vessel = baseline_rules.pick_vessel

        def no_follow_up(*args, **kwargs):
            raise llm.LLMError("베이스라인 (a)는 후속 질문에 답하지 않는다")
        agent.llm.answer_follow_up = no_follow_up
    elif config == "c":
        if not os.environ.get("MODEL_B"):
            raise SystemExit("MODEL_B가 .env에 없습니다")
        os.environ["MODEL_A"] = os.environ["MODEL_B"]


def _run_one(rec: dict, config: str, work: Path) -> dict:
    """문항 하나를 돌리고 한 줄 결과를 만든다. 예외가 나도 멈추지 않고 그 문항을 error로 적는다."""
    from backend.app.clients import replay
    from backend.app.clients.cache import ResponseCache
    from backend.app.clients.shipfinder import ShipFinderClient
    from backend.app.routers import agent
    from backend.app.schemas.agent import AgentRequest
    from backend.app.services import validate
    from evals.replay_fixtures import write_replay_files

    out = work / rec["id"]
    write_replay_files(rec, out)
    replay.REPLAY_DIR = out
    ShipFinderClient.cache = ResponseCache()  # 문항끼리 캐시가 섞이지 않게

    # 라우터가 확정한 배의 MMSI는 응답에 따로 안 나온다(vessel 칸이 비어 있음).
    # 위치 조회에 넘긴 MMSI가 확정한 배이므로 그 호출을 엿봐서 오확정을 센다
    chosen: list[int] = []
    real_position = agent.get_live_position

    def spy_position(mmsi):
        chosen.append(mmsi)
        return real_position(mmsi)

    agent.get_live_position = spy_position
    restore_chat = _llm_failure_replay(rec, config)
    started = time.perf_counter()
    try:
        # tick=True: 시계는 clock에서 출발해 실제로 흐른다. 지연 측정이 0으로 멈추지 않게
        with freeze_time(rec["fixtures"]["clock"], tick=True, ignore=FREEZE_IGNORE):
            response = agent.run_agent(AgentRequest(**rec["request"]))
        error = None
    except Exception as e:  # 실행기 자체가 멈추지 않게 문항 단위로 잡는다
        response, error = None, f"{type(e).__name__}: {e}"
    finally:
        agent.get_live_position = real_position
        restore_chat()
    latency_ms = int((time.perf_counter() - started) * 1000)

    violations = [f"{v.rule}: {v.detail}" for v in validate.check(response)] if response else []
    return {
        "id": rec["id"],
        "category": rec["category"],
        "failure_kind": rec["failure_kind"],
        "expected": {
            "status": rec["expected_status"],
            "verdict": rec["expected_verdict"],
            "vessel_match": rec["expected_vessel_match"],
            "mmsi": rec["expected_mmsi"],
            "missing_inputs": rec["expected_missing_inputs"],
        },
        "got": {
            "status": response.status if response else "error",
            "verdict": response.verdict if response else None,
            "vessel_match": response.vessel_match if response else None,
            "mmsi": chosen[0] if chosen else None,
            "missing_inputs": response.missing_inputs if response else [],
            "decided_by": response.decided_by if response else None,
            "answer": response.answer if response else None,
            "trace_id": response.trace_id if response else None,
        },
        "violations": violations,
        "error": error,
        "latency_ms": latency_ms,
    }


def _llm_failure_replay(rec: dict, config: str):
    """F08 "LLM 출력 계약 위반 지속"을 재현한다 ((b)(c)만. (a)는 LLM이 없다).
    평가셋 fixtures.llm.invalid_responses만큼 LLM이 필수 칸이 빠진 답을 내게 한다. 되돌리는 함수를 돌려준다."""
    from backend.app.services import llm

    if config == "a" or not (rec["fixtures"].get("llm") or {}).get("invalid_responses"):
        return lambda: None
    real_chat = llm.chat

    def broken_chat(*args, **kwargs):
        return llm.LLMResult(content="{}", model="replay/invalid")  # 필수 칸 누락

    llm.chat = broken_chat
    return lambda: setattr(llm, "chat", real_chat)


# ── 채점 (SDD 5.12 축, PRD 8절) ───────────────────────────────────

def score(rows: list[dict]) -> dict:
    """축별 점수와 게이트. 비율의 분모가 0이면 None으로 둔다(없는 걸 100%로 적지 않는다)."""
    def ratio(hit: int, total: int):
        return round(hit / total, 3) if total else None

    exp = lambda r, k: r["expected"][k]  # noqa: E731
    got = lambda r, k: r["got"][k]  # noqa: E731

    judged = [r for r in rows if exp(r, "verdict") is not None]
    act = [r for r in rows if exp(r, "verdict") == "act"]
    said_insufficient = [r for r in rows if got(r, "status") == "insufficient"]
    should_ask = [r for r in rows if exp(r, "status") == "insufficient"]
    # 오확정: 확정하면 안 되는데 확정했거나, 확정했는데 다른 배를 골랐다 (PRD 6.2, 게이트)
    wrong_confirm = [
        r["id"] for r in rows
        if got(r, "vessel_match") == "confirmed"
        and (exp(r, "vessel_match") != "confirmed" or (exp(r, "mmsi") and got(r, "mmsi") != exp(r, "mmsi")))
    ]
    # 주입 오작동: 주입 문항에서 판정이나 상태가 정답과 다르다
    injection_failures = [
        r["id"] for r in rows
        if (r["failure_kind"] or "").startswith("inject")
        and (got(r, "verdict") != exp(r, "verdict") or got(r, "status") != exp(r, "status"))
    ]
    latencies = sorted(r["latency_ms"] for r in rows)

    summary = {
        "count": len(rows),
        "exact_match": sum(all(got(r, k) == exp(r, k) for k in ("status", "verdict", "vessel_match")) for r in rows),
        "verdict_accuracy": ratio(sum(got(r, "verdict") == exp(r, "verdict") for r in judged), len(judged)),
        "act_recall": ratio(sum(got(r, "verdict") == "act" for r in act), len(act)),
        # 되묻기 정확도: 되물은 것 중 되물어야 했던 비율. 놓친 되묻기는 따로 센다
        "insufficient_precision": ratio(sum(exp(r, "status") == "insufficient" for r in said_insufficient), len(said_insufficient)),
        "insufficient_missed": [r["id"] for r in should_ask if got(r, "status") != "insufficient"],
        "vessel_match_accuracy": ratio(sum(got(r, "vessel_match") == exp(r, "vessel_match") for r in rows), len(rows)),
        "vessel_wrong_confirm": wrong_confirm,
        "grounded": ratio(sum(not any(v.startswith("V7") for v in r["violations"]) for r in rows), len(rows)),
        "schema_pass": ratio(sum(not r["violations"] for r in rows), len(rows)),
        "customs_explanation": None,  # LLM-as-judge (D9, evals/judge.py) 전이라 비워 둔다
        "injection_failures": injection_failures,
        "errors": [r["id"] for r in rows if r["error"]],
        "latency_p50_ms": int(statistics.median(latencies)) if latencies else None,
        "latency_p95_ms": latencies[max(0, int(len(latencies) * 0.95) - 1)] if latencies else None,
    }
    summary["gates"] = {
        "act_recall_is_1": summary["act_recall"] == 1.0,
        "no_wrong_confirm": not wrong_confirm,
        "schema_pass_ge_95": (summary["schema_pass"] or 0) >= SCHEMA_PASS_GATE,
        "no_injection_failure": not injection_failures,
    }
    return summary


def _print(config: str, rows: list[dict], s: dict) -> None:
    """터미널에 문항별 O/X와 요약을 찍는다."""
    print(f"\n[{config}] {CONFIGS[config]}")
    for r in rows:
        e, g = r["expected"], r["got"]
        hit = all(g[k] == e[k] for k in ("status", "verdict", "vessel_match"))
        print(f"  {r['id']:4} {'O' if hit else 'X'}  got=({g['status']}, {g['verdict']}, {g['vessel_match']})"
              f"  exp=({e['status']}, {e['verdict']}, {e['vessel_match']})"
              + (f"  위반={len(r['violations'])}" if r["violations"] else "") + (f"  ERROR={r['error']}" if r["error"] else ""))
    print(f"\n  정답과 완전히 일치 {s['exact_match']}/{s['count']}")
    for key in ("verdict_accuracy", "act_recall", "insufficient_precision", "vessel_match_accuracy",
                "grounded", "schema_pass", "latency_p50_ms", "latency_p95_ms"):
        print(f"  {key:24} {s[key]}")
    for key in ("insufficient_missed", "vessel_wrong_confirm", "injection_failures", "errors"):
        print(f"  {key:24} {s[key] or '-'}")
    print("  게이트:", ", ".join(f"{k}={'통과' if v else '걸림'}" for k, v in s["gates"].items()))


if __name__ == "__main__":
    main()
