"""로그인이 꺼진 환경(user_id 없음)에서는 기억을 읽지도 쓰지도 않는다 (docs/specs/memory.md EC-08, 검증).

대상 세 길: POST /api/chat, POST /api/chat/stream, run_agent의 후속 질문.
DATABASE_URL을 켜 둔 채로 보는 것이 핵심이다. DB가 없어서가 아니라 "사용자가 없어서" 안 하는지를 본다.
읽기 = memory.connect(load_context·lookup_notes가 쓰는 DB 연결), 쓰기 = memory.run_later·memory.remember.
위반을 예외로 던지면 load_context가 삼켜 버리므로(기억은 부가 기능) 호출 기록을 모아 마지막에 비어 있는지 본다.
외부 API·DB·LLM 없이 돈다. 판정 흐름 가짜는 test_routers.py의 fake를 쓴다. B/L은 모의값이다.
"""
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import agent as agent_router
from backend.app.routers import chat as chat_module
from backend.app.services import llm
from backend.app.services.account import memory
from backend.tests.integration.test_chat import _route
from backend.tests.integration.test_chat_stream import _events
from backend.tests.integration.test_memory_wiring import _capture_judge
from backend.tests.integration.test_routers import JUDGED, POSITION, _candidate, _request, _signals, fake  # noqa: F401

MESSAGE = "TESTMBL0000001 괜찮아?"


def _spy(monkeypatch) -> list[str]:
    """로그인 꺼짐 + DB 켜짐 상태로 두고, 기억을 읽거나 쓰는 호출을 모두 기록한다."""
    calls: list[str] = []
    monkeypatch.delenv("SUPABASE_URL", raising=False)  # 로그인 기능이 꺼진 채점 환경: current_user_id가 None을 준다
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")  # DB가 있어도 사용자가 없으면 안 한다
    monkeypatch.setattr(memory, "connect", lambda *a, **k: calls.append("read:connect") or (_ for _ in ()).throw(RuntimeError("no db")))
    monkeypatch.setattr(memory, "run_later", lambda *a, **k: calls.append("write:run_later"))
    monkeypatch.setattr(memory, "remember", lambda *a, **k: calls.append("write:remember"))
    monkeypatch.setattr(agent_router, "_position_history", lambda mmsi: [])
    return calls


def _lookup(fake, monkeypatch):
    """화물 조회 한 번이 끝까지 도는 가짜 흐름. 판정 LLM이 받은 인자를 돌려준다."""
    fake(candidates=[_candidate(440999001)], position=POSITION)
    _signals(monkeypatch, {"eta_conflict": "triggered"})
    _route(monkeypatch, intent="cargo", bl_ref="[BL1]", bl_type="MASTER")
    return _capture_judge(monkeypatch, [JUDGED])


def test_chat_without_user_reads_and_writes_nothing(fake, monkeypatch):
    """EC-08: /api/chat, 사용자 없음. 판정은 그대로 나가고 기억 읽기·쓰기는 한 번도 없다."""
    calls = _spy(monkeypatch)
    seen = _lookup(fake, monkeypatch)

    with TestClient(app) as client:
        r = client.post("/api/chat", json={"message": MESSAGE, "session_id": "s1"})

    assert r.status_code == 200 and r.json()["kind"] == "cargo" and r.json()["agent"]["verdict"] == "watch"
    assert "지난 조회" not in r.json()["reply"]  # 지난 조회 줄도 없다
    assert seen[0]["memory"] is None
    assert calls == []


def test_chat_stream_without_user_reads_and_writes_nothing(fake, monkeypatch):
    """EC-08: /api/chat/stream(별도 스레드), 사용자 없음. 스레드 안에서도 기억을 건드리지 않는다."""
    calls = _spy(monkeypatch)
    seen = _lookup(fake, monkeypatch)

    with TestClient(app) as client:
        r = client.post("/api/chat/stream", json={"message": MESSAGE, "session_id": "s1"})

    events = _events(r.text)
    assert events[-1][0] == "result" and events[-1][1]["agent"]["verdict"] == "watch"  # 오류 이벤트가 아니다
    assert seen[0]["memory"] is None
    assert calls == []


def test_follow_up_without_user_reads_and_writes_nothing(fake, monkeypatch):
    """EC-08: run_agent 후속 질문, 사용자 없음. 후속 LLM에 기억 블록이 가지 않고 쓰기도 없다."""
    calls = _spy(monkeypatch)
    fake()
    saved = agent_router._response(status="ok", verdict="watch", vessel_match="confirmed", answer="확인 필요")
    monkeypatch.setattr(agent_router, "_previous_response", lambda request, user_id=None: saved)
    seen = []

    def follow(question, response, feedback=None, memory=None, **kwargs):
        seen.append(memory)
        return llm.LLMAnswer(output=llm.FollowUpOutput(in_scope=True, answer="한 번 확인이 필요합니다."),
                             llm=llm.LLMResult(content="", model="test/model"), prompt_version="test")
    monkeypatch.setattr(agent_router.llm, "answer_follow_up", follow)

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request(follow_up_question="상태가 어때?")).json()

    assert body["answer"] == "한 번 확인이 필요합니다." and seen == [None]
    assert calls == []


def test_run_agent_called_directly_without_user_reads_and_writes_nothing(fake, monkeypatch):
    """평가 실행기·데모처럼 코드에서 직접 부를 때(user_id 기본값 None)도 같다."""
    calls = _spy(monkeypatch)
    fake(candidates=[_candidate(440999001)], position=POSITION, judge=JUDGED)
    _signals(monkeypatch, {"eta_conflict": "triggered"})

    from backend.app.schemas.agent import AgentRequest
    response = agent_router.run_agent(AgentRequest(**_request()))

    assert response.verdict == "watch" and calls == []
    assert chat_module.run_agent is agent_router.run_agent  # 채팅 창구가 부르는 것도 같은 함수다


def test_control_logged_in_user_does_hit_the_spies(fake, monkeypatch):
    """대조군: 같은 감시 장치가 로그인 사용자에서는 실제로 울린다. 위 테스트의 "비어 있음"이 감시가 고장 난 탓이 아님을 보인다."""
    from backend.tests.integration.test_routers import _login

    headers = _login(monkeypatch)
    calls = _spy(monkeypatch)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")  # _spy가 지운 것을 되돌린다 (_login이 쓴 값)
    _lookup(fake, monkeypatch)

    with TestClient(app) as client:
        r = client.post("/api/chat", json={"message": MESSAGE, "session_id": "s1"}, headers=headers)

    assert r.status_code == 200
    assert "read:connect" in calls and "write:run_later" in calls
