"""LLM-as-judge: 판정 LLM이 쓴 통관 해설을 다른 회사 모델로 채점한다 (SDD 5.12, 가이드 평가 4축 ④).

evals/run_eval.py가 문항을 푼 직후 grade(row, 판정 모델)를 부른다. 결과는 row["customs_grade"]에 담기고
요약의 customs_explanation(채점한 문항의 평균)과 Langfuse 실험 점수로 남는다.

채점하지 않는 경우 (None을 돌려준다)
  - 통관 해설이 없다: 규칙만(a) 실행, 되묻기·실패처럼 판정 LLM을 안 부른 응답
  - EVAL_GRADER_MODEL이 없다
  - EVAL_GRADER_MODEL이 판정 모델과 같다: 같은 모델은 자기 답을 후하게 채점한다 (자기 선호 편향, Zheng 외 2023)
채점 호출이 실패하면 score None과 실패 종류를 남긴다. 평가는 멈추지 않는다.
"""
from __future__ import annotations

import os

VERTEX_PREFIX = "vertex/"  # services/llm.py와 같은 앞머리. 같은 모델인지 볼 때 떼고 비교한다


def same_model(a: str | None, b: str | None) -> bool:
    """두 모델 이름이 같은 모델인가. vertex/ 앞머리와 대소문자 차이는 무시한다."""
    if not a or not b:
        return False
    norm = lambda name: name.strip().lower().removeprefix(VERTEX_PREFIX)  # noqa: E731
    return norm(a) == norm(b)


def grade(row: dict, generation_model: str | None) -> dict | None:
    """문항 하나의 통관 해설을 채점한다. {"score": 0|1|None, "reason": str, "model": str} 또는 None(채점 안 함)."""
    customs = (row.get("got") or {}).get("customs")
    if not customs or not customs.get("plain_explanation"):
        return None
    # 반출신고와 목록에 없는 단계는 코드가 고정 문장을 쓴다. LLM 해설 품질이 아니라 채점에서 뺀다
    from backend.app.services.judge.builders import code_written_explanation

    if code_written_explanation(customs.get("stage_name")):
        return None
    judge_model = os.environ.get("EVAL_GRADER_MODEL")
    if not judge_model or same_model(judge_model, generation_model):
        return None

    from backend.app.services import llm  # 실행기가 환경변수를 정한 뒤에 import한다 (run_eval.py와 같은 이유)

    try:
        out = llm.grade_customs(customs, model=judge_model).output
    except llm.LLMError as e:
        return {"score": None, "reason": f"judge failed: {e.kind}", "model": judge_model}
    return {"score": out.score, "reason": out.reason, "model": judge_model}
