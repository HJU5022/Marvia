"""목록에 없는 통관 단계는 설명 문장을 코드가 고정 문장으로 쓴다.

- customs-stages/rules.md에 뜻이 없는 단계라 LLM이 설명할 근거가 없다. LLM에 맡기면 뜻을 지어냈다 (평가 B10)
- LLM이 해설을 못 냈어도 이 경우는 채운다
- 코드가 쓴 문장(반출신고 · 목록 밖 단계)은 평가의 LLM 해설 채점에서 뺀다
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.routers import agent
from backend.app.schemas.customs import CustomsRecord
from evals import judge
from backend.app.services.judge import answers as agent_answers
from backend.app.services.judge import builders as agent_builders


def _customs(stage: str) -> CustomsRecord:
    return CustomsRecord(bl_masked="TEST****0001", stage_name=stage, fetched_at=datetime.now(timezone.utc))


def test_unlisted_stage_uses_fixed_sentence_even_if_llm_wrote_one():
    llm_text = SimpleNamespace(plain_explanation="검사를 지정한 단계입니다. 지연될 수 있습니다.", next_stage="수입신고수리")
    info = agent_builders._customs_info(_customs("검사지정"), llm_text)
    assert info.plain_explanation == agent_answers.UNLISTED_STAGE_EXPLANATION.format(stage="검사지정")
    assert info.next_stage is None
    assert info.needs_broker is True


def test_unlisted_stage_is_filled_when_llm_gave_nothing():
    info = agent_builders._customs_info(_customs("처음 보는 단계"), None)
    assert info is not None and info.next_stage is None


def test_listed_stage_keeps_llm_explanation():
    llm_text = SimpleNamespace(plain_explanation="배가 입항했습니다.", next_stage="반입신고")
    info = agent_builders._customs_info(_customs("입항보고 수리"), llm_text)
    assert info.plain_explanation == "배가 입항했습니다."
    assert info.next_stage == "반입신고"
    assert agent_builders._customs_info(_customs("입항보고 수리"), None) is None


def test_code_written_explanation():
    assert agent_builders.code_written_explanation("검사지정") is True
    assert agent_builders.code_written_explanation(agent.RELEASED_STAGE) is True
    assert agent_builders.code_written_explanation("입항보고 수리") is False
    assert agent_builders.code_written_explanation(None) is False


def test_judge_skips_code_written_explanation(monkeypatch):
    # 채점 모델 설정이 있어도 코드가 쓴 문장은 채점하지 않는다 (LLM을 부르기 전에 None)
    monkeypatch.setenv("EVAL_GRADER_MODEL", "openai/gpt-4o-mini")
    row = {"got": {"customs": {"stage_name": "검사지정", "plain_explanation": "고정 문장"}}}
    assert judge.grade(row, "vertex/google/gemini-2.5-flash") is None
