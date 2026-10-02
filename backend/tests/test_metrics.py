"""평가지표 API 테스트 (services/metrics.py). 가짜 결과 파일을 임시 폴더에 둔다."""
import json

from backend.app.services import metrics as svc


def _write(tmp_path, name, config, run_at, **summary):
    base = {"count": 30, "exact_match": 27, "verdict_accuracy": 1.0, "act_recall": 1.0, "insufficient_precision": 0.9,
            "vessel_match_accuracy": 0.933, "grounded": 1.0, "schema_pass": 1.0, "customs_explanation": None,
            "vessel_wrong_confirm": ["B01"], "injection_failures": [], "latency_p95_ms": 650,
            "gates": {"act_recall_is_1": True, "no_wrong_confirm": False}, "usage": {"llm_calls": 0, "cost_usd": None}}
    (tmp_path / name).write_text(json.dumps({"config": config, "model": "m", "run_at": run_at, "git_commit": "abc",
                                             "summary": {**base, **summary}}), encoding="utf-8")


def test_empty_results_are_all_null(tmp_path):
    m = svc.build(tmp_path)
    assert m["gate_passed"] is None and all(k["value"] is None for k in m["kpis"]) and m["experiments"] == []


def test_latest_per_config_and_service_gates(tmp_path):
    _write(tmp_path, "a_1.json", "a", "2026-10-01T07:00:00", verdict_accuracy=0.8)
    _write(tmp_path, "b_1.json", "b", "2026-10-01T06:00:00", verdict_accuracy=0.5)
    _write(tmp_path, "b_2.json", "b", "2026-10-01T08:00:00", verdict_accuracy=0.967,
           gates={"act_recall_is_1": True, "no_wrong_confirm": True}, vessel_wrong_confirm=[],
           usage={"llm_calls": 40, "cost_usd": 0.01, "cost_usd_per_request": 0.0003})
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    m = svc.build(tmp_path)
    row = next(r for r in m["comparison"] if r["id"] == "verdict_accuracy")
    assert row == {"id": "verdict_accuracy", "label": "판정 정확도", "baseline": 80.0, "model_a": 96.7, "model_b": None}
    assert m["gate_passed"] is True and m["updated_at"] == "2026-10-01T08:00:00"
    assert m["gates"][1]["value"] == "0건" and "$0.00030" in m["gates"][4]["value"]
    assert [e["file"] for e in m["experiments"]] == ["b_2.json", "a_1.json", "b_1.json"]  # 최신순, 깨진 파일 제외
