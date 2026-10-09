"""B/L 없이 배만 지켜보기 테스트 (services/watch/vessel_watch.py, routers/watch.py /api/watch/vessels).

DB 없이 돈다. vessel_watch·watch_positions 두 표를 흉내 내는 가짜 연결을 쓴다. 배 번호·이름·좌표는 모의값이다.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.account import operators as ops
from backend.app.services.watch import vessel_watch as vsvc
from backend.app.services.watch.watch import MAX_WATCH
from backend.tests.integration.test_admin import _login

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
        self.inserted: list[tuple] = []

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
        if q.startswith("INSERT INTO watch_positions"):
            mmsi, ts, fetched, lat, lng, sog, cog, navi = params
            pts = self.positions.setdefault(mmsi, [])
            if not any(p[0] == ts for p in pts):
                pts.append((ts, lat, lng, sog, cog))
                pts.sort(key=lambda p: p[0], reverse=True)  # 최신 먼저 (_track 조회 순서)
            self.inserted.append(params)
            return _Cur()
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


@pytest.fixture(autouse=True)
def _no_external(monkeypatch):
    """테스트는 실제 ShipFinder·MCP를 부르지 않는다. 위치 새로 받기·자세히 보기 캐시는 기본으로 "없음/실패"로 막고,
    필요한 테스트가 다시 바꿔 끼운다. 하루 한도 표시와 자세히 보기 캐시도 테스트마다 비운다."""
    from backend.app.clients import shipfinder
    from backend.app.services.watch import vessel_detail
    shipfinder.reset_quota_block()
    vessel_detail._cache.clear()
    monkeypatch.setattr(vessel_detail, "get_live_position", lambda mmsi: {"error": {"code": "timeout", "message": "x"}})
    yield
    shipfinder.reset_quota_block()
    vessel_detail._cache.clear()


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


# ── 호출부호로 올리기 (입항 예정 목록, MMSI 없음) ──

class _FakeClient:
    """ShipFinderClient 자리. hits는 (mmsi, call_sign[, ship_name, last_time]) 목록, error를 주면 검색이 그 오류로 실패한다.
    cached_at을 주면 한도·시간 초과로 지난 캐시 값을 대신 준 것처럼 last_cached_at이 채워진다."""

    def __init__(self, hits=(), error=None, cached_at=None):
        self.hits, self.error, self.closed, self.queries = hits, error, False, []
        self.last_cached_at = cached_at

    def search(self, keywords, max=10):
        from types import SimpleNamespace
        self.queries.append(keywords)
        if self.error:
            raise self.error
        out = []
        for h in self.hits:
            m, c, *rest = h
            name = rest[0] if rest else "X"
            last = rest[1] if len(rest) > 1 else None
            out.append(SimpleNamespace(mmsi=m, call_sign=c, ship_name=name, last_time=last))
        return SimpleNamespace(hits=out)

    def close(self):
        self.closed = True


def _use(monkeypatch, client):
    monkeypatch.setattr(vsvc, "make_client", lambda: client)
    return client


SIGN_BODY = {"call_sign": "tst01", "name": "TEST STAR", "flag": "KR"}
D = lambda days: NOW - timedelta(days=days)  # noqa: E731


def test_call_sign_add_resolves_mmsi(db, me, monkeypatch):
    # 예전에 같은 호출부호를 쓴 다른 호출부호 배·같은 배의 중복 줄은 걸러진다
    client = _use(monkeypatch, _FakeClient([(440999901, "TST01"), (440999901, " tst01 "), (111, "OTHER1")]))
    r = _call("post", "/api/watch/vessels", SIGN_BODY, me)
    assert r.status_code == 200 and r.json() == {"mmsi": 440999901, "watch": True}
    assert (USER, 440999901) in db.rows and client.queries == ["TST01"] and client.closed


def test_call_sign_without_exact_match_is_422(db, me, monkeypatch):
    _use(monkeypatch, _FakeClient([(111, "TST011"), (222, None)]))  # 비슷하지만 같지 않은 호출부호
    r = _call("post", "/api/watch/vessels", SIGN_BODY, me)
    assert r.status_code == 422 and "선박 번호를 확인하지 못해" in r.json()["detail"] and db.rows == {}
    _use(monkeypatch, _FakeClient([]))
    assert _call("post", "/api/watch/vessels", SIGN_BODY, me).status_code == 422


def test_normalization_both_sides(monkeypatch):
    # 요청 쪽 하이픈·공백과 결과 쪽 소문자·공백이 달라도 같은 호출부호로 본다
    _use(monkeypatch, _FakeClient([(7, " b-oak 2 ")]))
    assert vsvc.resolve_mmsi("BOAK2") == 7
    _use(monkeypatch, _FakeClient([(8, "BOAK2")]))
    assert vsvc.resolve_mmsi(" boa-k2 ") == 8


def test_many_match_prefers_same_name_then_latest(monkeypatch):
    hits = [(1, "BOAK2", "OLD NAME", D(1)), (2, "BOAK2", "ZHONG WAI YUN NINGBO", D(300)),
            (3, "BOAK2", "ANOTHER", D(5))]
    _use(monkeypatch, _FakeClient(hits))
    assert vsvc.resolve_mmsi("BOAK2", "zhong wai yun-ningbo") == 2  # 이름이 같으면 신호가 오래돼도 그 배
    assert vsvc.resolve_mmsi("BOAK2", "NO SUCH NAME") == 1  # 이름이 안 맞으면 가장 최근 신호
    assert vsvc.resolve_mmsi("BOAK2") == 1  # 이름을 안 주면 가장 최근 신호
    # 이름이 같은 배가 둘이면 그중 최근
    _use(monkeypatch, _FakeClient([(4, "X1", "SAME", D(9)), (5, "X1", "SAME", D(2)), (6, "X1", "OTHER", D(1))]))
    assert vsvc.resolve_mmsi("X1", "same") == 5
    # last_time이 없는 줄은 맨 뒤
    _use(monkeypatch, _FakeClient([(10, "X2", "A", None), (11, "X2", "B", D(400))]))
    assert vsvc.resolve_mmsi("X2") == 11


def test_many_match_via_endpoint_uses_body_name(db, me, monkeypatch):
    _use(monkeypatch, _FakeClient([(1, "TST01", "NEWER", D(1)), (2, "TST01", "TEST STAR", D(200))]))
    r = _call("post", "/api/watch/vessels", SIGN_BODY, me)
    assert r.status_code == 200 and r.json()["mmsi"] == 2 and (USER, 2) in db.rows


def test_detail_and_watch_pick_same_ship(monkeypatch):
    # 자세히 보기(후보 순서가 유사도 순)와 지켜보기가 같은 규칙으로 같은 배를 고른다
    from backend.app.services.watch import vessel_detail as vd
    cands = [{"mmsi": 1, "name": "NEWER", "call_sign": "T", "last_time": D(1).isoformat()},
             {"mmsi": 2, "name": "TEST STAR", "call_sign": "T", "last_time": D(200).isoformat()}]
    monkeypatch.setattr(vd, "get_port_schedule", lambda **kw: {})
    monkeypatch.setattr(vd, "get_vessel_candidates", lambda **kw: {"candidates": cands})
    monkeypatch.setattr(vd, "get_live_position", lambda mmsi: {"error": {"code": "timeout", "message": "x"}})
    vessel = vd.detail("T", "TEST STAR")["vessel"]
    _use(monkeypatch, _FakeClient([(1, "T", "NEWER", D(1)), (2, "T", "TEST STAR", D(200))]))
    assert vessel["mmsi"] == vsvc.resolve_mmsi("T", "TEST STAR") == 2


def test_call_sign_lookup_failure_is_503_without_leaking(db, me, monkeypatch):
    from backend.app.clients.shipfinder import ShipFinderError
    _use(monkeypatch, _FakeClient(error=ShipFinderError("timeout", "secret-url 응답 시간 초과")))
    r = _call("post", "/api/watch/vessels", SIGN_BODY, me)
    assert r.status_code == 503 and "secret-url" not in r.text and db.rows == {}
    assert "문제가 생겼어요" in r.json()["detail"]  # 기존 안내 그대로
    _use(monkeypatch, _FakeClient(error=RuntimeError("boom secret-host")))
    r = _call("post", "/api/watch/vessels", SIGN_BODY, me)
    assert r.status_code == 503 and "secret-host" not in r.text
    monkeypatch.setattr(vsvc, "make_client", lambda: (_ for _ in ()).throw(ShipFinderError("bad_key", "키 없음")))  # 키 없음
    assert _call("post", "/api/watch/vessels", SIGN_BODY, me).status_code == 503


QUOTA_MSG = "오늘 선박 조회 한도를 다 썼어요. 내일 다시 시도해 주세요."


def test_quota_exhausted_is_503_with_own_message(db, me, monkeypatch):
    from backend.app.clients.shipfinder import ShipFinderError
    _use(monkeypatch, _FakeClient(error=ShipFinderError("quota_exhausted", "secret-url 한도")))
    r = _call("post", "/api/watch/vessels", SIGN_BODY, me)
    assert r.status_code == 503 and r.json()["detail"] == QUOTA_MSG and "secret-url" not in r.text and db.rows == {}


def test_cache_fallback_is_not_a_fresh_result(db, me, monkeypatch):
    from backend.app.clients import shipfinder
    # 한도 소진으로 지난 캐시를 대신 받았으면, 캐시에 배가 있어도 새 결과로 쓰지 않고 한도 안내를 낸다
    shipfinder._mark_quota_out()
    _use(monkeypatch, _FakeClient([(440999901, "TST01", "TEST STAR", D(1))], cached_at=D(1)))
    r = _call("post", "/api/watch/vessels", SIGN_BODY, me)
    assert r.status_code == 503 and r.json()["detail"] == QUOTA_MSG and db.rows == {}  # unknown_vessel(422)이 아니다
    # 시간 초과 등 한도 아닌 이유의 캐시 대체는 기존 조회 실패 안내
    shipfinder.reset_quota_block()
    _use(monkeypatch, _FakeClient([(440999901, "TST01")], cached_at=D(1)))
    r = _call("post", "/api/watch/vessels", SIGN_BODY, me)
    assert r.status_code == 503 and "문제가 생겼어요" in r.json()["detail"]


def test_mmsi_wins_and_neither_is_422(db, me, monkeypatch):
    client = _use(monkeypatch, _FakeClient([(5, "TST01")]))
    r = _call("post", "/api/watch/vessels", {**VESSEL, "call_sign": "TST01"}, me)
    assert r.json()["mmsi"] == 440999901 and client.queries == []  # mmsi가 있으면 검색하지 않는다
    for body in ({"name": "TEST STAR"}, {"name": "TEST STAR", "call_sign": "  "}):
        assert _call("post", "/api/watch/vessels", body, me).status_code == 422


# ── 위치 바로 보이기 (66번) ──

def _detail_cache(call_sign, name, mmsi, last_time, **extra):
    from backend.app.services.watch import vessel_detail as vd
    pos = {"mmsi": mmsi, "lat": 33.5, "lng": 128.5, "sog": 11.0, "cog": 80.0, "navistat": 0,
           "last_time": last_time.isoformat(), "fetched_at": NOW.isoformat(), "freshness": "fresh", **extra}
    vd._cache_put(vd._key(call_sign, name), {"vessel": {"mmsi": mmsi}, "position": pos})


def test_add_stores_position_from_detail_cache(db, me, monkeypatch):
    _detail_cache("TST01", "TEST STAR", 440999901, NOW - timedelta(hours=1))
    r = _call("post", "/api/watch/vessels", {**VESSEL, "call_sign": "TST01"}, me)
    assert r.status_code == 200
    assert len(db.inserted) == 1 and db.inserted[0][0] == 440999901 and db.inserted[0][3:5] == (33.5, 128.5)
    # 목록을 열면 새 호출 없이 바로 보인다 (live_position 호출이 있으면 _no_external이 실패시킨다)
    item = _call("get", "/api/watch/vessels", None, me).json()["items"][0]
    assert (item["lat"], item["lng"]) == (33.5, 128.5)


def test_add_skips_seed_when_cache_missing_other_ship_or_cached_value(db, me):
    _call("post", "/api/watch/vessels", {**VESSEL, "call_sign": "TST01"}, me)  # 캐시 없음
    _detail_cache("TST01", "TEST STAR", 111, NOW)  # 다른 MMSI의 캐시는 이 배 위치가 아니다
    _call("post", "/api/watch/vessels", {**VESSEL, "call_sign": "TST01"}, me)
    _detail_cache("TST01", "TEST STAR", 440999901, NOW, cached_at=NOW.isoformat())  # 한도 대체값
    _call("post", "/api/watch/vessels", {**VESSEL, "call_sign": "TST01"}, me)
    assert db.inserted == []


def test_seed_failure_does_not_fail_add(db, me, monkeypatch):
    _detail_cache("TST01", "TEST STAR", 440999901, NOW)
    monkeypatch.setattr(vsvc, "_store_position", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db secret")))
    r = _call("post", "/api/watch/vessels", {**VESSEL, "call_sign": "TST01"}, me)
    assert r.status_code == 200 and "secret" not in r.text


# ── 목록을 열 때 오래된 위치 새로 받기 (66번) ──

def _live(monkeypatch, calls, hours_old=0, fail=()):
    from backend.app.services.watch import vessel_detail as vd

    def fake(mmsi):
        calls.append(mmsi)
        if mmsi in fail:
            return {"error": {"code": "timeout", "message": "x", "retryable": True}}
        t = datetime.now(timezone.utc) - timedelta(hours=hours_old)
        return {"mmsi": mmsi, "lat": 30.0 + mmsi % 7, "lng": 129.0, "sog": 9.0, "cog": 1.0, "navistat": 0,
                "last_time": t.isoformat(), "fetched_at": datetime.now(timezone.utc).isoformat()}
    monkeypatch.setattr(vd, "get_live_position", fake)


def _recent(hours):
    t = datetime.now(timezone.utc) - timedelta(hours=hours)
    return [(t, 34.0, 128.0, 12.0, 60.0)]


def test_list_refresh_fills_missing_and_stale_only(db, me, monkeypatch):
    calls = []
    _live(monkeypatch, calls)
    db.positions = {2: _recent(1), 3: _recent(30)}  # 2는 신선, 3은 오래됨(rules.md position_stale_hours 6시간), 1은 없음
    for m in (1, 2, 3):
        vsvc.add_vessel(db, USER, m, f"S{m}")
    items = {i["mmsi"]: i for i in _call("get", "/api/watch/vessels", None, me).json()["items"]}
    assert sorted(calls) == [1, 3]
    assert items[1]["lat"] is not None and items[3]["lat"] == 30.0 + 3 % 7 and items[2]["lat"] == 34.0
    assert len(items[3]["track"]) == 2  # 옛 점 + 새 점


def test_list_refresh_uses_10min_cache(db, me, monkeypatch):
    calls = []
    _live(monkeypatch, calls, hours_old=20)  # 받아도 신호 자체가 오래된 배: 목록을 다시 열어도 새로 부르지 않는다
    vsvc.add_vessel(db, USER, 1, "S1")
    _call("get", "/api/watch/vessels", None, me)
    _call("get", "/api/watch/vessels", None, me)
    assert calls == [1]


def test_list_refresh_is_capped_and_failure_tolerant(db, me, monkeypatch):
    calls = []
    _live(monkeypatch, calls, fail={2})
    for m in range(1, MAX_WATCH + 1):
        vsvc.add_vessel(db, USER, m, f"S{m}")
    db.positions = {2: _recent(40)}
    r = _call("get", "/api/watch/vessels", None, me)
    assert r.status_code == 200 and len(calls) <= MAX_WATCH  # 한 요청 최대 5척
    items = {i["mmsi"]: i for i in r.json()["items"]}
    assert items[2]["lat"] == 34.0 and len(items[2]["track"]) == 1  # 실패한 배는 옛 값 그대로
    assert items[1]["lat"] is not None


def test_list_refresh_survives_exceptions_and_skips_when_quota_out(db, me, monkeypatch):
    from backend.app.clients import shipfinder
    from backend.app.services.watch import vessel_detail as vd
    vsvc.add_vessel(db, USER, 1, "S1")
    monkeypatch.setattr(vd, "get_live_position", lambda m: (_ for _ in ()).throw(RuntimeError("secret-host")))
    r = _call("get", "/api/watch/vessels", None, me)
    assert r.status_code == 200 and r.json()["items"][0]["lat"] is None and "secret-host" not in r.text
    calls = []
    _live(monkeypatch, calls)
    shipfinder._mark_quota_out()
    assert _call("get", "/api/watch/vessels", None, me).status_code == 200 and calls == []


def test_refresh_reuses_detail_cache(db, me, monkeypatch):
    calls = []
    _live(monkeypatch, calls)
    vsvc.add_vessel(db, USER, 440999901, "TEST STAR")  # call_sign 없이 올렸지만 이름 열쇠로 캐시를 찾는다
    _detail_cache(None, "TEST STAR", 440999901, NOW - timedelta(hours=1))
    from backend.app.services.watch import vessel_detail as vd
    pos = vd.live_position(440999901, None, "TEST STAR")
    assert pos["lat"] == 33.5 and calls == []


# ── span: 키·URL·B/L이 없다 ──

def test_spans_carry_metadata_only(monkeypatch):
    from backend.app.observability import langfuse as lf
    from backend.app.clients import shipfinder as sf
    import httpx
    ended = []
    monkeypatch.setattr(lf, "start_tool", lambda name, inp: ended.append(("start", name, inp)) or object())
    monkeypatch.setattr(lf, "end_tool", lambda tool, out, meta, error=None: ended.append(("end", out, dict(meta), error)))
    # resolve span
    _use(monkeypatch, _FakeClient([(1, "TST01", "A", D(1)), (2, "TST01", "B", D(2))]))
    vsvc.resolve_mmsi("TST01", "A")
    # 실제 클라이언트의 _get span (가짜 전송, 키는 테스트 값)
    def handler(req):
        return httpx.Response(200, json={"status": 0, "data": [{"mmsi": 1, "call_sign": "TST01", "ship_name": "A", "last_time": 1790000000}]})
    client = sf.ShipFinderClient(key="TESTKEY123", transport=httpx.MockTransport(handler))
    client.cache = sf.ResponseCache()
    client.search("TST01")
    client.close()
    text = repr(ended)
    assert "TESTKEY123" not in text and "key=" not in text and "http" not in text
    meta = [e for e in ended if e[0] == "end"]
    assert any(m[2].get("endpoint") == "VesselSearch" and m[2].get("result_count") == 2
               and m[2].get("served_from_cache") is False and "replay_mode" in m[2] for m in meta)
    assert any(m[2].get("endpoint") == "VesselSearch" and m[2].get("result_count") == 1 for m in meta)
    # 오류 코드는 error 칸에
    from backend.app.clients.shipfinder import ShipFinderError
    ended.clear()
    _use(monkeypatch, _FakeClient(error=ShipFinderError("quota_exhausted", "x")))
    with pytest.raises(vsvc.VesselWatchError):
        vsvc.resolve_mmsi("TST01")
    assert [e for e in ended if e[0] == "end"][0][3] == "quota_exhausted"


# ── 워커·마이그레이션 ──

def test_worker_collects_positions_for_vessel_watch_too():
    from worker.collector import SELECT_WATCHED
    sql = " ".join(SELECT_WATCHED.split())
    assert "UNION SELECT mmsi FROM vessel_watch" in sql  # 같은 배는 UNION이 한 번만 센다


def test_migration_023_is_last_and_creates_table():
    from pathlib import Path
    names = sorted(p.name for p in (Path(__file__).parents[2] / "app/db/migrations").glob("*.sql"))
    assert names[-1] == "023_vessel_watch.sql"
    text = (Path(__file__).parents[2] / "app/db/migrations" / names[-1]).read_text()
    assert "CREATE TABLE IF NOT EXISTS vessel_watch" in text and "ENABLE ROW LEVEL SECURITY" in text
