"""평가 결과 파일을 평가지표 화면 모양으로 (GET /api/metrics).

evals/run_eval.py가 실행마다 evals/results/<config>_<한국시각>.json을 남긴다 (D8). 여기서는 읽기만 한다.
- 구성별 최신 파일: a(규칙만) → baseline, b(서비스 모델) → model_a, c(비교 모델) → model_b (PRD 8절 베이스라인 비교)
- KPI·게이트는 서비스에 실제로 쓰는 구성 b 기준. b가 없으면 값은 null(화면은 "미측정")
- 실행 기록은 파일 전부를 최신순으로 (실험 이력)
숫자를 만들거나 고치지 않는다. 실행하지 않은 값은 null 그대로다 (CLAUDE.md "실행하지 않은 결과 숫자를 적지 않는다").
보고에 쓴 실행 결과는 레포에 커밋한다(재감사). 폴더가 비어 있으면 전부 null이다. 주입 측정(injection/ 하위 폴더)은 읽지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parents[4] / "evals" / "results"
ROLE = {"a": "baseline", "b": "model_a", "c": "model_b"}
EXPERIMENT_LIMIT = 20

# 화면 표의 줄 (web/lib/fixtures/metrics.json의 id와 같다). act 등급의 한국어 이름이 긴급으로 바뀌어 지표 이름도 맞춘다
COMPARE = [("verdict_accuracy", "판정 정확도"), ("act_recall", "긴급 재현율"),
           ("insufficient_precision", "되묻기 정확도"), ("vessel_match_accuracy", "선박 식별 정확도"),
           ("grounded", "근거 일치율"), ("customs_explanation", "통관 해설 품질")]
KPIS = [("verdict_accuracy", "판정 정확도"), ("insufficient_precision", "되묻기 정확도"),
        ("act_recall", "긴급 재현율"), ("schema_pass", "출력 계약 준수율")]


def _pct(v) -> float | None:
    """0~1 비율을 소수 한 자리 %로. 값이 없으면 None."""
    return None if v is None else round(float(v) * 100, 1)


def load_runs(results_dir: Path = RESULTS_DIR) -> list[dict]:
    """결과 파일 전부, 최신순. 깨진 파일은 건너뛴다."""
    runs = []
    for path in results_dir.glob("*.json") if results_dir.exists() else []:
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("config") in ROLE and isinstance(d.get("summary"), dict):
            d["_file"] = path.name
            runs.append(d)
    return sorted(runs, key=lambda d: d.get("run_at") or "", reverse=True)


def build(results_dir: Path = RESULTS_DIR) -> dict:
    runs = load_runs(results_dir)
    latest = {}
    for r in runs:
        latest.setdefault(r["config"], r)
    service = latest.get("b")
    s = service["summary"] if service else {}
    gates = s.get("gates") or {}
    usage = s.get("usage") or {}

    def passed(key):
        """게이트 한 줄의 통과 여부. 측정 전이거나 키가 없으면 None (화면은 대기)."""
        v = gates.get(key)
        return None if v is None else bool(v)

    def count(key):
        v = s.get(key)
        return None if not service else (f"{len(v)}건" if isinstance(v, list) else ("0건" if v in (None, "-") else str(v)))

    return {
        "title": "서비스 구성(b) 평가 결과" if service else "평가 결과를 기다리고 있습니다",
        "updated_at": service.get("run_at") if service else None,
        "dataset_size": s.get("count"),
        "gate_passed": all(gates.values()) if gates else None,
        "kpis": [{"id": k, "label": label, "value": _pct(s.get(k)), "unit": "%"} for k, label in KPIS],
        "comparison": [{"id": k, "label": label, **{ROLE[c]: _pct(latest[c]["summary"].get(k)) if c in latest else None
                                                    for c in ROLE}} for k, label in COMPARE],
        "gates": [
            {"label": "긴급 누락", "target": "0건", "value": None if not gates else ("통과" if gates.get("act_recall_is_1") else "걸림"), "passed": passed("act_recall_is_1")},
            {"label": "선박 식별 오확정", "target": "0건", "value": count("vessel_wrong_confirm"), "passed": passed("no_wrong_confirm")},
            {"label": "출력 계약 준수율", "target": "95% 이상", "value": None if s.get("schema_pass") is None else f"{_pct(s['schema_pass'])}%", "passed": passed("schema_pass_ge_95")},
            {"label": "주입 오작동", "target": "0건", "value": count("injection_failures"), "passed": passed("no_injection_failure")},
            {"label": "p95 지연 · 요청당 비용", "target": None, "passed": None,  # 목표값이 없어 통과 여부도 없다
             "value": None if not service else f"{s.get('latency_p95_ms')}ms · "
                      + (f"${usage['cost_usd_per_request']:.5f}" if usage.get("cost_usd_per_request") else "비용 미집계")},
        ],
        "experiments": [{
            "config": r["config"], "model": r.get("model"), "run_at": r.get("run_at"), "commit": r.get("git_commit"),
            "exact_match": r["summary"].get("exact_match"), "count": r["summary"].get("count"),
            "gate_passed": all((r["summary"].get("gates") or {}).values()) if r["summary"].get("gates") else None,
            "llm_calls": (r["summary"].get("usage") or {}).get("llm_calls"),
            "cost_usd": (r["summary"].get("usage") or {}).get("cost_usd"), "file": r["_file"],
        } for r in runs[:EXPERIMENT_LIMIT]],
    }
