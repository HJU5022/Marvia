"""감시 목록 테스트 (GET /api/watch, services/watch/watch.watch_list, services/watch/cargo._keep_position).

DB 없이 돈다. 가짜 연결이 SQL 모양을 보고 정해 둔 줄을 돌려준다. B/L·배·좌표는 모두 모의값이다.
"""
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.account import operators as ops
from backend.app.services.watch import watch as svc
from backend.tests.integration.test_admin import _login

NOW = datetime(2026, 10, 6, 6, tzinfo=timezone.utc)
MMSI = 440999901  # 모의 배


def _cargo_row(**over):
    """watch_list가 읽는 user_cargo 줄 (SELECT 순서 그대로)."""
    row = {"cargo_key": "k1", "bl_masked": "MOC*******1006", "label": "고추", "goods_name": "TEST GOODS",
           "vessel_name": "TEST STAR", "vessel_flag": "KR", "vessel_mmsi": MMSI, "status": "active",
           "last_verdict": "watch", "last_stage": "입항보고 수리", "last_eta": date(2026, 10, 9),
           "last_days_margin": 3, "last_checked_at": NOW}
    row.update(over)
    return tuple(row.values())


class FakeConn:
    """user_cargo SELECT에는 cargo, watch_positions SELECT에는 그 배의 점(최신 먼저)을 돌려준다."""

    def __init__(self, cargo=(), positions=None):
        self.cargo, self.positions, self.calls = list(cargo), positions or {}, []

    def execute(self, sql, params=()):
        self.calls.append((sql, list(params)))
        rows = self.cargo if "FROM user_cargo" in sql else self.positions.get(params[0], [])[:params[1]] \
            if "FROM watch_positions" in sql else []

        class Cur:
            def fetchall(self):
                return rows
        return Cur()


def _points(n):
    """최신이 먼저 오는 위치 n개 (DB의 ORDER BY ts DESC 모양). 6시간 간격"""
    return [(NOW - timedelta(hours=6 * i), 34.0 + i * 0.1, 128.0 - i * 0.1, 12.5, 60.0) for i in range(n)]


def test_list_has_screen_shape_and_last_point_is_current_position():
    conn = FakeConn([_cargo_row()], {MMSI: _points(3)})
    out = svc.watch_list(conn, "u1")
    item = out["items"][0]
    assert out["sample"] is False and out["updated_at"] == NOW.isoformat()
    assert (item["ship_name"], item["ship_flag"], item["goods_name"], item["verdict"]) == ("TEST STAR", "KR", "TEST GOODS", "watch")
    assert item["eta"] == "2026-10-09" and item["days_margin"] == 3 and item["stage"] == "입항보고 수리"
    assert [p["at"] for p in item["track"]] == sorted(p["at"] for p in item["track"])  # 오래된 순
    assert (item["lat"], item["lng"], item["position_at"]) == (34.0, 128.0, NOW.isoformat())  # 마지막 점 = 현재
    assert "user_id = %s AND watch" in conn.calls[0][0] and conn.calls[0][1] == ["u1"]


def test_track_is_capped_to_track_points():
    conn = FakeConn([_cargo_row()], {MMSI: _points(svc.TRACK_POINTS + 5)})
    assert len(svc.watch_list(conn, "u1")["items"][0]["track"]) == svc.TRACK_POINTS


def test_no_position_gives_null_location_not_error():
    """위치 수집 전이거나 배 번호를 모르는 화물은 위치 칸이 null. 화면은 지도에 안 그리고 목록에는 보인다"""
    conn = FakeConn([_cargo_row(), _cargo_row(cargo_key="k2", vessel_mmsi=None)], {})
    items = svc.watch_list(conn, "u1")["items"]
    assert all(i["lat"] is None and i["track"] == [] for i in items)
    assert sum("watch_positions" in sql for sql, _ in conn.calls) == 1  # 배 번호 없는 줄은 위치를 묻지 않는다


def test_empty_list():
    assert svc.watch_list(FakeConn(), "u1") == {"items": [], "updated_at": None, "sample": False}


def test_route_returns_list_for_logged_in_user(monkeypatch):
    conn = FakeConn([_cargo_row()], {MMSI: _points(2)})
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")

    class Ctx:
        def __enter__(self):
            return conn

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(ops, "open_conn", lambda: Ctx())
    headers = _login(monkeypatch, "kim@example.com")
    with TestClient(app) as c:
        r = c.get("/api/watch", headers=headers)
    assert r.status_code == 200 and r.json()["items"][0]["bl_masked"] == "MOC*******1006"
    assert conn.calls[0][1] == ["user-123"]  # 출입증의 사용자 것만 읽는다
