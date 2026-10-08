"""1명당 하루 LLM 토큰 한도 테스트 (docs/specs/token-quota.md). 키·DB 없이 메모리 저장으로 돈다.

지키는 것
- LLM 호출마다 그 사람 사용량에 입력+출력 토큰이 쌓인다
- 요청 시작 때 한도 이상이면 429 daily_token_limit
- 처리 도중 한도를 넘어도 그 요청은 끝까지 답한다 (같은 요청 안에서는 다시 확인하지 않는다)
- 한도 환경변수가 비면 막지 않는다
"""
import contextvars

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.observability.langfuse import session_scope
from backend.app.routers.agent import QUOTA_DETAIL, quota_guard
from backend.app.services import llm
from backend.app.services.account import quota


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)  # 로그인 끔: 세션 기준으로 센다
    monkeypatch.setenv(quota.LIMIT_ENV, "100")
    quota.reset_memory()
    yield
    quota.reset_memory()


def _fresh(fn, *args):
    """요청 하나처럼 새 문맥에서 돌린다. checked_var가 요청마다 처음 값이 되는 것과 같다."""
    return contextvars.Context().run(fn, *args)


def test_llm_call_adds_prompt_and_completion_tokens(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test/model")
    monkeypatch.setattr(llm, "_call_once", lambda kwargs: llm.LLMResult(content="{}", prompt_tokens=30, completion_tokens=12))

    def call():
        with session_scope("s1", None):
            llm.chat([{"role": "user", "content": "q"}])
    _fresh(call)
    assert quota.used("session:s1") == 42


def test_tokens_go_to_user_not_session_when_logged_in(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test/model")
    monkeypatch.setattr(llm, "_call_once", lambda kwargs: llm.LLMResult(content="{}", prompt_tokens=5, completion_tokens=5))

    def call():
        with session_scope("s1", "u-1"):
            llm.chat([{"role": "user", "content": "q"}])
    _fresh(call)
    assert quota.used("user:u-1") == 10 and quota.used("session:s1") == 0


def test_request_is_blocked_when_limit_reached():
    def spend():
        with session_scope("s1", None):
            quota.add(100)
    _fresh(spend)
    with pytest.raises(HTTPException) as e:
        _fresh(quota_guard, "s1", None)
    assert e.value.status_code == 429 and e.value.detail == QUOTA_DETAIL
    _fresh(quota_guard, "other-session", None)  # 다른 사람은 막지 않는다


def test_request_that_crosses_limit_finishes():
    """시작할 때 한도 아래였으면, 처리 도중 넘어도 같은 요청 안에서는 다시 막지 않는다 (/api/chat 안의 run_agent)."""
    from backend.app.observability.logging import request_id_var

    def one_request():
        request_id_var.set("req-1")  # 미들웨어가 요청마다 붙이는 ID
        quota_guard("s1", None)  # 시작: 0 < 100 통과
        with session_scope("s1", None):
            quota.add(150)  # 처리 도중 한도 넘김
        quota_guard("s1", None)  # 같은 요청 안의 두 번째 확인은 건너뛴다
        return "answered"
    assert _fresh(one_request) == "answered"
    with pytest.raises(HTTPException):
        _fresh(quota_guard, "s1", None)  # 다음 요청부터 막힌다


def test_no_limit_when_env_empty(monkeypatch):
    monkeypatch.setenv(quota.LIMIT_ENV, "")
    def spend():
        with session_scope("s1", None):
            quota.add(10_000)
    _fresh(spend)
    _fresh(quota_guard, "s1", None)  # 막지 않는다
    assert quota.status("s1", None)["limit"] is None


def test_usage_endpoint_reports_exhausted_and_near_limit():
    def spend(n):
        def run():
            with session_scope("s1", None):
                quota.add(n)
        _fresh(run)
    with TestClient(app) as client:
        spend(95)
        body = client.get("/api/usage", params={"session_id": "s1"}).json()
        assert body == {"limit": 100, "used": 95, "remaining": 5, "exhausted": False, "near_limit": True}
        spend(5)
        body = client.get("/api/usage", params={"session_id": "s1"}).json()
        assert body["exhausted"] is True and body["remaining"] == 0


def test_agent_route_returns_429_when_exhausted():
    def spend():
        with session_scope("s1", None):
            quota.add(100)
    _fresh(spend)
    with TestClient(app) as client:
        res = client.post("/api/agent", json={"bl_no": "TESTBL01", "bl_type": "HOUSE", "session_id": "s1"})
    assert res.status_code == 429 and res.json()["detail"] == QUOTA_DETAIL


def test_operator_is_not_blocked(monkeypatch):
    """운영자는 한도를 다 써도 막지 않는다. 운영자 판단은 로그인 이메일로 한다."""
    from backend.app.observability.logging import request_user_var
    from backend.app.services.account import operators

    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(quota, "used", lambda owner, day=None: 1_000)  # 이미 한도(100)를 넘김
    monkeypatch.setattr(operators, "open_conn", lambda: __import__("contextlib").nullcontext(object()))
    monkeypatch.setattr(operators, "is_operator", lambda conn, email: email == "op@test.example")

    def as_user(email):
        request_user_var.set({"email": email})
        quota_guard("s1", "u-1")

    _fresh(as_user, "op@test.example")  # 운영자: 통과
    with pytest.raises(HTTPException):
        _fresh(as_user, "user@test.example")  # 일반 사용자: 막힘
