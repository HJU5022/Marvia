"""대화 저장(제목 LLM 포함)이 사용량 주인이 정해진 범위 안에서 맡겨지는지.

routers/chat.py가 _save_conversation을 session_scope 밖에서 부르면 뒤에서 도는 제목 LLM이 복사해 가는
문맥에 사용량 주인(quota.owner_var)이 없어 토큰이 하루 한도에 안 쌓였다. /api/chat과 /api/chat/stream 둘 다 본다.
키·DB·LLM은 부르지 않는다. svc.handle과 _save_conversation을 가짜로 끼운다.
"""
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import chat as chat_router
from backend.app.services.chat import chat as svc
from backend.app.services.account import quota


def _stubs(monkeypatch) -> list:
    owners: list = []
    monkeypatch.setattr(svc, "handle", lambda *a, **k: svc.ChatResult(kind="message", reply="안녕하세요"))
    monkeypatch.setattr(chat_router, "_save_conversation", lambda body, user_id, response: owners.append(quota.owner_var.get()))
    return owners


def test_chat_saves_conversation_inside_owner_scope(monkeypatch):
    owners = _stubs(monkeypatch)
    with TestClient(app) as client:
        r = client.post("/api/chat", json={"message": "안녕", "session_id": "s-title"})
    assert r.status_code == 200
    assert owners == ["session:s-title"]


def test_chat_stream_saves_conversation_inside_owner_scope(monkeypatch):
    owners = _stubs(monkeypatch)
    with TestClient(app) as client:
        r = client.post("/api/chat/stream", json={"message": "안녕", "session_id": "s-title"})
    assert r.status_code == 200 and "event: result" in r.text
    assert owners == ["session:s-title"]
