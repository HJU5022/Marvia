"""처리 단계 소식 테스트 (docs/specs/chat-progress.md, services/chat/progress.py, routers/chat.py POST /api/chat/stream).

키·DB 없이 돈다. 스트림 라우터는 handle을 가짜로 끼워 이벤트 모양만 보고,
단계 순서는 데모 3건(test_demo.py와 같은 재생 폴더)을 실제 판정 경로(run_agent)로 돌려 확인한다.
"""
import json
import shutil
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.app.clients import replay
from backend.app.clients.shipfinder import ShipFinderClient
from backend.app.main import app
from backend.app.routers import chat as chat_router
from backend.app.services.chat import chat as svc
from backend.app.services.chat import progress
from backend.tests.integration.test_demo import RECORDING
from scripts.demo import make_demo


def _events(text: str) -> list[tuple[str, dict]]:
    """SSE 본문을 (이벤트 이름, JSON) 목록으로. 주석 줄(: ping)은 건너뛴다."""
    out = []
    for block in text.split("\n\n"):
        lines = [x for x in block.splitlines() if x and not x.startswith(":")]
        if not lines:
            continue
        name = next(x[7:] for x in lines if x.startswith("event: "))
        data = next(x[6:] for x in lines if x.startswith("data: "))
        out.append((name, json.loads(data)))
    return out


def test_step_without_listener_does_nothing():
    progress.step("customs")  # 듣는 쪽이 없으면 조용히 지나간다 (/api/agent·평가 실행기)


def test_listener_gets_known_stages_only():
    heard = []
    with progress.listening(heard.append):
        progress.step("customs")
        progress.step("not-a-stage")  # 정한 이름 밖은 보내지 않는다
        progress.step("judge")
    progress.step("identify")  # with 밖은 안 들린다
    assert heard == ["customs", "judge"]


def test_broken_listener_does_not_stop_work():
    def broken(stage):
        raise RuntimeError("화면 연결 끊김")
    with progress.listening(broken):
        progress.step("customs")  # 예외가 밖으로 나오면 판정이 멈춘다


def test_stream_sends_progress_then_same_result_as_chat(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)

    # user_id: 화물 비서 기억. history·run_tool: 채팅 에이전트
    def fake_handle(message, session_id, context, run_agent, user_id=None, history=None, run_tool=None, watch=None, kakao=None):
        progress.step("understand")
        progress.step("customs")
        return svc.ChatResult(kind="message", reply="B/L 번호를 넣어 주세요")
    monkeypatch.setattr(svc, "handle", fake_handle)
    body = {"message": "안녕", "session_id": "s1"}
    with TestClient(app) as client:
        r = client.post("/api/chat/stream", json=body)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = _events(r.text)
        plain = client.post("/api/chat", json=body).json()
    assert events[:2] == [("progress", {"stage": "understand"}), ("progress", {"stage": "customs"})]
    assert events[-1] == ("result", plain)  # 최종 결과는 /api/chat 응답과 같은 모양


def test_stream_reports_bad_message_and_crash_as_error_event(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with TestClient(app) as client:
        assert _events(client.post("/api/chat/stream", json={"message": "  ", "session_id": "s1"}).text) == [
            ("error", {"status": 400, "detail": chat_router.BAD_MESSAGE})]
        assert client.post("/api/chat/stream", json={"message": "가" * 501, "session_id": "s1"}).status_code == 422

        def crash(*args, **kwargs):  # 라우터가 history·run_tool을 이름으로 넘긴다
            raise RuntimeError("TESTBL01 비밀")  # 예외 메시지는 화면에도 로그에도 가지 않는다
        monkeypatch.setattr(svc, "handle", crash)
        events = _events(client.post("/api/chat/stream", json={"message": "안녕", "session_id": "s1"}).text)
    assert events == [("error", {"status": 500, "detail": chat_router.STREAM_FAILED})]


def test_real_flow_stage_order(tmp_path, monkeypatch):
    """데모 3건을 실제 판정 경로로 돌려, 단계가 실제로 지난 곳까지만 순서대로 나오는지 본다."""
    from backend.app.routers import agent
    from backend.app.schemas.agent import AgentRequest

    for key in ("LLM_MODEL", "OPENROUTER_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
                "DATABASE_URL", "SHIPFINDER_KEY", "UNIPASS_KEY", "DATA_GO_KR_KEY",
                "MCP_URL"):  # Dockerfile이 MCP_URL을 박아 둔다. 남아 있으면 없는 서버에 HTTP로 붙다가 partial이 된다
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("REPLAY_MODE", "true")
    monkeypatch.setattr(replay, "REPLAY_DIR", tmp_path)
    ShipFinderClient.cache.clear()
    (tmp_path / "llm").mkdir()
    shutil.copy(RECORDING, tmp_path / "llm" / RECORDING.name)
    guide = {g["case_id"]: g for g in make_demo.build(datetime.now(timezone.utc), tmp_path)}

    def stages(case_id: str) -> tuple[str, list[str]]:
        g, heard = guide[case_id], []
        with progress.listening(heard.append):
            r = agent.run_agent(AgentRequest(bl_no=g["bl_no"], bl_type="HOUSE", session_id=f"s-{case_id}",
                                             sale_due_date=g["sale_due_date"]))
        return r.status, heard

    assert stages("N01") == ("ok", ["customs", "identify", "position", "judge"])  # 정상: 판정까지
    assert stages("B01") == ("insufficient", ["customs", "identify"])  # 되묻기: 식별에서 멈춘다
    # 위치 권한 없음: 위치 조회까지 가고 LLM 판정은 부르지 않는다 (routers/agent._no_position)
    assert stages("F04") == ("partial", ["customs", "identify", "position"])
