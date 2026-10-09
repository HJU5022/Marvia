"""회원 정보 테스트 (docs/specs/user-profile.md, routers/profile.py, services/account/profile.py).

진짜 DB는 부르지 않는다. test_admin.FakeConn(user_profiles 흉내)과 테스트용 Fernet 열쇠를 쓴다.
"""
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import admin as admin_router
from backend.app.services.account import operators as ops
from backend.app.services.account import profile as svc
from backend.tests.integration.test_admin import OPERATOR, FakeConn, _login

GOOD = {"name": "김승욱", "phone": "010-1234-5678", "address": "서울특별시 강남구 테헤란로 1", "consent": True}


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("PII_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture
def db(monkeypatch, key):
    conn = FakeConn()
    ops.grant(conn, OPERATOR, "bootstrap", None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(ops, "open_conn", lambda: conn)
    return conn


# ── 검사와 마스킹 ──

def test_clean_requires_consent_first():
    with pytest.raises(svc.ProfileError) as e:
        svc.clean("김", "bad", "", consent=False)
    assert e.value.kind == "consent"  # EC-01: 동의가 다른 칸보다 먼저


@pytest.mark.parametrize("field,value,kind", [
    ("name", "", "name"), ("name", "가" * 31, "name"),
    ("phone", "02-123-4567", "phone"), ("phone", "010-12-34", "phone"),
    ("address", "서울", "address"),
])
def test_clean_rejects_bad_fields(field, value, kind):
    with pytest.raises(svc.ProfileError) as e:
        svc.clean(**{**GOOD, field: value})
    assert e.value.kind == kind


def test_clean_normalizes():
    p = svc.clean("  김  승욱 ", "010 1234 5678", " 서울특별시  강남구 ", True)
    assert (p.name, p.phone, p.address) == ("김 승욱", "01012345678", "서울특별시 강남구")
    assert svc.format_phone(p.phone) == "010-1234-5678" and svc.format_phone("0111234567") == "011-123-4567"


def test_masks():
    assert svc.mask_name("김승욱") == "김**"
    assert svc.mask_phone("01012345678") == "010-****-5678"
    assert svc.mask_address("서울특별시 강남구 테헤란로 1") == "서울특별시 강남구 ***"
    assert svc.mask_address("세종특별자치시") == "세종특별자치시 ***"


# ── 암호화 저장 ──

def test_db_gets_only_sealed_values(key):
    conn = FakeConn()
    svc.save(conn, "u1", svc.clean(**GOOD))
    stored = " ".join(conn.profiles["u1"])
    assert "김승욱" not in stored and "01012345678" not in stored and "테헤란로" not in stored
    assert svc.load(conn, "u1") == svc.Profile("김승욱", "01012345678", "서울특별시 강남구 테헤란로 1")


def test_no_key_saves_nothing(monkeypatch):
    monkeypatch.delenv("PII_ENCRYPTION_KEY", raising=False)
    conn = FakeConn()
    with pytest.raises(svc.ProfileError) as e:
        svc.save(conn, "u1", svc.clean(**GOOD))
    assert e.value.kind == "no_key" and conn.profiles == {}  # EC-04: 원문을 대신 저장하지 않는다


def test_changed_key_is_unreadable_not_crash(key, monkeypatch):
    conn = FakeConn()
    svc.save(conn, "u1", svc.clean(**GOOD))
    monkeypatch.setenv("PII_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert svc.load(conn, "u1") is None  # EC-07
    assert svc.masked_by_user(conn)["u1"]["unreadable"] is True


# ── API ──

def test_profile_flow_and_me_flag(db, monkeypatch):
    headers = _login(monkeypatch, "kim@example.com")
    with TestClient(app) as client:
        assert client.get("/api/me", headers=headers).json()["profile_complete"] is False
        assert client.get("/api/profile", headers=headers).status_code == 404
        assert client.put("/api/profile", json={**GOOD, "consent": False}, headers=headers).status_code == 400
        r = client.put("/api/profile", json=GOOD, headers=headers)
        assert r.status_code == 200 and r.json() == {"name": "김승욱", "phone": "010-1234-5678",
                                                      "address": "서울특별시 강남구 테헤란로 1"}
        assert client.get("/api/me", headers=headers).json()["profile_complete"] is True
        assert client.get("/api/profile", headers=headers).json()["phone"] == "010-1234-5678"


def test_profile_requires_login(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with TestClient(app) as client:
        assert client.put("/api/profile", json=GOOD).status_code == 401  # EC-05


def test_operator_sees_only_masked_profile(db, monkeypatch):
    svc.save(db, "u1", svc.clean(**GOOD))
    monkeypatch.setattr(admin_router, "list_users", lambda: [
        {"id": "u1", "email": "kim@example.com", "user_metadata": {"full_name": "Google Name"},
         "created_at": "2026-10-01T01:00:00Z", "last_sign_in_at": None},
        {"id": "u2", "email": "lee@example.com", "user_metadata": {"full_name": "이영희"},
         "created_at": "2026-09-30T01:00:00Z", "last_sign_in_at": None}])
    with TestClient(app) as client:
        r = client.get("/api/admin/customers", headers=_login(monkeypatch, OPERATOR))
    first, second = r.json()["items"]
    assert first["name_masked"] == "김**" and first["phone_masked"] == "010-****-5678"  # 입력한 이름이 구글 이름보다 먼저
    assert first["address_masked"] == "서울특별시 강남구 ***" and first["profile_complete"] is True
    assert second["name_masked"] == "이**" and second["phone_masked"] is None and second["profile_complete"] is False
    for raw in ["김승욱", "01012345678", "010-1234-5678", "테헤란로", "Google Name", "kim@example.com"]:
        assert raw not in r.text


@pytest.mark.parametrize("method,path", [("PUT", "/api/profile"), ("DELETE", "/api/history"), ("POST", "/api/admin/operators")])
def test_browser_preflight_allows_methods_the_screen_uses(method, path):
    """화면이 쓰는 메서드가 CORS에서 빠지면 브라우저는 사전 요청(OPTIONS)에서 막고 '연결 실패'로 보인다 (PUT 누락)."""
    with TestClient(app) as client:
        r = client.options(path, headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": method,
                                          "Access-Control-Request-Headers": "authorization,content-type"})
    assert r.status_code == 200 and method in r.headers["access-control-allow-methods"]


def test_pii_key_is_separate_from_bl_key(monkeypatch):
    """개인정보는 PII 열쇠로만 잠근다. B/L 열쇠만 있으면 저장하지 않는다."""
    from backend.app import crypto
    monkeypatch.delenv("PII_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("BL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert crypto.encrypt_pii("김승욱") is None and crypto.fingerprint("a@b.com") is None
    assert crypto.encrypt("TESTBL01") is not None  # B/L 쪽은 그대로
    monkeypatch.setenv("PII_ENCRYPTION_KEY", Fernet.generate_key().decode())
    sealed = crypto.encrypt_pii("김승욱")
    assert crypto.decrypt(sealed) is None and crypto.decrypt_pii(sealed) == "김승욱"  # 서로 다른 열쇠
