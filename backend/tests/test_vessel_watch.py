"""B/L 없이 배만 지켜보기 테스트 (services/vessel_watch.py, routers/watch.py /api/watch/vessels, 10-08 정운 실사용 57번).

DB 없이 돈다. vessel_watch·watch_positions 두 표를 흉내 내는 가짜 연결을 쓴다. 배 번호·이름·좌표는 모의값이다.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services import operators as ops
from backend.app.services import vessel_watch as vsvc
from backend.app.services.watch import MAX_WATCH
from backend.tests.test_admin import _login

NOW = datetime(2026, 10, 8, 6, tzinfo=timezone.utc)
USER = "user-123"  # _login이 쓰는 사용자 ID


class _Cur:
    def __init__(self, rows=None, rowcount=0):
        self._rows, self.rowcount = rows or [], rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class FakeConn:
    """vessel_watch 한 표와 watch_positions(배별 최신 먼저 점)를 메모리에 둔다. 문장 앞부분으로 SQL을 가른다."""

    def __init__(self, positions=None):
        self.rows: dict[tuple, dict] = {}
        self.positions = positions or {}

    def execute(self, sql, params=()):
        q = " ".join(sql.split())
        if q.startswith("SELECT 1 FROM vessel_watch"):
            return _Cur([(1,)] if (params[0], params[1]) in self.rows else [])
        if q.startswith("SELECT count(*) FROM vessel_watch"):
            return _Cur([(sum(1 for u, _ in self.rows if u == params[0]),)])
        if q.startswith("INSERT INTO vessel_watch"):
            user, mmsi, name, flag, dest, eta = params
            self.rows[(user, mmsi)] = {"name": name, "flag": flag, "dest": dest, "eta": eta, "created_at": NOW}
            return _Cur()
        if q.startswith("DELETE FROM vessel_watch"):
            return _Cur(rowcount=1 if self.rows.pop((params[0], params[1]), None) else 0)
        if q.startswith("SELECT mmsi, name, flag, dest, eta, created_at FROM vessel_watch"):
            return _Cur([(m, r["name"], r["flag"], r["dest"], r["eta"], r["created_at"])
                         for (u, m), r in self.rows.items() if u == params[0]])
        if "FROM watch_positions" in q:
            return _Cur(self.positions.get(params[0], [])[:params[1]])
        raise AssertionError(f"예상 못 한 SQL: {q}")


class _Ctx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


@pytest.fixture
def db(monkeypatch):
    conn = FakeConn()
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(ops, "open_conn", lambda: _Ctx(conn))
    return conn


@pytest.fixture
def me(monkeypatch):
    return _login(monkeypatch, "kim@example.com")


def _call(method, path, body=None, headers=None):
    with TestClient(app) as c:
        return getattr(c, method)(path, headers=headers, **({"json": body} if body is not None else {}))


def _points(n):
    return [(NOW - timedelta(hours=6 * i), 34.0 + i * 0.1, 128.0 - i * 0.1, 12.5, 60.0) for i in range(n)]


VESSEL = {"mmsi": 440999901, "name": "TEST STAR", "flag": "KR", "dest": "KRPUS", "eta": "10-12 09:00"}


# ── 서비스 ──

def test_add_is_idempotent_and_updates_shown_values():
    conn = FakeConn()
    assert vsvc.add_vessel(conn, USER, 440999901, " TEST STAR ", "KR", "KRPUS", "10-12") == {"mmsi": 440999901, "watch": True}
    vsvc.add_vessel(conn, USER, 440999901, "TEST STAR", "KR", "KRPUS", "10-13")
    assert len(conn.rows) == 1 and conn.rows[(USER, 440999901)]["eta"] == "10-13"
    assert conn.rows[(USER, 440999901)]["name"] == "TEST STAR"  # 공백은 뗀다


def test_limit_counts_only_new_vessels():
    conn = FakeConn()
    for i in range(MAX_WATCH):
        vsvc.add_vessel(conn, USER, 1000 + i, f"S{i}")
    with pytest.raises(vsvc.VesselWatchError) as e:
        vsvc.add_vessel(conn, USER, 9999, "NEW")
    assert e.value.kind == "limit"
    vsvc.add_vessel(conn, USER, 1000, "S0 RENAMED")  # 이미 있는 배는 한도에 걸리지 않는다
    vsvc.add_vessel(conn, "other-user", 9999, "NEW")  # 한도는 사용자별이다


def test_invalid_input_rejected_and_text_trimmed():
    conn = FakeConn()
    for mmsi, name in ((0, "X"), (-5, "X"), (1, "   ")):
        with pytest.raises(vsvc.VesselWatchError) as e:
            vsvc.add_vessel(conn, USER, mmsi, name)
        assert e.value.kind == "invalid"
    vsvc.add_vessel(conn, USER, 5, "N", dest="D" * 500)
    assert len(conn.rows[(USER, 5)]["dest"]) == vsvc.TEXT_MAX


def test_list_has_last_position_and_no_verdict_fields():
    conn = FakeConn({440999901: _points(3)})
    vsvc.add_vessel(conn, USER, 440999901, "TEST STAR", "KR")
    vsvc.add_vessel(conn, USER, 440999902, "NO POS")
    items = {i["mmsi"]: i for i in vsvc.list_vessels(conn, USER)["items"]}
    a, b = items[440999901], items[440999902]
    assert (a["lat"], a["lng"], a["position_at"]) == (34.0, 128.0, NOW.isoformat()) and len(a["track"]) == 3
    assert b["lat"] is None and b["track"] == []
    assert not {"verdict", "stage", "bl_masked", "days_margin"} & set(a)  # 판정·통관·B/L 칸이 없다


# ── 창구 ──

def test_endpoints_round_trip(db, me):
    r = _call("post", "/api/watch/vessels", VESSEL, me)
    assert r.status_code == 200 and r.json() == {"mmsi": 440999901, "watch": True}
    items = _call("get", "/api/watch/vessels", None, me).json()["items"]
    assert [i["name"] for i in items] == ["TEST STAR"] and items[0]["dest"] == "KRPUS"
    r = _call("delete", "/api/watch/vessels/440999901", None, me)
    assert r.status_code == 200 and r.json() == {"mmsi": 440999901, "watch": False}
    assert _call("get", "/api/watch/vessels", None, me).json() == {"items": []}
    assert _call("delete", "/api/watch/vessels/440999901", None, me).status_code == 200  # 없어도 오류가 아니다


def test_limit_is_409_and_blank_name_is_422(db, me):
    for i in range(MAX_WATCH):
        assert _call("post", "/api/watch/vessels", {**VESSEL, "mmsi": 2000 + i}, me).status_code == 200
    r = _call("post", "/api/watch/vessels", VESSEL, me)
    assert r.status_code == 409 and "5척" in r.json()["detail"]
    r = _call("post", "/api/watch/vessels", {**VESSEL, "name": " "}, me)
    assert r.status_code == 422


ENDPOINTS = [("get", "/api/watch/vessels", None), ("post", "/api/watch/vessels", VESSEL),
             ("delete", "/api/watch/vessels/1", None)]


@pytest.mark.parametrize("method,path,body", ENDPOINTS)
def test_login_and_db_conditions(db, monkeypatch, method, path, body):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert _call(method, path, body).status_code == 401  # 로그인 꺼짐
    headers = _login(monkeypatch, "kim@example.com")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _call(method, path, body, headers).status_code == 503  # DB 없음


def test_db_failure_is_503_without_leaking(monkeypatch, me):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")

    def down():
        raise RuntimeError("connection to secret-host failed")

    monkeypatch.setattr(ops, "open_conn", down)
    r = _call("get", "/api/watch/vessels", None, me)
    assert r.status_code == 503 and "secret-host" not in r.text


def test_other_users_vessels_are_not_listed(db, me):
    db.rows[("someone-else", 777)] = {"name": "THEIRS", "flag": None, "dest": None, "eta": None, "created_at": NOW}
    assert _call("get", "/api/watch/vessels", None, me).json() == {"items": []}


# ── 워커·마이그레이션 ──

def test_worker_collects_positions_for_vessel_watch_too():
    from worker.collector import SELECT_WATCHED
    sql = " ".join(SELECT_WATCHED.split())
    assert "UNION SELECT mmsi FROM vessel_watch" in sql  # 같은 배는 UNION이 한 번만 센다


def test_migration_023_is_last_and_creates_table():
    from pathlib import Path
    names = sorted(p.name for p in (Path(__file__).parents[1] / "app/db/migrations").glob("*.sql"))
    assert names[-1] == "023_vessel_watch.sql"
    text = (Path(__file__).parents[1] / "app/db/migrations" / names[-1]).read_text()
    assert "CREATE TABLE IF NOT EXISTS vessel_watch" in text and "ENABLE ROW LEVEL SECURITY" in text
