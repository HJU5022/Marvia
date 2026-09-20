"""공유 링크 API (SDD 2절 GET/PATCH, 7절 핀 소유권). DB 없이 가짜 store 로 돈다 (TEST_GUIDE)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers import session as session_router
from backend.app.services import store
from backend.app.services.auth import current_user

ME = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


def make_session(owner: str | None = None) -> dict:
    return {
        "preset": "ship_maintenance",
        "purpose": "레이더 정기점검",
        "destination_name": "진해 기지",
        "destination_lng": 128.652,
        "destination_lat": 35.149,
        "meet_at": None,
        "schedule_confirmed": True,
        "constraints": [],
        "participants": [
            {
                "name": "김현장", "origin_text": "창원시청", "lng": 128.68, "lat": 35.22,
                "transport": "car", "pickup": None, "pickup_at": None, "unfamiliar": False,
                "role": "site", "confirmed": True, "owner_user_id": owner,
                "origin_set_by": "organizer", "self_edited_at": None,
            }
        ],
    }


RESULT_ROW = {
    "candidates": [{
        "name": "진해 기지 위병소", "kind": "gate", "address": "테스트", "lng": 128.67, "lat": 35.144,
        "rank": 1, "access_ok": True, "switched_from": None, "reason": "access.md", "rejected_reason": None,
    }],
    "per_participant": [{
        "name": "김현장", "candidate_rank": 1, "transport": "car", "duration_min": 57,
        "raw_duration_min": 27, "buffer_min": 30, "departure_time": "06:42", "arrive_by": "07:40",
        "transfer_count": None, "first_train": None, "last_train": None,
        "polyline": [[128.68, 35.22], [128.67, 35.14]], "via_rendezvous": False, "via_pickup": False,
    }],
    "routed_to": "small", "model_small": "test", "model_large": None, "prompt_version": "test",
    "rendezvous_departure": None, "provisional": False, "trace_id": "t1", "confidence": 0.8,
}


@pytest.fixture
def client(monkeypatch):
    """세션 라우터만 띄우고, store 와 로그인을 가짜로 바꾼다."""
    state = {"session": make_session(), "saved": None, "locked": False}

    async def get_session(_id):
        return state["session"]

    async def get_latest_result(_id):
        return RESULT_ROW

    async def update_session(_id, **kwargs):
        state["saved"] = kwargs.get("participants")

    monkeypatch.setattr(store, "get_session", get_session)
    monkeypatch.setattr(store, "get_latest_result", get_latest_result)
    monkeypatch.setattr(store, "update_session", update_session)
    monkeypatch.setattr(store, "is_locked", lambda *_: state["locked"])

    app = FastAPI()
    app.include_router(session_router.router)
    app.dependency_overrides[current_user] = lambda: ME
    return TestClient(app), state


def test_공유_링크는_에이전트_응답과_같은_모양이다(client):
    api, _ = client
    body = api.get("/api/session/s1").json()
    assert body["stage"] == "done"
    assert body["slots"]["participants"][0]["name"] == "김현장"
    assert body["result"]["candidates"][0]["name"] == "진해 기지 위병소"
    kinds = {p["kind"] for p in body["geocoded"]}
    assert kinds == {"participant", "destination"}


def test_주인이_없는_핀은_claim_할_수_있다(client):
    api, state = client
    res = api.patch("/api/session/s1/participants", json={"name": "김현장", "lng": 128.68, "lat": 35.22, "claim": True})
    assert res.status_code == 200
    assert state["saved"][0]["owner_user_id"] == ME


def test_이미_주인이_있으면_claim_은_409(client):
    api, state = client
    state["session"] = make_session(owner=OTHER)
    res = api.patch("/api/session/s1/participants", json={"name": "김현장", "lng": 128.68, "lat": 35.22, "claim": True})
    assert res.status_code == 409


def test_남의_핀도_고칠_수_있고_누가_고쳤는지_남는다(client):
    """09-18 결정: 소유권은 표시용이고 수정은 막지 않는다 (SDD 7절)."""
    api, state = client
    state["session"] = make_session(owner=OTHER)
    res = api.patch("/api/session/s1/participants", json={"name": "김현장", "lng": 128.7, "lat": 35.25, "claim": False})
    assert res.status_code == 200

    saved = state["saved"][0]
    assert (saved["lng"], saved["lat"]) == (128.7, 35.25)
    assert saved["owner_user_id"] == OTHER  # 주인은 그대로
    assert saved["last_edited_by"] == ME  # 고친 사람은 나
    assert saved["origin_set_by"] == "other"  # 본인이 아닌 사람이 고쳤다

    edit = next(e for e in res.json()["edits"] if e["name"] == "김현장")
    assert edit["edited_by"] == ME
    assert edit["by_owner"] is False


def test_내_핀이면_위치를_고치고_기록을_남긴다(client):
    api, state = client
    state["session"] = make_session(owner=ME)
    res = api.patch("/api/session/s1/participants", json={"name": "김현장", "lng": 128.7, "lat": 35.25, "claim": False})
    assert res.status_code == 200
    saved = state["saved"][0]
    assert (saved["lng"], saved["lat"]) == (128.7, 35.25)
    assert saved["origin_set_by"] == "self"
    assert saved["last_edited_by"] == ME
    assert datetime.fromisoformat(saved["self_edited_at"]).tzinfo is not None
    assert res.json()["result"]["candidates"][0]["rank"] == 1

    edit = next(e for e in res.json()["edits"] if e["name"] == "김현장")
    assert edit["by_owner"] is True  # 주인이 직접 고쳤다


def test_잠긴_세션은_409(client):
    api, state = client
    state["locked"] = True
    res = api.patch("/api/session/s1/participants", json={"name": "김현장", "lng": 128.7, "lat": 35.25, "claim": True})
    assert res.status_code == 409


def test_없는_참석자면_404(client):
    api, _ = client
    res = api.patch("/api/session/s1/participants", json={"name": "없는사람", "lng": 128.7, "lat": 35.25, "claim": True})
    assert res.status_code == 404


# --- 내 계획 목록 (SDD 2절 GET /api/sessions) ---


@pytest.fixture
def list_client(monkeypatch):
    """목록 라우터만 띄우고 store 를 가짜로 바꾼다."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    captured: dict = {}

    async def list_sessions(user_id, limit=20):
        captured["user_id"] = user_id
        captured["limit"] = limit
        return [
            {
                "id": "aaaaaaaa-0000-0000-0000-000000000001",
                "preset": "ship_maintenance",
                "status": "computed",
                "purpose": "레이더 정기점검",
                "destination_name": "진해 기지",
                "meet_at": None,
                "participant_count": 3,
                "created_at": now,
                "expires_at": now + timedelta(days=7),
            }
        ]

    monkeypatch.setattr(store, "list_sessions", list_sessions)
    monkeypatch.setattr(store, "is_locked", lambda *_: False)

    app = FastAPI()
    app.include_router(session_router.list_router)
    app.dependency_overrides[current_user] = lambda: ME
    return TestClient(app), captured


def test_내_계획만_최근_순으로_준다(list_client):
    api, captured = list_client
    rows = api.get("/api/sessions").json()
    assert captured["user_id"] == ME  # 토큰의 사용자로만 조회한다
    assert len(rows) == 1
    assert rows[0]["destination"] == "진해 기지"
    assert rows[0]["participant_count"] == 3
    assert rows[0]["locked"] is False


def test_목록에는_참석자_이름이_없다(list_client):
    api, _ = list_client
    row = api.get("/api/sessions").json()[0]
    assert "participants" not in row  # 목록은 복호화하지 않는다 (테이블정의서 7절)


def test_limit_은_1에서_100_사이로_자른다(list_client):
    api, captured = list_client
    api.get("/api/sessions?limit=500")
    assert captured["limit"] == 100
    api.get("/api/sessions?limit=0")
    assert captured["limit"] == 1
