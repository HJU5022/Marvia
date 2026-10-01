"""운영자 관리 테스트 (docs/specs/operator-admin.md, routers/admin.py, services/operators.py).

진짜 DB와 Supabase는 부르지 않는다. services/operators.py가 보내는 SQL 문장을 흉내 내는 가짜 연결과
가짜 list_users를 끼운다. 실제 SQL은 서버 기동 때 009 마이그레이션 적용과 화면 확인으로 본다.
"""
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.clients import supabase_admin
from backend.app.main import app
from backend.app.routers import admin as admin_router
from backend.app.services import operators as ops

OPERATOR = "boss@marvia.test"
CUSTOMER = "kim@example.com"


class _Result:
    def __init__(self, rows=None, rowcount=0):
        self._rows, self.rowcount = rows or [], rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class FakeConn:
    """operators·operator_audit 두 표만 메모리에 둔다. 문장 앞부분으로 어떤 SQL인지 가른다."""

    def __init__(self):
        self.operators: dict[str, dict] = {}
        self.audit: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, params=()):
        q = " ".join(sql.split())
        now = datetime.now(timezone.utc)
        if q.startswith("SELECT 1 FROM operators"):
            row = self.operators.get(params[0])
            return _Result([(1,)] if row and row["revoked_at"] is None else [])
        if q.startswith("SELECT email FROM operators"):
            return _Result([(e,) for e, r in self.operators.items() if r["revoked_at"] is None])
        if q.startswith("SELECT revoked_at FROM operators"):
            row = self.operators.get(params[0])
            return _Result([(row["revoked_at"],)] if row else [])
        if q.startswith("INSERT INTO operators"):
            self.operators[params[0]] = {"granted_by": params[1], "granted_at": now, "revoked_by": None, "revoked_at": None}
            return _Result(rowcount=1)
        if q.startswith("UPDATE operators SET revoked_by"):
            row = self.operators.get(params[1])
            if not row or row["revoked_at"] is not None:
                return _Result(rowcount=0)
            row.update(revoked_by=params[0], revoked_at=now)
            return _Result(rowcount=1)
        if q.startswith("INSERT INTO operator_audit"):
            self.audit.append({"action": params[0], "target_email": params[1], "actor_user_id": params[2],
                               "actor_email": params[3], "created_at": now})
            return _Result(rowcount=1)
        if q.startswith("SELECT email, granted_by, granted_at"):
            return _Result([(e, r["granted_by"], r["granted_at"]) for e, r in self.operators.items() if r["revoked_at"] is None])
        if q.startswith("SELECT action, target_email"):
            rows = [(a["action"], a["target_email"], a["actor_user_id"], a["actor_email"], a["created_at"])
                    for a in reversed(self.audit)]
            return _Result(rows[: params[0]])
        raise AssertionError(f"예상하지 못한 SQL: {q}")


# ── 마스킹 ──

def test_mask_email_keeps_only_hints():
    assert ops.mask_email("kim.seunguk@gmail.com") == "ki***@g***.com"
    assert ops.mask_email("ab@naver.co.kr") == "a***@n***.kr"  # 2자 아이디는 1자만
    assert ops.mask_email(None) is None and ops.mask_email("not-an-email") is None


def test_mask_name():
    assert ops.mask_name("김승욱") == "김**"
    assert ops.mask_name("  ") is None and ops.mask_name(None) is None


def test_normalize_email_lowercases_and_rejects_typos():
    assert ops.normalize_email("  Boss@Marvia.Test ") == "boss@marvia.test"
    for bad in ["", "no-at-sign", "a@b", "a b@c.com"]:
        with pytest.raises(ops.OperatorError) as e:
            ops.normalize_email(bad)
        assert e.value.kind == "invalid_email"


def test_customers_never_carry_raw_email_or_name():
    users = [{"id": "u1", "email": "Kim@Example.com", "user_metadata": {"full_name": "김승욱"},
              "created_at": "2026-09-30T01:00:00Z", "last_sign_in_at": "2026-10-01T01:00:00Z"}]
    [c] = ops.mask_customers(users, {"kim@example.com"})
    assert c.is_operator  # 대문자 이메일도 운영자 표와 맞춘다
    assert "kim@example.com" not in str(c.__dict__).lower() and "김승욱" not in str(c.__dict__)


# ── 등록·해지 규칙 ──

def test_grant_revoke_and_audit_trail():
    conn = FakeConn()
    ops.grant(conn, OPERATOR, ops.BOOTSTRAP_ACTOR, None)
    ops.grant(conn, "New@Marvia.test", "user-1", OPERATOR)
    assert ops.is_operator(conn, "new@marvia.test")
    ops.revoke(conn, "new@marvia.test", "user-1", OPERATOR)
    assert not ops.is_operator(conn, "new@marvia.test")
    ops.grant(conn, "new@marvia.test", "user-1", OPERATOR)  # EC-05 다시 등록
    assert [(a["action"], a["target_email"]) for a in conn.audit] == [
        ("grant", OPERATOR), ("grant", "new@marvia.test"), ("revoke", "new@marvia.test"), ("grant", "new@marvia.test")]
    assert conn.audit[0]["actor_user_id"] == "bootstrap"


def test_duplicate_grant_is_rejected_without_audit():
    conn = FakeConn()
    ops.grant(conn, OPERATOR, "bootstrap", None)
    with pytest.raises(ops.OperatorError) as e:
        ops.grant(conn, OPERATOR.upper(), "user-1", OPERATOR)
    assert e.value.kind == "already" and len(conn.audit) == 1  # EC-03


def test_cannot_revoke_self_or_unknown():
    conn = FakeConn()
    ops.grant(conn, OPERATOR, "bootstrap", None)
    with pytest.raises(ops.OperatorError) as e:
        ops.revoke(conn, OPERATOR, "user-1", OPERATOR)
    assert e.value.kind == "self_revoke"  # EC-04
    with pytest.raises(ops.OperatorError) as e:
        ops.revoke(conn, "ghost@marvia.test", "user-1", OPERATOR)
    assert e.value.kind == "not_found"


# ── API ──

def _login(monkeypatch, email: str) -> dict:
    """로그인 켬 + 테스트 도장 (test_routers._login과 같은 방식, email 클레임 추가)."""
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec

    from backend.app import auth

    key = ec.generate_private_key(ec.SECP256R1())
    base = "https://test-project.supabase.co"
    monkeypatch.setenv("SUPABASE_URL", base)
    monkeypatch.setattr(auth, "_signing_key", lambda token, base_url: key.public_key())
    token = jwt.encode({"sub": "user-123", "email": email, "aud": "authenticated", "iss": f"{base}/auth/v1",
                        "exp": int(time.time()) + 3600}, key, algorithm="ES256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def db(monkeypatch):
    conn = FakeConn()
    ops.grant(conn, OPERATOR, "bootstrap", None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(ops, "open_conn", lambda: conn)
    return conn


def test_me_reports_operator_flag(db, monkeypatch):
    with TestClient(app) as client:
        r = client.get("/api/me", headers=_login(monkeypatch, OPERATOR.upper()))
        assert r.json() == {"user_id": "user-123", "email": OPERATOR, "is_operator": True}
        r = client.get("/api/me", headers=_login(monkeypatch, CUSTOMER))
        assert r.json()["is_operator"] is False


def test_me_without_login_feature(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with TestClient(app) as client:
        assert client.get("/api/me").json() == {"user_id": None, "email": None, "is_operator": False}  # EC-02


def test_admin_api_forbids_non_operators(db, monkeypatch):
    headers = _login(monkeypatch, CUSTOMER)
    with TestClient(app) as client:
        assert client.get("/api/admin/customers", headers=headers).status_code == 403  # EC-01
        assert client.post("/api/admin/operators", json={"email": "x@y.com"}, headers=headers).status_code == 403
    assert len(db.audit) == 1  # 막힌 요청은 이력을 남기지 않는다


def test_customers_are_masked(db, monkeypatch):
    monkeypatch.setattr(admin_router, "list_users", lambda: [
        {"id": "u1", "email": CUSTOMER, "user_metadata": {"name": "Kim"}, "created_at": "2026-09-30T01:00:00Z",
         "last_sign_in_at": None}])
    with TestClient(app) as client:
        r = client.get("/api/admin/customers", headers=_login(monkeypatch, OPERATOR))
    assert r.status_code == 200 and CUSTOMER not in r.text
    assert r.json()["items"][0]["email_masked"] == "ki***@e***.com" and r.json()["total"] == 1


def test_customers_503_when_admin_key_missing(db, monkeypatch):
    def broken():
        raise supabase_admin.AdminError("not_configured")
    monkeypatch.setattr(admin_router, "list_users", broken)
    with TestClient(app) as client:
        assert client.get("/api/admin/customers", headers=_login(monkeypatch, OPERATOR)).status_code == 503  # EC-07


def test_grant_and_revoke_through_api(db, monkeypatch):
    headers = _login(monkeypatch, OPERATOR)
    with TestClient(app) as client:
        r = client.post("/api/admin/operators", json={"email": "New@Marvia.test"}, headers=headers)
        assert r.status_code == 200 and {o["email"] for o in r.json()["operators"]} == {OPERATOR, "new@marvia.test"}
        assert r.json()["audit"][0] == {**r.json()["audit"][0], "action": "grant", "actor_email": OPERATOR,
                                        "actor_user_id": "user-123"}
        assert client.post("/api/admin/operators", json={"email": "new@marvia.test"}, headers=headers).status_code == 409
        assert client.post("/api/admin/operators", json={"email": "bad"}, headers=headers).status_code == 400
        assert client.post("/api/admin/operators/revoke", json={"email": OPERATOR}, headers=headers).status_code == 400
        r = client.post("/api/admin/operators/revoke", json={"email": "new@marvia.test"}, headers=headers)
        assert r.status_code == 200 and r.json()["audit"][0]["action"] == "revoke"
