"""evals/judge.py 검증 모델 채점 테스트. 키 없이 돈다 (채점 LLM 호출은 가짜)."""
import pytest

from backend.app.services import llm
from evals import judge
from evals.run_eval import _scores, score

CUSTOMS = {"stage_name": "반입신고", "plain_explanation": "화물이 보세창고에 들어왔습니다.",
           "next_stage": "수입신고", "needs_broker": False, "stage_code": ""}


def _row(customs=CUSTOMS, grade=None):
    return {"id": "N1", "category": "normal", "failure_kind": None,
            "expected": {"status": "ok", "verdict": "fine", "vessel_match": "confirmed", "mmsi": 1, "missing_inputs": []},
            "got": {"status": "ok", "verdict": "fine", "vessel_match": "confirmed", "mmsi": 1, "missing_inputs": [],
                    "customs": customs},
            "violations": [], "error": None, "latency_ms": 10, "customs_grade": grade}


def _fake_grade(monkeypatch, score=1, reason="pass", fail=False):
    calls = []

    def grade_customs(customs, *, model=None):
        calls.append(model)
        if fail:
            raise llm.LLMError("테스트", kind="rate_limited")
        return llm.LLMAnswer(output=llm.GradeOutput(score=score, reason=reason),
                             llm=llm.LLMResult(content="", model=model or ""), prompt_version="test")

    monkeypatch.setattr(llm, "grade_customs", grade_customs)
    return calls


def test_grades_with_judge_model(monkeypatch):
    monkeypatch.setenv("EVAL_GRADER_MODEL", "openai/gpt-4o-mini")
    calls = _fake_grade(monkeypatch, score=0, reason="2: next stage is wrong")
    result = judge.grade(_row(), "vertex/google/gemini-2.5-flash")
    assert result == {"score": 0, "reason": "2: next stage is wrong", "model": "openai/gpt-4o-mini"}
    assert calls == ["openai/gpt-4o-mini"]


def test_same_model_is_not_graded(monkeypatch):
    """채점 모델이 판정 모델과 같으면 채점하지 않는다 (자기 선호 편향). vertex/ 앞머리는 무시하고 비교한다."""
    monkeypatch.setenv("EVAL_GRADER_MODEL", "google/gemini-2.5-flash")
    calls = _fake_grade(monkeypatch)
    assert judge.grade(_row(), "vertex/google/gemini-2.5-flash") is None
    assert calls == []


@pytest.mark.parametrize("customs", [None, {**CUSTOMS, "plain_explanation": ""}])
def test_no_explanation_is_not_graded(monkeypatch, customs):
    """규칙만 실행이나 되묻기처럼 해설이 없으면 채점하지 않는다."""
    monkeypatch.setenv("EVAL_GRADER_MODEL", "openai/gpt-4o-mini")
    calls = _fake_grade(monkeypatch)
    assert judge.grade(_row(customs=customs), "vertex/google/gemini-2.5-flash") is None
    assert calls == []


def test_judge_failure_keeps_going(monkeypatch):
    monkeypatch.setenv("EVAL_GRADER_MODEL", "openai/gpt-4o-mini")
    _fake_grade(monkeypatch, fail=True)
    result = judge.grade(_row(), "vertex/google/gemini-2.5-flash")
    assert result["score"] is None and "rate_limited" in result["reason"]


def test_summary_and_langfuse_score_use_graded_rows_only():
    """요약의 customs_explanation은 채점한 문항만 분모. 채점 실패(None)는 뺀다. Langfuse 점수도 같은 기준."""
    rows = [_row(grade={"score": 1, "reason": "pass", "model": "m"}),
            _row(grade={"score": 0, "reason": "2", "model": "m"}),
            _row(grade={"score": None, "reason": "judge failed", "model": "m"}),
            _row(customs=None, grade=None)]
    s = score(rows)
    assert s["customs_explanation"] == 0.5 and s["customs_graded"] == 2
    assert _scores(rows[0])["customs_explanation"] == 1.0
    assert "customs_explanation" not in _scores(rows[2])
