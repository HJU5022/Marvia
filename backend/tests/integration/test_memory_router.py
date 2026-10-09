"""화물 비서 기억 창구 테스트 (routers/memory.py, schemas/memory.py, docs/specs/memory.md "API", 결정 7).

DB 없이 돈다. connect와 서비스 함수를 가짜로 끼운다. B/L은 모의값이다.
"""
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import memory as memory_router
from backend.tests.integration.test_routers import _login

BL = "MOCKBL20261002"
FACTS = {"bl_no": BL, "bl_type": "HOUSE", "source": "B/L", "original_bl": "required", "to_order_bank": True,
         "freight_term": "collect", "incoterm": "FOB",
         "contact": {"company": "가나다물류", "role": "포워더", "phone": "051-000-0000"}}


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(memory_router, "connect", lambda *a, **k: FakeConn())


@pytest.mark.parametrize("method, path, body", [
    ("get", "/api/memory", None), ("delete", "/api/memory", None), ("delete", "/api/memory/items/c1", None),
    ("post", "/api/memory/document-facts", FACTS),
])
def test_login_required_everywhere(monkeypatch, db, method, path, body):
    """로그인 꺼진 환경(EC-08)과 헤더 없는 요청은 401. 서비스까지 가지 않는다."""
    monkeypatch.setattr(memory_router.memory, "view", lambda *a: pytest.fail("로그인 없이 읽으면 안 된다"))
    monkeypatch.setattr(memory_router.memory, "delete_all", lambda *a: pytest.fail("로그인 없이 지우면 안 된다"))
    monkeypatch.setattr(memory_router.cargo, "apply_document_facts", lambda *a: pytest.fail("로그인 없이 쓰면 안 된다"))
    kwargs = {"json": body} if body else {}
    with TestClient(app) as client:
        assert getattr(client, method)(path, **kwargs).status_code == 401  # 로그인 꺼짐
    _login(monkeypatch)
    with TestClient(app) as client:
        assert getattr(client, method)(path, **kwargs).status_code == 401  # 로그인 켜짐, 헤더 없음


def test_view_hides_raw_bl_and_key(monkeypatch, db):
    headers = _login(monkeypatch)
    row = {"cargo_key": "secret-key", "bl_masked": "MOC*******1002", "bl_type": "HOUSE", "label": "고추",
           "status": "active", "sale_due_date": None, "forwarder_eta": None, "original_bl": "required",
           "to_order_bank": None, "freight_term": "collect", "incoterm": None, "last_verdict": "watch",
           "last_checked_at": None, "last_days_margin": 3, "last_eta": None, "last_stage": "반입신고",
           "pending": [{"field": "sale_due_date", "value": "2026-10-03", "noted_at": "2026-10-02"}],
           "vessel_mmsi": 440999001}
    item = {"id": "c1", "section": "cargo", "cargo_key": "secret-key", "kind": "todo",
            "fields": {"text": "은행에서 원본 B/L 받기", "done": False}, "noted_at": "2026-09-28"}
    monkeypatch.setattr(memory_router.memory, "view", lambda conn, user_id: {
        "markdown": "# 화물별\n## 고추 (MOC*******1002)\n- 할 일: 은행에서 원본 B/L 받기 [ ] (9/28)",
        "items": [item], "cargo": [row], "full": True})
    with TestClient(app) as client:
        body = client.get("/api/memory", headers=headers).json()
    assert body["available"] is True and body["full"] is True
    assert body["used_chars"] == len(body["markdown"]) and body["max_chars"] == 3000  # 메모장 N/3000자 (M5)
    assert body["items"][0]["cargo_name"] == "고추 (MOC*******1002)" and "[c1]" not in body["markdown"]
    assert body["cargo"][0]["pending"][0]["value"] == "2026-10-03"
    text = str(body)
    assert "secret-key" not in text and BL not in text and "440999001" not in text


def test_view_without_db_is_unavailable(monkeypatch):
    headers = _login(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        body = client.get("/api/memory", headers=headers).json()
    assert body["available"] is False and body["items"] == []


def test_delete_all_and_one(monkeypatch, db):
    headers = _login(monkeypatch)
    asked = []
    # 메모장 전부 지우기는 메모장만 지운다 (결정 D2). 화물 표를 지우는 forget_user는 부르지 않는다
    monkeypatch.setattr(memory_router.memory, "forget_user", lambda *a: pytest.fail("화물 표는 지우지 않는다"))
    monkeypatch.setattr(memory_router.memory, "delete_all", lambda conn, user_id: asked.append(user_id) or 3)
    status = {"c1": "deleted", "c9": "missing", "c5": "conflict"}
    monkeypatch.setattr(memory_router.memory, "delete_item", lambda conn, user_id, item_id: status[item_id])
    with TestClient(app) as client:
        assert client.delete("/api/memory", headers=headers).json() == {"deleted": 3}
        assert client.delete("/api/memory/items/c1", headers=headers).json() == {"deleted": 1}
        assert client.delete("/api/memory/items/c9", headers=headers).status_code == 404
        assert client.delete("/api/memory/items/c5", headers=headers).status_code == 503  # 동시 수정 충돌은 404 아님
    assert asked == ["user-123"]


def test_delete_failure_is_not_hidden(monkeypatch):
    headers = _login(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        assert client.delete("/api/memory", headers=headers).status_code == 503

    def broken(*a, **k):
        raise ConnectionError("테스트")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(memory_router, "connect", broken)
    with TestClient(app) as client:
        assert client.delete("/api/memory/items/c1", headers=headers).status_code == 503


def test_document_facts_saves_conditions_and_contact(monkeypatch, db):
    """확인한 B/L 조건은 화물 표에, 거래처는 출처 B/L 메모로 (결정 7)."""
    headers = _login(monkeypatch)
    calls = []
    monkeypatch.setattr(memory_router.cargo, "apply_document_facts",
                        lambda conn, user_id, bl_no, bl_type, facts: calls.append(("cargo", bl_no, bl_type, facts)) or "k1")
    monkeypatch.setattr(memory_router.cargo, "get_row", lambda conn, user_id, key: {"cargo_key": key})
    monkeypatch.setattr(memory_router.memory, "add_contact",
                        lambda conn, user_id, contact, key, today: calls.append(("contact", contact, key)) or "saved")
    with TestClient(app) as client:
        body = client.post("/api/memory/document-facts", json=FACTS, headers=headers).json()
    assert body == {"conditions_saved": True, "contact": "saved"}
    assert calls[0] == ("cargo", BL, "HOUSE", {"original_bl": "required", "to_order_bank": True,
                                               "freight_term": "collect", "incoterm": "FOB"})
    assert calls[1] == ("contact", {"company": "가나다물류", "role": "포워더", "phone": "051-000-0000", "source": "B/L"}, "k1")


def test_document_facts_without_source_skips_contact(monkeypatch, db):
    headers = _login(monkeypatch)
    monkeypatch.setattr(memory_router.cargo, "apply_document_facts", lambda *a: "k1")
    monkeypatch.setattr(memory_router.memory, "add_contact", lambda *a: pytest.fail("출처를 모르면 저장하지 않는다"))
    with TestClient(app) as client:
        body = client.post("/api/memory/document-facts", json={**FACTS, "source": None}, headers=headers).json()
    assert body == {"conditions_saved": True, "contact": "skipped"}


@pytest.mark.parametrize("over", [{"original_bl": "maybe"}, {"freight_term": "cod"}, {"incoterm": "EXW"},
                                  {"bl_no": "short"}, {"contact": {"company": "가나다물류", "role": "은행"}}])
def test_document_facts_rejects_values_outside_lists(monkeypatch, db, over):
    """허용 값 밖은 계약에서 422. 마이그레이션 015 CHECK와 같은 목록이다."""
    headers = _login(monkeypatch)
    with TestClient(app) as client:
        assert client.post("/api/memory/document-facts", json={**FACTS, **over}, headers=headers).status_code == 422
