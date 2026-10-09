"""운영자의 고객 수정·강제 탈퇴·마스킹 해제 테스트 (docs/specs/operator-admin.md 추가 절, services/account/customers.py).

진짜 DB·Supabase는 부르지 않는다. test_admin.FakeConn과 가짜 get_user·withdraw를 끼운다.
"""
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.account import customers as svc
from backend.app.services.account import operators as ops
from backend.app.services.account import profile as profile_svc
from backend.tests.integration.test_admin import OPERATOR, FakeConn, _login

USERS = {
    "u1": {"id": "u1", "email": "testuser1@marvia.test", "user_metadata": {"full_name": "testUser1"}},
    "op": {"id": "op", "email": OPERATOR, "user_metadata": {}},
}
REASON = "고객 전화 문의로 본인 확인이 필요함"


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("PII_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    conn = FakeConn()
    ops.grant(conn, OPERATOR, "bootstrap", None)
    profile_svc.save(conn, "u1", profile_svc.clean("테스트유저", "010-1111-2222", "서울특별시 중구 세종대로 1", True))
    monkeypatch.setattr(ops, "open_conn", lambda: conn)
    monkeypatch.setattr(svc, "get_user", lambda user_id: USERS.get(user_id))
    return conn


def test_unmask_needs_reason_and_records_first(db, monkeypatch):
    with pytest.raises(svc.CustomerError) as e:
        svc.unmask(db, "u1", "actor", OPERATOR, "확인용")  # 10자 미만
    assert e.value.kind == "reason" and db.actions == []  # EC-09: 기록도 원문도 없다
    raw = svc.unmask(db, "u1", "actor", OPERATOR, REASON)
    assert raw == {"email": "testuser1@marvia.test", "name": "테스트유저", "phone": "010-1111-2222",
                   "address": "서울특별시 중구 세종대로 1"}
    action, target, masked, actor, actor_enc, actor_masked, reason = db.actions[0][:7]
    assert (action, target, masked, reason) == ("unmask", "u1", "te***@m***.test", REASON)
    assert "testuser1@marvia.test" not in str(db.actions) and OPERATOR not in str(db.actions)  # 이력에 원문 이메일 없음
    assert actor_masked == ops.mask_email(OPERATOR) and svc.list_actions(db)[0]["actor_email"] == OPERATOR


def test_unmask_fails_closed_when_record_fails(db, monkeypatch):
    """기록을 못 쓰면 원문을 주지 않는다."""
    def broken(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(svc, "_record", broken)
    with pytest.raises(RuntimeError):
        svc.unmask(db, "u1", "actor", OPERATOR, REASON)


def test_update_keeps_rules_and_records(db):
    svc.update(db, "u1", "actor", OPERATOR, "새이름", "01099998888", "부산광역시 해운대구 우동 1")
    assert profile_svc.load(db, "u1").phone == "01099998888"
    assert db.actions[-1][0] == "customer_update"
    with pytest.raises(profile_svc.ProfileError):
        svc.update(db, "u1", "actor", OPERATOR, "새이름", "02-123-4567", "부산광역시 해운대구 우동 1")


def test_delete_guards(db, monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "withdraw", lambda user_id: calls.append(user_id) or 3)
    for user_id, actor, kind in [("op", "x", "is_operator"), ("u1", "u1", "self"), ("ghost", "x", "not_found")]:
        with pytest.raises(svc.CustomerError) as e:
            svc.delete(db, user_id, actor, OPERATOR)
        assert e.value.kind == kind
    assert calls == []
    assert svc.delete(db, "u1", "actor", OPERATOR) == 3 and calls == ["u1"]
    assert db.actions[-1][:3] == ("customer_delete", "u1", "te***@m***.test")


def test_api_flow(db, monkeypatch):
    monkeypatch.setattr(svc, "withdraw", lambda user_id: 0)
    headers = _login(monkeypatch, OPERATOR)
    with TestClient(app) as client:
        assert client.post("/api/admin/customers/u1/unmask", json={"reason": "짧음"}, headers=headers).status_code == 400
        r = client.post("/api/admin/customers/u1/unmask", json={"reason": REASON}, headers=headers)
        assert r.status_code == 200 and r.json()["phone"] == "010-1111-2222"
        assert client.put("/api/admin/customers/u1/profile", headers=headers,
                          json={"name": "수정", "phone": "010-3333-4444", "address": "대구광역시 중구 1"}).status_code == 200
        assert client.delete("/api/admin/customers/op", headers=headers).status_code == 409
        assert client.delete("/api/admin/customers/u1", headers=headers).json() == {"deleted_records": 0}
        actions = client.get("/api/admin/actions", headers=headers).json()
        assert [a["action"] for a in actions] == ["customer_delete", "customer_update", "unmask"]
        assert actions[2]["reason"] == REASON


def test_customer_api_forbids_non_operator(db, monkeypatch):
    headers = _login(monkeypatch, "kim@example.com")
    with TestClient(app) as client:
        assert client.post("/api/admin/customers/u1/unmask", json={"reason": REASON}, headers=headers).status_code == 403
        assert client.delete("/api/admin/customers/u1", headers=headers).status_code == 403
    assert db.actions == []


# ── 일시 정지 ──

def test_suspend_rules_and_ban(db, monkeypatch):
    bans = []
    monkeypatch.setattr(svc, "set_ban", lambda user_id, banned: bans.append((user_id, banned)))
    for args, kind in [(("u1", "a", OPERATOR, "짧음"), "reason"), (("op", "a", OPERATOR, REASON), "is_operator"),
                       (("u1", "u1", OPERATOR, REASON), "self")]:
        with pytest.raises(svc.CustomerError) as e:
            svc.suspend(db, *args)
        assert e.value.kind == kind
    assert bans == []  # 규칙 위반이면 Supabase도 건드리지 않는다
    svc.suspend(db, "u1", "a", OPERATOR, REASON)
    assert svc.is_suspended(db, "u1") and bans == [("u1", True)] and db.actions[-1][0] == "customer_suspend"
    with pytest.raises(svc.CustomerError) as e:
        svc.suspend(db, "u1", "a", OPERATOR, REASON)
    assert e.value.kind == "already_suspended"
    svc.resume(db, "u1", "a", OPERATOR)
    assert not svc.is_suspended(db, "u1") and bans[-1] == ("u1", False) and db.actions[-1][0] == "customer_resume"


def test_ban_failure_leaves_db_untouched(db, monkeypatch):
    from backend.app.clients.supabase_admin import AdminError

    def broken(user_id, banned):
        raise AdminError("failed", 500)
    monkeypatch.setattr(svc, "set_ban", broken)
    with pytest.raises(AdminError):
        svc.suspend(db, "u1", "a", OPERATOR, REASON)
    assert not svc.is_suspended(db, "u1") and db.actions == []


def test_suspended_user_is_blocked_everywhere(db, monkeypatch):
    """정지되면 이미 받은 출입증으로도 403 account_suspended (auth.current_user)."""
    monkeypatch.setattr(svc, "set_ban", lambda *a: None)
    svc.suspend(db, "u1", "a", OPERATOR, REASON)
    import jwt as _jwt
    headers = _login(monkeypatch, "testuser1@marvia.test")
    token = headers["Authorization"].split()[1]
    assert _jwt.decode(token, options={"verify_signature": False})["sub"] == "user-123"
    db.suspended["user-123"] = ("a", REASON)  # 도장의 sub(user-123)를 정지 목록에
    with TestClient(app) as client:
        r = client.get("/api/me", headers=headers)
        assert r.status_code == 403 and r.json()["detail"] == "account_suspended"
        assert client.post("/api/agent", headers=headers, json={"bl_no": "TESTBL01", "bl_type": "HOUSE", "session_id": "s"}).status_code == 403


def test_suspend_api_and_list_flag(db, monkeypatch):
    monkeypatch.setattr(svc, "set_ban", lambda *a: None)
    from backend.app.routers import admin as admin_router
    monkeypatch.setattr(admin_router, "list_users", lambda: [{"id": "u1", "email": "testuser1@marvia.test", "user_metadata": {}}])
    headers = _login(monkeypatch, OPERATOR)
    with TestClient(app) as client:
        assert client.post("/api/admin/customers/u1/suspend", json={"reason": "짧음"}, headers=headers).status_code == 400
        assert client.post("/api/admin/customers/u1/suspend", json={"reason": REASON}, headers=headers).status_code == 200
        assert client.get("/api/admin/customers", headers=headers).json()["items"][0]["is_suspended"] is True
        assert client.post("/api/admin/customers/u1/resume", headers=headers).status_code == 200
        assert client.post("/api/admin/customers/u1/resume", headers=headers).status_code == 409
