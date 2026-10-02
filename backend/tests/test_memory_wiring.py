"""화물 비서 기억 연결 테스트 (routers/agent.py, services/chat.py, docs/specs/memory.md 읽기·쓰기 흐름, EC-02·05·08·09).

외부 API·DB·LLM 없이 돈다. test_routers.py의 가짜(fake)와 로그인 도장(_login)을 그대로 쓴다. B/L은 모의값이다.
"""
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app import crypto
from backend.app.main import app
from backend.app.routers import agent as agent_router
from backend.app.services import chat as svc
from backend.app.services import llm, memory, validate
from backend.tests.test_chat import _agent_calls, _route
from backend.tests.test_routers import JUDGED, POSITION, _candidate, _login, _request, _signals, fake  # noqa: F401

BLOCKS = ("<user_cargo>\n- 고추 (TEST*******001) · 마스터 B/L · 받아야 하는 날 2026-10-03\n</user_cargo>\n"
          "<user_memory>\n# 화물별\n## 고추 (TEST*******001)\n- 할 일: 은행에서 원본 B/L 받기 [ ] (9/28)\n</user_memory>")


def _with_memory(monkeypatch, blocks=BLOCKS):
    """로그인 사용자의 기억이 있다고 치고, 뒤 작업으로 넘어간 값을 모은다."""
    jobs = []
    monkeypatch.setattr(agent_router.memory_service, "load_context",
                        lambda user_id, bl_no=None: memory.MemoryContext(blocks=blocks) if user_id else None)
    monkeypatch.setattr(agent_router.memory_service, "remember_later",
                        lambda user_id, request, response, released: jobs.append((user_id, released, response.verdict)))
    return jobs


def _capture_judge(monkeypatch, answers):
    """가짜 판정 LLM. answers를 차례로 돌려주고 받은 인자를 모은다."""
    seen = []

    def judge(signal_set, customs, margin, **kwargs):
        seen.append(kwargs)
        return llm.LLMAnswer(output=llm.JudgeOutput.model_validate(answers[min(len(seen), len(answers)) - 1]),
                             llm=llm.LLMResult(content="", model="test/model"), prompt_version="test")
    monkeypatch.setattr(agent_router.llm, "judge", judge)
    return seen


def test_logged_in_judge_gets_memory_and_write_runs_after(fake, monkeypatch):
    """로그인 사용자: 판정 LLM에 기억 블록이 가고, 응답 뒤 기억 쓰기가 예약된다 (Spec 읽기·쓰기 흐름)."""
    fake(candidates=[_candidate(440999001)], position=POSITION)
    _signals(monkeypatch, {"eta_conflict": "triggered"})
    headers, jobs = _login(monkeypatch), _with_memory(monkeypatch)
    seen = _capture_judge(monkeypatch, [JUDGED])

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request(), headers=headers).json()

    assert seen[0]["memory"] == BLOCKS
    assert body["verdict"] == "watch" and body["decided_by"] == "rule"  # 등급은 지금처럼 판정 표 (EC-01)
    assert jobs == [("user-123", False, "watch")]


def test_answer_may_mention_remembered_date(fake, monkeypatch):
    """기억 블록 속 날짜(10/3)를 짚는 답은 V7(근거 없는 숫자)에 걸리지 않는다. 기억도 LLM이 받은 자료다."""
    fake(candidates=[_candidate(440999001)], position=POSITION)
    _signals(monkeypatch, {"eta_conflict": "triggered"})
    headers = _login(monkeypatch)
    _with_memory(monkeypatch)
    seen = _capture_judge(monkeypatch, [{**JUDGED, "answer": "말씀하신 2026-10-03까지 받으셔야 해서 한 번 확인이 필요합니다."}])

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request(), headers=headers).json()

    assert len(seen) == 1 and body["answer"].startswith("말씀하신")


def test_leaked_memo_id_is_retried(fake, monkeypatch):
    """답에 메모 번호([c1])가 새어 나오면 V12로 다시 묻는다 (EC-09)."""
    fake(candidates=[_candidate(440999001)], position=POSITION)
    _signals(monkeypatch, {"eta_conflict": "triggered"})
    headers = _login(monkeypatch)
    _with_memory(monkeypatch)
    seen = _capture_judge(monkeypatch, [{**JUDGED, "answer": "[c1] 할 일을 먼저 하세요."}, JUDGED])

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request(), headers=headers).json()

    assert len(seen) == 2 and "V12" in seen[1]["feedback"] and body["answer"] == JUDGED["answer"]


def test_without_login_nothing_is_read_or_written(fake, monkeypatch):
    """로그인이 꺼진 채점 환경(EC-08): 기억을 읽지도 쓰지도 않고 판정 LLM 입력도 그대로다."""
    fake(candidates=[_candidate(440999001)], position=POSITION)
    _signals(monkeypatch, {"eta_conflict": "triggered"})
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(memory, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("DB에 붙으면 안 된다")))
    monkeypatch.setattr(memory, "run_later", lambda *a, **k: (_ for _ in ()).throw(AssertionError("뒤 작업 금지")))
    monkeypatch.setattr(agent_router, "_position_history", lambda mmsi: [])
    seen = _capture_judge(monkeypatch, [JUDGED])

    with TestClient(app) as client:
        assert client.post("/api/agent", json=_request()).status_code == 200

    assert seen[0]["memory"] is None


def test_released_cargo_is_reported_as_done(fake, monkeypatch):
    """반출이면 뒤 작업에 released=True가 간다. 화물 표가 끝난 화물(done)로 옮긴다."""
    from backend.app.schemas.customs import CustomsRecord
    from backend.tests.test_routers import NOW

    fake(customs=CustomsRecord(ship_name="TEST STAR", stage_name=agent_router.RELEASED_STAGE,
                               bl_masked="TEST****0001", fetched_at=NOW))
    headers, jobs = _login(monkeypatch), _with_memory(monkeypatch)
    with TestClient(app) as client:
        client.post("/api/agent", json=_request(), headers=headers)
    assert jobs == [("user-123", True, "fine")]


def test_follow_up_gets_memory_and_id_rule(fake, monkeypatch):
    fake()
    headers = _login(monkeypatch)
    _with_memory(monkeypatch)
    saved = agent_router._response(status="ok", verdict="watch", vessel_match="confirmed", answer="확인 필요")
    monkeypatch.setattr(agent_router, "_previous_response", lambda request, user_id=None: saved)
    seen = []

    def follow(question, response, feedback=None, memory=None, **kwargs):
        seen.append({"memory": memory, "feedback": feedback})
        text = "c2 항목을 확인하세요." if len(seen) == 1 else "은행에서 원본 B/L을 받는 일이 남아 있어요."
        return llm.LLMAnswer(output=llm.FollowUpOutput(in_scope=True, answer=text),
                             llm=llm.LLMResult(content="", model="test/model"), prompt_version="test")
    monkeypatch.setattr(agent_router.llm, "answer_follow_up", follow)

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request(follow_up_question="남은 일 뭐야?"), headers=headers).json()

    assert seen[0]["memory"] == BLOCKS and "V12" in seen[1]["feedback"]
    assert body["answer"].startswith("은행에서")


def test_follow_up_lookup_separates_same_masked_number(monkeypatch):
    """가린 번호가 같은 두 화물: 잠긴 원본을 열어 이번 B/L 줄만 쓴다 (EC-05)."""
    monkeypatch.setenv("BL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    mine, other = "MOCKBL20261002", "MOCKXX20261002"  # 둘 다 MOC*******1002
    rows = [({"answer": "다른 화물"}, crypto.encrypt(other)), ({"answer": "내 화물"}, crypto.encrypt(mine))]
    assert agent_router._same_cargo(rows, mine) == {"answer": "내 화물"}
    assert agent_router._same_cargo(rows[:1], mine) is None                      # 다른 화물로 확인된 줄만 있으면 다시 조회
    assert agent_router._same_cargo([({"answer": "옛 줄"}, None)], mine) == {"answer": "옛 줄"}  # 원본이 없던 줄은 예전처럼
    assert agent_router._same_cargo([], mine) is None


def test_chat_lookup_gets_previous_line(monkeypatch):
    """10-02 결정 4: 로그인 사용자가 다시 조회한 화물이면 답 끝에 코드가 쓴 한 줄. 후속 질문에는 안 붙인다."""
    notes = []
    monkeypatch.setattr(svc.memory, "lookup_notes",
                        lambda user_id, bl: notes.append((user_id, bl)) or ["지난 조회(10.01)에서는 지켜볼 것, 여유 3일이었어요."])
    _route(monkeypatch, intent="cargo", bl_ref="[BL1]", bl_type="MASTER")
    agent, run = _agent_calls()
    r = svc.handle("TESTBL01 괜찮아?", "s1", None, run, user_id="user-123")
    assert r.reply == "괜찮습니다\n지난 조회(10.01)에서는 지켜볼 것, 여유 3일이었어요."
    assert notes == [("user-123", "TESTBL01")]

    _route(monkeypatch, intent="follow_up", question="여유 며칠?")
    r = svc.handle("여유 며칠?", "s1", agent[0], run, user_id="user-123")
    assert r.reply == "괜찮습니다" and len(notes) == 1


def test_chat_passes_masked_text_to_memory(monkeypatch):
    """채팅 문장은 B/L을 가린 모양으로만 기억 뽑기 재료가 된다 (CLAUDE.md)."""
    seen = []
    monkeypatch.setattr(svc.memory, "lookup_notes", lambda user_id, bl: [])
    _route(monkeypatch, intent="cargo", bl_ref="[BL1]", bl_type="MASTER")

    def run(req):
        seen.append(memory._USER_TEXT.get())
        from backend.app.routers.agent import _response
        return _response(status="ok", answer="괜찮습니다")
    svc.handle("TESTBL01 10/3까지 받아야 해", "s1", None, run, user_id="user-123")
    assert seen == ["[BL1] 10/3까지 받아야 해"] and memory._USER_TEXT.get() is None


def test_memory_id_rule_unit():
    assert validate.check_memory_ids(["c1은 어떠세요?"])[0].rule == "V12"
    assert validate.check_memory_ids(["[u2] 선호대로 알려 드려요"])[0].rule == "V12"
    assert validate.check_memory_ids(["항차 c12로 확인"], evidence="voyage c12") == []  # 근거에 원래 있는 글자
    assert validate.check_memory_ids(["UC1234 화물은 괜찮습니다", "abc1 x"]) == []         # 낱말 안의 글자는 아니다
