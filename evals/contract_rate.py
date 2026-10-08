"""출력 계약 준수율 집계 (가이드 7-1 "100건 이상 실행했을 때의 계약 준수율").

평가 실행기(run_eval.py)가 남긴 결과 파일 여러 개를 합쳐 LLM 출력 단위와 요청 단위로 센다.
새로 LLM을 부르지 않는다. 결과 파일에 이미 있는 값만 읽는다.

    python -m evals.contract_rate evals/results/b_20261002_*.json

세는 것
- LLM 출력 수: 결과 파일 rows[].llm_calls 중 실제 모델이 답한 것 (run_eval._spy_llm_calls가 호출마다 적는다)
- 계약 위반 출력: rows[].failures의 "<이름>=<사유> attempt N" 줄. 판정 라우터가 JSON 모양 오류(bad_format)나
  검증 위반(V1~V11)마다 남긴다 (routers/agent.py 판정 루프, log_failure)
- 요청 단위: 첫 시도 통과 / 재시도로 복구 / 3번 모두 실패해 판정 표 폴백 ("gave up after")

빼는 것
- F08 같은 녹화 실패(model "replay/invalid"). 일부러 깨진 답을 넣어 폴백 경로를 보는 문항이라
  모델의 준수율이 아니다. 폴백이 동작했는지는 따로 센다
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ATTEMPT = re.compile(r"^(?P<name>[a-z_]+)=(?P<why>.+) attempt (?P<n>\d+)$")  # log_failure("validate", "V7 attempt 1")
GAVE_UP = re.compile(r"gave up after \d+ attempts")
REPLAY_MODEL = "replay/invalid"  # run_eval._llm_failure_replay가 넣는 가짜 답의 모델 이름


def tally(paths: list[Path]) -> dict:
    """결과 파일들을 합쳐 출력 단위·요청 단위 숫자를 돌려준다."""
    outputs = violations = call_errors = 0
    first_try = recovered = fallback = 0
    replay_rows = replay_fallback = 0
    reasons: Counter[str] = Counter()
    runs = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        runs.append({"file": path.name, "model": data.get("model"), "commit": (data.get("git_commit") or "")[:12]})
        for row in data["rows"]:
            calls = row.get("llm_calls") or []
            failures = row.get("failures") or []
            gave_up = any(GAVE_UP.search(f) for f in failures)
            if any(c.get("model") == REPLAY_MODEL for c in calls):
                replay_rows += 1
                replay_fallback += gave_up
                continue
            real = [c for c in calls if c.get("ok")]
            call_errors += sum(1 for c in calls if not c.get("ok"))
            if not real:
                continue  # LLM을 부르기 전에 끝난 문항 (통관 실패, 부산 밖 등)
            bad = [m for m in (ATTEMPT.match(f) for f in failures) if m]
            outputs += len(real)
            violations += len(bad)
            for m in bad:
                for rule in m["why"].split(","):
                    reasons[rule.strip()] += 1
            if gave_up:
                fallback += 1
            elif bad:
                recovered += 1
            else:
                first_try += 1
    requests = first_try + recovered + fallback
    return {
        "runs": runs,
        "llm_outputs": outputs,
        "contract_violations": violations,
        "compliance": round((outputs - violations) / outputs, 4) if outputs else None,
        "violation_reasons": dict(reasons.most_common()),
        "call_errors": call_errors,
        "requests": requests,
        "first_try_pass": first_try,
        "recovered_by_retry": recovered,
        "fallback_to_table": fallback,
        "replay_rows_excluded": replay_rows,
        "replay_fallback_ok": replay_fallback,
    }


def main(argv: list[str]) -> None:
    paths = [Path(p) for p in argv]
    if not paths:
        sys.exit("결과 파일을 하나 이상 주세요. 예: python -m evals.contract_rate evals/results/b_*.json")
    print(json.dumps(tally(paths), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
