"""후속 질문의 컨테이너 번호 처리 테스트: LLM은 [CNTR1] 번호표만 보고, 사용자 화면에는 실제 번호가 나간다.

컨테이너 번호도 B/L처럼 화물을 특정하는 번호라 LLM에 원문을 넘기지 않는다 (CLAUDE.md).
- llm.answer_follow_up: 입력의 컨테이너 번호를 [CNTR1], [CNTR2]로 바꾼다
- routers/agent.py _follow_up: 검증을 통과한 답 속 번호표를 같은 규칙으로 원래 번호로 되돌린다
번호는 전부 가공값이다. 키 없이 돈다: chat()과 지난 결과 조회를 가짜로 바꾼다.
"""
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import agent as agent_router
from backend.app.schemas.agent import AgentResponse, CustomsInfo, Evidence
from backend.app.services import llm
from backend.app.services import llm_support

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)
ONE = "TSTU1234560"
TWO = "TSTU7654321"


@pytest.fixture(autouse=True)
def local_prompt(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)


def _response(container_no: str | None, **over) -> AgentResponse:
    """컨테이너 번호만 바꿔 끼우는 가공 지난 결과."""
    customs = CustomsInfo(stage_code="", stage_name="반입신고", plain_explanation="반입신고 단계입니다.", next_stage=None,
                          needs_broker=False, container_no=container_no, goods_name="TEST GOODS")
    base = dict(status="ok", verdict="watch", vessel_match="confirmed", days_margin=5, decided_by="llm", vessel=None,
                position=None, eta=None, customs=customs, berth=None, evidence=[], answer="한 번 확인이 필요합니다.",
                trace_id="trace-test")
    return AgentResponse(**{**base, **over})


def _fake_chat(monkeypatch, answer: dict):
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append(messages)
        return llm.LLMResult(content=json.dumps(answer, ensure_ascii=False), model="test/model")

    monkeypatch.setattr(llm, "chat", fake_chat)
    return calls


# ── 번호표 만들기 ──

def test_tokens_follow_order_and_dedupe():
    assert llm.container_tokens(f"{ONE}, {TWO}") == {"[CNTR1]": ONE, "[CNTR2]": TWO}
    assert llm.container_tokens(f"{ONE}, {ONE}") == {"[CNTR1]": ONE}


@pytest.mark.parametrize("value", [None, "", " , "])
def test_tokens_empty_when_no_container(value):
    assert llm.container_tokens(value) == {}


# ── LLM 입력 ──

def test_llm_input_has_token_not_raw_number(monkeypatch):
    calls = _fake_chat(monkeypatch, {"in_scope": True, "answer": "컨테이너 번호는 [CNTR1]입니다."})
    llm.answer_follow_up("컨테이너 번호 뭐야?", _response(ONE))

    user = calls[0][1]["content"]
    assert ONE not in user and json.loads(user)["result"]["customs"]["container_no"] == "[CNTR1]"


def test_llm_input_multi_container_gets_one_token_each(monkeypatch):
    calls = _fake_chat(monkeypatch, {"in_scope": True, "answer": "[CNTR1], [CNTR2]입니다."})
    llm.answer_follow_up("컨테이너 번호 뭐야?", _response(f"{ONE}, {TWO}"))

    user = calls[0][1]["content"]
    assert ONE not in user and TWO not in user
    assert json.loads(user)["result"]["customs"]["container_no"] == "[CNTR1], [CNTR2]"


def test_llm_input_scrubs_number_found_elsewhere(monkeypatch):
    """근거 카드 값이나 지난 답에 번호가 섞여 있어도 LLM에는 안 간다."""
    evidence = [Evidence(source="unipass", field="note", value=f"컨테이너 {ONE} 반입", fetched_at=NOW)]
    previous = _response(ONE, evidence=evidence, answer=f"컨테이너는 {ONE}입니다.")
    calls = _fake_chat(monkeypatch, {"in_scope": True, "answer": "확인이 필요합니다."})
    llm.answer_follow_up("언제 들어와?", previous)

    user = calls[0][1]["content"]
    assert ONE not in user and "컨테이너 [CNTR1] 반입" in user


def test_llm_input_unchanged_without_container(monkeypatch):
    calls = _fake_chat(monkeypatch, {"in_scope": True, "answer": "여유는 5일입니다."})
    llm.answer_follow_up("여유가 며칠이야?", _response(None))

    data = json.loads(calls[0][1]["content"])
    assert data["result"]["customs"]["container_no"] is None and "CNTR" not in calls[0][1]["content"]
    assert data["result"]["customs"]["goods_name"] == "TEST GOODS"  # 다른 칸은 그대로


# ── 화면에 나가는 답 ──

def _ask(monkeypatch, previous: AgentResponse, llm_answer: str, session: str) -> dict:
    """라우터 후속 질문 경로를 진짜로 타되, 지난 결과와 LLM 답만 가짜로 바꾼다."""
    def follow(question, response, feedback=None, **kwargs):
        return llm.LLMAnswer(output=llm.FollowUpOutput(in_scope=True, answer=llm_answer),
                             llm=llm.LLMResult(content="", model="test/model"), prompt_version="test")

    monkeypatch.setattr(agent_router, "_previous_response", lambda request, user_id=None: previous)
    monkeypatch.setattr(agent_router.llm, "answer_follow_up", follow)
    with TestClient(app) as client:
        return client.post("/api/agent", json={"bl_no": "TESTBL0000000001", "bl_type": "HOUSE", "session_id": session,
                                               "follow_up_question": "컨테이너 번호 뭐야?"}).json()


def test_user_sees_real_number_for_token(monkeypatch):
    body = _ask(monkeypatch, _response(ONE), "컨테이너 번호는 [CNTR1]입니다.", "s-cntr1")
    assert body["answer"] == f"컨테이너 번호는 {ONE}입니다."


def test_user_sees_each_real_number_for_multi(monkeypatch):
    body = _ask(monkeypatch, _response(f"{ONE}, {TWO}"), "컨테이너는 [CNTR1]과 [CNTR2]입니다.", "s-cntr2")
    assert body["answer"] == f"컨테이너는 {ONE}과 {TWO}입니다."


def test_token_passes_validation_not_flagged_as_stray_number_or_word(monkeypatch):
    """번호표 속 숫자 1·낱말 CNTR이 V7·V9에 걸려 후속 답이 '답하지 못했습니다'로 끝나면 안 된다."""
    body = _ask(monkeypatch, _response(ONE), "컨테이너 번호는 [CNTR1]입니다.", "s-cntr3")
    assert body["answer"] != agent_router.FOLLOW_UP_FAILED


def test_no_container_changes_nothing(monkeypatch):
    body = _ask(monkeypatch, _response(None), "여유는 5일입니다.", "s-cntr4")
    assert body["answer"] == "여유는 5일입니다."


def test_unknown_token_is_left_as_is():
    """LLM이 지어낸 번호표는 되돌리지 않는다 (없는 번호를 만들어 내지 않는다)."""
    assert llm_support.restore_containers("[CNTR9]입니다", {"[CNTR1]": ONE}) == "[CNTR9]입니다"


def test_question_with_container_number_is_tokenized(monkeypatch):
    """사용자가 후속 질문에 이 화물의 컨테이너 번호를 직접 써도 LLM에는 번호표로 간다 (메인 세션 보완)"""
    calls = _fake_chat(monkeypatch, {"in_scope": True, "answer": "[CNTR1] 컨테이너는 반입신고 단계입니다."})
    llm.answer_follow_up(f"{ONE} 컨테이너 지금 어디야?", _response(ONE))

    user = calls[0][1]["content"]
    assert ONE not in user and json.loads(user)["question"] == "[CNTR1] 컨테이너 지금 어디야?"
