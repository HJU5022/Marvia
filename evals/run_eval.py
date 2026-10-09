"""평가 실행기 (D8, SDD 5.12, PRD 8절).

    python -m evals.run_eval --config a     # 규칙만 (evals/baseline_rules.py)
    python -m evals.run_eval --config b     # 규칙 + 서비스 모델 (.env LLM_MODEL)
    python -m evals.run_eval --config c     # 규칙 + 비교 모델 (.env EVAL_COMPARE_MODEL)

하는 일:
  1. dataset.jsonl 30건을 문항마다 REPLAY 재생 파일로 풀고 (evals/replay_fixtures.py)
  2. 시계를 문항의 clock(09-22 12:00)으로 맞춘 채 실제 라우터(run_agent)에 요청을 넣고
  3. 응답을 정답과 대조해 축별 점수와 게이트를 계산해 evals/results/<config>_<한국시각>.json에 쓴다
     (예: b_20260929_0343.json). 예전엔 <config>.json 하나를 덮어써서 Gemini 19/30 원본을 잃었다.
     그래서 실행마다 새 파일을 만들고, 어떤 코드·프롬프트로 잰 점수인지(git 커밋·프롬프트 버전)도 같이 적는다
  4. 문항마다 LLM 호출(모델·토큰·비용·지연·실패 종류)과 실패 로그(stage=error)를 남긴다.
     qwen 무료 실행에서 23건이 판정을 못 냈는데 왜 실패했는지 결과 파일에 없었다.
     요청당 비용은 README 지표 표·발표 질문 7에 필요하다 (Main_2 가이드 12장·13장)
  5. Langfuse 키가 있으면 실행 한 번을 Dataset marvia-golden-30의 실험(Experiment)으로 남긴다 (_LangfuseRun).
     문항마다 호출을 한 트레이스로 묶어 그 문항에 잇고, 채점 결과를 점수로 붙인다. Experiments 탭에서 실행끼리 비교한다
서버 코드는 고치지 않는다. 바꿔 끼우는 것(판정기, 재생 transport, 시계)은 이 실행 안에서만 유효하다.

외부 API는 키 없이 재생한다. (b)(c)만 진짜 LLM을 부른다(비용이 든다). (a)는 LLM을 한 번도 부르지 않는다.
DB(DATABASE_URL)는 쓰지 않는다. 조회 이력 저장은 실패해도 응답이 나가게 돼 있다 (routers/agent.py _logged).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import statistics
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from freezegun import freeze_time

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "dataset.jsonl"
RESULTS = ROOT / "evals" / "results"

CONFIGS = {"a": "규칙만 (baseline_rules)", "b": "규칙 + 서비스 모델 (LLM_MODEL)", "c": "규칙 + 비교 모델 (EVAL_COMPARE_MODEL)"}

# 게이트 (PRD 8절, SDD 5.12). 하나라도 걸리면 배포하지 않는다
SCHEMA_PASS_GATE = 0.95

# 시계를 멈출 때 제외할 모듈. 트레이스·토큰 발급은 진짜 시각을 써야 Langfuse에서 찾기 쉽고 인증이 안 꼬인다
FREEZE_IGNORE = ["langfuse", "opentelemetry", "google.auth"]

KST = timezone(timedelta(hours=9))  # 결과 파일 이름은 한국 시각으로. 위키 근거 원장의 시각과 맞춘다


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
    prompt_versions = _spy_prompt_versions()

    records = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.only:
        records = [r for r in records if r["id"] in args.only]

    work = Path(tempfile.mkdtemp(prefix="marvia_eval_"))
    try:
        # --only는 확인용 부분 실행이라 Langfuse 실행 기록으로 남기지 않는다 (30건 비교가 흐트러진다)
        recorder = None if args.only else _LangfuseRun.start(args.config)
        solve = lambda rec: _graded(_run_one(rec, args.config, work), args.config)  # noqa: E731
        rows = recorder.run_all(records, solve) if recorder else [solve(rec) for rec in records]
    finally:
        shutil.rmtree(work, ignore_errors=True)

    summary = score(rows)
    summary["usage"] = usage(rows)
    _print(args.config, rows, summary)
    if not args.only:
        RESULTS.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        result = {
            "config": args.config,
            "description": CONFIGS[args.config],
            "model": os.environ.get("LLM_MODEL") if args.config != "a" else "baseline/rules",
            "run_at": now.isoformat(),
            "git_commit": _git_commit(),
            "prompt_versions": prompt_versions,  # {"marvia-judge": "2", ...}. (a)는 LLM을 안 불러 비어 있다
            "summary": summary,
            "rows": rows,
        }
        # 실행마다 새 파일. 같은 분에 두 번 돌려도 덮지 않게 초까지 붙이지는 않고, 있으면 멈춘다
        path = RESULTS / f"{args.config}_{now.astimezone(KST):%Y%m%d_%H%M}.json"
        if path.exists():
            raise SystemExit(f"{path.name}이 이미 있습니다. 1분 뒤 다시 실행하세요 (덮어쓰지 않는다)")
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n결과 파일: {path.relative_to(ROOT)}")


def _graded(row: dict, config: str) -> dict:
    """문항을 푼 직후 통관 해설을 검증 모델로 채점해 row["customs_grade"]에 넣는다 (evals/judge.py).
    규칙만(a)은 LLM 해설이 없어 채점하지 않는다. (c)는 LLM_MODEL 자리에 EVAL_COMPARE_MODEL이 들어가 있다 (_setup_config)."""
    if config != "a":
        from evals import judge

        row["customs_grade"] = judge.grade(row, os.environ.get("LLM_MODEL"))
    return row


class _LangfuseRun:
    """평가 실행 한 번을 Langfuse Dataset(evals/push_dataset.py로 올린 marvia-golden-30)의 실험(Experiment)으로 남긴다.

    SDK의 dataset.run_experiment를 쓴다. 이 계정(09-16 이후 생성)은 옛 "dataset run" API로 만든 기록이
    Experiments 화면에 안 잡혀서(Experiments 0개) 공식 경로로 바꿨다.
    max_concurrency=1로 한 문항씩 돈다. 이 실행기는 시계를 멈추고 서버 함수를 바꿔 끼워서 동시에 돌면 안 된다.
    SDK가 문항마다 span을 열어 주므로, 그 안에서 서버가 남기는 LLM generation이 문항별 트레이스로 모인다.
    Langfuse가 실패해도 평가는 계속한다. 못 돈 문항은 기록 없이 로컬에서 풀고, 결과 파일은 그대로 남는다.
    """

    def __init__(self, client, run_name: str, config: str):
        self.client = client
        self.run_name = run_name
        self.config = config

    @classmethod
    def start(cls, config: str) -> "_LangfuseRun | None":
        if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
            return None
        try:
            from langfuse import get_client
        except ImportError:
            return None
        model = os.environ.get("LLM_MODEL") if config != "a" else "baseline/rules"
        now = datetime.now(timezone.utc).astimezone(KST)
        # 실행 이름만 보고 무엇을 잰 것인지 알게: 구성 · 모델 · 생각 설정 · 시각
        thinking = f" thinking={os.environ['VERTEX_THINKING_BUDGET']}" if os.environ.get("VERTEX_THINKING_BUDGET") and config != "a" else ""
        return cls(get_client(), f"{config} {model}{thinking} {now:%m-%d %H:%M}", config)

    def run_all(self, records: list[dict], solve) -> list[dict]:
        """모든 문항을 실험으로 푼다. solve(rec)는 문항 하나를 풀어 결과 줄(row)을 돌려준다. 결과는 평가셋 순서로."""
        from evals.push_dataset import DATASET_NAME

        by_case = {r["id"]: r for r in records}
        rows: dict[str, dict] = {}

        def task(*, item, **kwargs):
            rec = by_case.get((item.metadata or {}).get("case_id"))
            if rec is None:  # Langfuse에만 있고 이번 실행에 없는 문항(--only 등)은 건너뛴다
                return None
            rows[rec["id"]] = solve(rec)
            return rows[rec["id"]]["got"]

        def evaluator(*, input, output, expected_output=None, metadata=None, **kwargs):
            from langfuse.experiment import Evaluation

            row = rows.get((metadata or {}).get("case_id"))
            return [Evaluation(name=k, value=v) for k, v in _scores(row).items()] if row else []

        try:
            result = self.client.get_dataset(DATASET_NAME).run_experiment(
                name=f"eval {self.config}", run_name=self.run_name, description=CONFIGS[self.config],
                task=task, evaluators=[evaluator], max_concurrency=1,
                metadata={"config": self.config, "git_commit": _git_commit() or ""},
            )
            print(f"Langfuse 실험: {self.run_name} ({len(rows)}건) {getattr(result, 'dataset_run_url', '') or ''}")
        except Exception as e:
            log_failure_eval("langfuse_experiment", type(e).__name__)
        # Langfuse에서 못 돈 문항(평가셋을 안 올렸거나 실패)은 기록 없이 로컬에서 푼다
        for rec in records:
            if rec["id"] not in rows:
                rows[rec["id"]] = solve(rec)
        self.client.flush()
        return [rows[r["id"]] for r in records]


def _scores(row: dict) -> dict[str, float]:
    """문항 하나의 채점을 Langfuse 점수로. score()와 같은 기준이다 (1 맞음, 0 틀림).

    verdict_match는 정답 판정이 있는 문항만 준다 (score의 verdict_accuracy 분모와 같게).
    """
    e, g = row["expected"], row["got"]
    scores = {
        "exact_match": float(all(g[k] == e[k] for k in ("status", "verdict", "vessel_match"))),
        "schema_pass": float(not row["violations"]),
    }
    if e["verdict"] is not None:
        scores["verdict_match"] = float(g["verdict"] == e["verdict"])
    grade = row.get("customs_grade") or {}
    if grade.get("score") is not None:
        scores["customs_explanation"] = float(grade["score"])  # 검증 모델 채점 (evals/judge.py)
    return scores


def log_failure_eval(stage: str, error: str) -> None:
    """실행기 안의 Langfuse 실패를 서버와 같은 형식으로 남긴다. 서버 모듈은 환경변수를 정한 뒤에 import한다."""
    from backend.app.observability.logging import log_failure

    log_failure(stage, error)


def _git_commit() -> str | None:
    """지금 코드의 커밋. 커밋 안 한 변경이 있으면 뒤에 -dirty를 붙인다. git이 없으면 None."""
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{head}-dirty" if dirty else head


def _spy_prompt_versions() -> dict[str, str]:
    """실행 동안 LLM이 실제로 받은 프롬프트 버전을 모은다. Langfuse 번호, Langfuse가 안 되면 "local".
    llm.py가 get_prompt를 이름으로 가져다 쓰므로 llm 모듈 안의 이름을 감싼다. 이 실행 안에서만 유효하다."""
    from backend.app.services import llm

    seen: dict[str, str] = {}
    real_get_prompt = llm.get_prompt

    def spy(name, *args, **kwargs):
        prompt = real_get_prompt(name, *args, **kwargs)
        seen[name] = prompt.version
        return prompt

    llm.get_prompt = spy
    return seen


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
    (c) LLM_MODEL 자리에 EVAL_COMPARE_MODEL을 넣는다. 라우터는 모델을 따로 지정하지 않고 LLM_MODEL을 쓰기 때문이다.
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
        if not os.environ.get("EVAL_COMPARE_MODEL"):
            raise SystemExit("EVAL_COMPARE_MODEL이 .env에 없습니다")
        os.environ["LLM_MODEL"] = os.environ["EVAL_COMPARE_MODEL"]


def _run_one(rec: dict, config: str, work: Path) -> dict:
    """문항 하나를 돌리고 한 줄 결과를 만든다. 예외가 나도 멈추지 않고 그 문항을 error로 적는다."""
    from backend.app.clients import replay
    from backend.app.clients.cache import ResponseCache
    from backend.app.clients.shipfinder import ShipFinderClient
    from backend.app.observability.logging import failure_logger
    from backend.app.routers import agent
    from backend.app.schemas.agent import AgentRequest
    from backend.app.services.judge import validate
    from evals.replay_fixtures import write_replay_files

    out = work / rec["id"]
    write_replay_files(rec, out)
    replay.REPLAY_DIR = out
    ShipFinderClient.cache = ResponseCache()  # 문항끼리 캐시가 섞이지 않게
    _seed_position_cache(rec, ShipFinderClient.cache)

    # 라우터가 확정한 배의 MMSI는 응답에 따로 안 나온다(vessel 칸이 비어 있음).
    # 위치 조회에 넘긴 MMSI가 확정한 배이므로 그 호출을 엿봐서 오확정을 센다
    chosen: list[int] = []
    real_position = agent.get_live_position

    def spy_position(mmsi):
        chosen.append(mmsi)
        return real_position(mmsi)

    agent.get_live_position = spy_position
    # 워커 위치 이력은 DB 대신 평가셋 fixtures.worker_positions를 준다. 평가는 DB를 쓰지 않는다 (_setup_env).
    # 이게 없으면 anchor_wait가 정지 시간을 못 재서 B08(30시간 정박)이 늘 unknown이었다
    real_history = agent._position_history
    agent._position_history = lambda mmsi: list(rec["fixtures"].get("worker_positions") or [])
    restore_chat = _llm_failure_replay(rec, config)
    # 실패 재현(broken_chat)을 끼운 뒤에 감싼다. 그래야 F08의 가짜 답도 호출 기록에 남는다
    llm_calls: list[dict] = []
    restore_spy = _spy_llm_calls(llm_calls)
    failures: list[str] = []
    collector = _FailureCollector(failures)
    failure_logger.addHandler(collector)
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
        agent._position_history = real_history
        restore_spy()
        restore_chat()
        failure_logger.removeHandler(collector)
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
            # 판정 LLM이 쓴 통관 해설. 검증 모델이 채점한다 (evals/judge.py). 이력은 길고 채점에 안 쓰여 뺀다
            "customs": response.customs.model_dump(mode="json", exclude={"history"}) if response and response.customs else None,
            "trace_id": response.trace_id if response else None,
        },
        "violations": violations,
        "error": error,
        "latency_ms": latency_ms,
        "failures": failures,    # 서버가 남긴 실패 로그 "stage=error" (D6). partial·failed가 왜 났는지
        "llm_calls": llm_calls,  # 이 문항에서 부른 LLM 호출 하나당 한 줄 (_spy_llm_calls)
    }


def _seed_position_cache(rec: dict, cache) -> None:
    """평가셋 fixtures.shipfinder.cache(예전에 받아 둔 위치)를 캐시에 넣는다. 평가셋에 적힌 담긴 시각 그대로.

    F02 "위치 조회가 시간 초과 → 마지막 수신 위치로 판정"을 재현하려면 조회 전에 캐시가 있어야 한다.
    전에는 이 칸을 읽지 않아 F02가 캐시 없는 시간 초과로만 돌았다.
    캐시가 TTL(clients/cache.py, SDD 5.2 6시간)을 넘겼으면 클라이언트가 버린다. 그 판단은 서버 코드에 맡긴다.
    """
    from backend.app.clients.shipfinder import position_from_data

    cached = (rec["fixtures"].get("shipfinder") or {}).get("cache")
    if not cached:
        return
    cache.set(f"shipfinder:pos:{cached['mmsi']}", position_from_data(cached),
              cached_at=datetime.fromisoformat(cached["cached_at"]))


class _FailureCollector(logging.Handler):
    """서버의 log_failure()가 남긴 줄(stage·error)을 문항별 목록에 모은다.
    예외 메시지는 원래 로그에 안 들어가니(키·B/L 섞임 방지, logging.py) 여기에도 종류·코드만 남는다."""

    def __init__(self, sink: list[str]):
        super().__init__(level=logging.WARNING)
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self.sink.append(f"{getattr(record, 'stage', '?')}={getattr(record, 'error', '?')}")


def _spy_llm_calls(sink: list[dict]):
    """llm.chat을 감싸 호출마다 모델·토큰·비용·지연을, 실패면 종류(kind)·코드를 sink에 적는다. 되돌리는 함수를 돌려준다.

    cost는 OpenRouter가 준 실제 금액(USD)이다. Vertex는 금액을 안 줘서 None이다(llm.py LLMResult).
    그때 요청당 비용은 토큰 수 × 가격표로 따로 계산한다. 가격표를 여기 박아 두면 가격이 바뀌어도 모르고 쓰게 된다.
    """
    from backend.app.services import llm

    inner = llm.chat

    def spy_chat(*args, **kwargs):
        model = kwargs.get("model") or os.environ.get("LLM_MODEL")
        try:
            result = inner(*args, **kwargs)
        except llm.LLMError as e:
            sink.append({"ok": False, "model": model, "kind": e.kind, "code": e.code, "latency_ms": e.latency_ms})
            raise
        sink.append({
            "ok": True, "model": result.model, "provider": result.provider,
            "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
            "cached_tokens": result.cached_tokens,
            "cost": result.cost, "latency_ms": result.latency_ms, "attempts": result.attempts,
            "finish_reason": result.finish_reason,
        })
        return result

    llm.chat = spy_chat
    return lambda: setattr(llm, "chat", inner)


def _llm_failure_replay(rec: dict, config: str):
    """F08 "LLM 출력 계약 위반 지속"을 재현한다 ((b)(c)만. (a)는 LLM이 없다).
    평가셋 fixtures.llm.invalid_responses만큼 LLM이 필수 칸이 빠진 답을 내게 한다. 되돌리는 함수를 돌려준다."""
    from backend.app.services import llm

    if config == "a" or not (rec["fixtures"].get("llm") or {}).get("invalid_responses"):
        return lambda: None
    real_chat = llm.chat

    def broken_chat(*args, **kwargs):
        # 필수 칸 누락. 실제로 부르지 않았으니 비용 0. None으로 두면 usage()가 "금액 모름"으로 보고
        # 진짜 호출 금액 합계까지 버린다 (gpt-4o-mini 실행에서 요청당 비용이 이것 때문에 비었다)
        return llm.LLMResult(content="{}", model="replay/invalid", cost=0.0)

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
    graded = [r["customs_grade"] for r in rows if (r.get("customs_grade") or {}).get("score") is not None]

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
        # 검증 모델(EVAL_GRADER_MODEL)이 채점한 통관 해설 통과율. 채점한 문항만 분모다. 채점이 없으면 None (evals/judge.py)
        "customs_explanation": ratio(sum(g["score"] for g in graded), len(graded)),
        "customs_graded": len(graded),
        "injection_failures": injection_failures,
        "errors": [r["id"] for r in rows if r["error"]],
        "latency_p50_ms": int(statistics.median(latencies)) if latencies else None,
        "latency_p95_ms": p95(latencies),
    }
    summary["gates"] = {
        "act_recall_is_1": summary["act_recall"] == 1.0,
        "no_wrong_confirm": not wrong_confirm,
        "schema_pass_ge_95": (summary["schema_pass"] or 0) >= SCHEMA_PASS_GATE,
        "no_injection_failure": not injection_failures,
    }
    return summary


def p95(values: list[int]) -> int | None:
    """95번째 백분위수. 작은 순으로 줄 세워 ceil(0.95 × n)번째 값을 고른다 (nearest-rank 방식).

    100건 중 95건이 이 값 안에 들어온다는 뜻이다. 보간 없이 실제로 나온 값 하나를 고른다.
    예전 식 sorted[int(n × 0.95) - 1]은 한 칸 앞 값을 골랐다. 30건이면 29번째 대신 28번째라 실제보다 낮게 나왔고,
    2건이면 가장 빠른 값이 나와 p50보다 작았다 (--only N01 F08: p50 5066ms, p95 23ms).
    """
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def usage(rows: list[dict]) -> dict:
    """LLM 호출 수·토큰·비용 합계와 실패 종류별 개수. 요청당 비용은 README 지표 표·발표 질문 7에 쓴다.

    비용은 모든 성공 호출에 금액이 있을 때만 합친다. 하나라도 없으면(Vertex) None으로 둔다.
    일부만 더한 값을 합계처럼 적으면 실제보다 싸 보이기 때문이다. 그때는 토큰 합계로 계산한다.
    """
    calls = [c for r in rows for c in r.get("llm_calls", [])]
    ok = [c for c in calls if c["ok"]]
    costs = [c["cost"] for c in ok]
    total_cost = round(sum(costs), 6) if ok and all(c is not None for c in costs) else None
    return {
        "llm_calls": len(calls),
        "llm_errors": dict(Counter(c["kind"] for c in calls if not c["ok"])),
        "prompt_tokens": sum(c["prompt_tokens"] or 0 for c in ok),
        "completion_tokens": sum(c["completion_tokens"] or 0 for c in ok),  # Vertex는 생각 토큰 포함 (llm.py)
        # 입력 중 제공사 캐시에서 읽은 토큰 합. 캐시된 입력은 싸게 계산된다. 할인율은 제공사 가격표를 따른다
        "cached_tokens": sum(c.get("cached_tokens") or 0 for c in ok),
        "cost_usd": total_cost,
        "cost_usd_per_request": round(total_cost / len(rows), 6) if total_cost is not None and rows else None,
        "failures": dict(Counter(f for r in rows for f in r.get("failures", []))),
    }


def _grade_note(grade: dict | None) -> str:
    """통관 해설 채점을 한 줄 끝에 붙인다. 0점이면 이유도 (어느 조건을 어겼는지)."""
    if not grade:
        return ""
    if grade.get("score") == 0:
        return f"  해설=0 ({grade.get('reason')})"
    return f"  해설={grade.get('score')}" if grade.get("score") is not None else f"  해설=채점실패 ({grade.get('reason')})"


def _print(config: str, rows: list[dict], s: dict) -> None:
    """터미널에 문항별 O/X와 요약을 찍는다."""
    print(f"\n[{config}] {CONFIGS[config]}")
    for r in rows:
        e, g = r["expected"], r["got"]
        hit = all(g[k] == e[k] for k in ("status", "verdict", "vessel_match"))
        print(f"  {r['id']:4} {'O' if hit else 'X'}  got=({g['status']}, {g['verdict']}, {g['vessel_match']})"
              f"  exp=({e['status']}, {e['verdict']}, {e['vessel_match']})"
              + (f"  위반={len(r['violations'])}" if r["violations"] else "") + (f"  ERROR={r['error']}" if r["error"] else "")
              + (f"  실패={','.join(r['failures'])}" if r.get("failures") else "")
              + _grade_note(r.get("customs_grade")))
    print(f"\n  정답과 완전히 일치 {s['exact_match']}/{s['count']}")
    for key in ("verdict_accuracy", "act_recall", "insufficient_precision", "vessel_match_accuracy",
                "grounded", "schema_pass", "customs_explanation", "latency_p50_ms", "latency_p95_ms"):
        print(f"  {key:24} {s[key]}")
    for key in ("insufficient_missed", "vessel_wrong_confirm", "injection_failures", "errors"):
        print(f"  {key:24} {s[key] or '-'}")
    print("  게이트:", ", ".join(f"{k}={'통과' if v else '걸림'}" for k, v in s["gates"].items()))
    u = s.get("usage")
    if u:
        print(f"  LLM 호출 {u['llm_calls']}회 · 토큰 입력 {u['prompt_tokens']} (캐시 {u.get('cached_tokens', 0)}) / 출력 {u['completion_tokens']}"
              f" · 비용 {u['cost_usd'] if u['cost_usd'] is not None else '금액 없음(토큰으로 계산)'}"
              f" · 요청당 {u['cost_usd_per_request'] if u['cost_usd_per_request'] is not None else '-'}")
        print(f"  LLM 실패 종류 {u['llm_errors'] or '-'}")
        print(f"  실패 로그 {u['failures'] or '-'}")


if __name__ == "__main__":
    main()
