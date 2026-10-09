"""회원 탈퇴 테스트 (삭제 3단계: routers/account.py 창구, services/account/account.py 순서 규칙, clients/supabase_admin.py).

진짜 Supabase는 부르지 않는다. httpx.delete와 DB 함수를 가짜로 바꿔 끼운다.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.clients import supabase_admin
from backend.app.main import app
from backend.app.services.account import account as account_service
from backend.tests.integration.test_routers import _login

SECRET = "sb_secret_test-only-value"


# ── 계정 삭제 요청 (clients/supabase_admin.py) ──

@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", SECRET)


def _fake_delete(monkeypatch, *statuses: int) -> list:
    """부를 때마다 statuses를 차례로 돌려주는 가짜 httpx.delete. 불린 기록을 돌려준다."""
    calls, codes = [], list(statuses)

    def delete(url, headers, timeout):
        calls.append({"url": url, "headers": headers})
        return httpx.Response(codes.pop(0), request=httpx.Request("DELETE", url))

    monkeypatch.setattr(supabase_admin.httpx, "delete", delete)
    return calls


def test_deletes_account_with_key_in_header_only(admin_env, monkeypatch):
    calls = _fake_delete(monkeypatch, 200)
    supabase_admin.delete_account("user-123")
    assert calls[0]["url"] == "https://test-project.supabase.co/auth/v1/admin/users/user-123"
    assert calls[0]["headers"] == {"apikey": SECRET} and SECRET not in calls[0]["url"]  # 키는 헤더에만


def test_already_gone_account_counts_as_done(admin_env, monkeypatch):
    """탈퇴를 두 번 눌러도 같은 결과. 404(이미 없음)는 재시도 없이 성공."""
    calls = _fake_delete(monkeypatch, 404)
    supabase_admin.delete_account("user-123")
    assert len(calls) == 1


def test_server_error_is_retried_then_reported(admin_env, monkeypatch):
    calls = _fake_delete(monkeypatch, 500, 500, 500)
    with pytest.raises(supabase_admin.AdminError) as e:
        supabase_admin.delete_account("user-123")
    assert e.value.kind == "failed" and e.value.code == 500 and len(calls) == 3  # 최초 1 + 재시도 2 (SDD 8절)


def test_forbidden_is_not_retried(admin_env, monkeypatch):
    """키가 틀렸으면(401·403) 다시 불러도 같다. 재시도하지 않는다."""
    calls = _fake_delete(monkeypatch, 403)
    with pytest.raises(supabase_admin.AdminError):
        supabase_admin.delete_account("user-123")
    assert len(calls) == 1


def test_missing_key_is_not_configured(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    with pytest.raises(supabase_admin.AdminError) as e:
        supabase_admin.delete_account("user-123")
    assert e.value.kind == "not_configured"


# ── 탈퇴 순서 (services/account/account.py)와 입구 (routers/account.py) ──

class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _db(monkeypatch, steps: list, fail: bool = False):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    if fail:
        def broken(*a, **k):
            raise ConnectionError("테스트")
        monkeypatch.setattr(account_service, "connect", broken)
    else:
        monkeypatch.setattr(account_service, "connect", lambda *a, **k: FakeConn())
    monkeypatch.setattr(account_service, "delete_user_queries", lambda conn, user_id: steps.append(("records", user_id)) or 2)
    # 회원 정보도 기록과 같은 단계에서 지운다 (docs/specs/user-profile.md EC-08)
    monkeypatch.setattr(account_service, "delete_profile", lambda conn, user_id: steps.append(("profile", user_id)) or 1)
    # 화물 비서 기억(화물 표·메모장)도 같은 단계에서 지운다 (docs/specs/memory.md "개인정보")
    monkeypatch.setattr(account_service, "forget_user", lambda conn, user_id: steps.append(("memory", user_id)) or 2)
    # 대화 목록도 같은 단계에서 지운다
    monkeypatch.setattr(account_service, "delete_conversations", lambda conn, user_id: steps.append(("conversations", user_id)) or 1)
    # 카카오톡 알림 토큰도 같은 단계에서 지운다
    monkeypatch.setattr(account_service, "delete_kakao_link", lambda conn, user_id: steps.append(("kakao", user_id)) or 1)
    # 하루 토큰 사용량 줄도 같은 단계에서 지운다
    monkeypatch.setattr(account_service.quota, "forget_user", lambda conn, user_id: steps.append(("quota", user_id)))


def test_withdraw_deletes_records_then_account(monkeypatch):
    headers, steps = _login(monkeypatch), []
    _db(monkeypatch, steps)
    monkeypatch.setattr(account_service, "delete_account", lambda user_id: steps.append(("account", user_id)))

    with TestClient(app) as client:
        resp = client.delete("/api/account", headers=headers)

    assert resp.status_code == 200 and resp.json() == {"deleted_records": 2, "account_deleted": True}
    assert steps == [("records", "user-123"), ("profile", "user-123"), ("memory", "user-123"),
                     ("conversations", "user-123"), ("kakao", "user-123"), ("quota", "user-123"),
                     ("account", "user-123")]  # 기록·회원 정보·기억·카카오 토큰 먼저, 계정 나중


def test_records_failure_keeps_account(monkeypatch):
    """기록을 못 지우면 계정은 건드리지 않는다. 계정이 먼저 사라지면 다시 탈퇴할 길이 없다."""
    headers, steps = _login(monkeypatch), []
    _db(monkeypatch, steps, fail=True)
    monkeypatch.setattr(account_service, "delete_account", lambda user_id: pytest.fail("기록 삭제 실패인데 계정을 지우면 안 된다"))

    with TestClient(app) as client:
        assert client.delete("/api/account", headers=headers).status_code == 503


def test_account_failure_is_reported_and_retry_finishes(monkeypatch):
    """계정 삭제가 실패하면 503. 다시 누르면 기록 0건 + 계정 삭제로 끝난다."""
    headers, steps = _login(monkeypatch), []
    _db(monkeypatch, steps)
    results = [supabase_admin.AdminError("failed", 500), None]

    def delete_account(user_id):
        r = results.pop(0)
        if r:
            raise r

    monkeypatch.setattr(account_service, "delete_account", delete_account)
    with TestClient(app) as client:
        assert client.delete("/api/account", headers=headers).status_code == 503
        assert client.delete("/api/account", headers=headers).status_code == 200


def test_withdraw_needs_login(monkeypatch):
    monkeypatch.setattr(account_service, "delete_user_queries", lambda *a: pytest.fail("로그인 없이 삭제까지 가면 안 된다"))
    with TestClient(app) as client:
        assert client.delete("/api/account").status_code == 401  # 로그인 꺼짐(사용자 없음)
    _login(monkeypatch)
    with TestClient(app) as client:
        assert client.delete("/api/account").status_code == 401  # 로그인 켜짐, 헤더 없음


def test_browser_may_send_delete():
    """CORS가 DELETE를 허용해야 화면에서 내 기록 삭제·탈퇴를 부를 수 있다 (전엔 GET·POST만)."""
    with TestClient(app) as client:
        resp = client.options("/api/account", headers={"Origin": "http://localhost:3000",
                                                       "Access-Control-Request-Method": "DELETE"})
    assert resp.status_code == 200 and "DELETE" in resp.headers["access-control-allow-methods"]
