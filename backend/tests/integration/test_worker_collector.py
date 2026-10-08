"""D1 수집 워커 단위 테스트. DB 대신 가짜 연결, 외부 API 대신 가공 fixture로 키 없이 돈다."""
from datetime import date
from pathlib import Path

import httpx

from backend.app.clients.mof import MofClient
from worker.collector import collect_port

FIXTURES = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "mof"


class FakeConn:
    """execute()만 흉내 낸다. 같은 (SQL, 값)이 다시 오면 ON CONFLICT처럼 0줄로 센다."""

    def __init__(self):
        self.rows: list[tuple] = []
        self._seen: set = set()

    def execute(self, sql, params=()):
        key = (sql, params[:-1])  # 마지막 값 fetched_at은 매번 달라서 중복 판단에서 뺀다
        new = key not in self._seen
        self._seen.add(key)
        if new:
            self.rows.append((sql, params))
        return type("Cur", (), {"rowcount": 1 if new else 0})()


def _mof() -> MofClient:
    def handler(request: httpx.Request) -> httpx.Response:
        name = "arrival_report_busan.xml" if "VsslEtrynd5" in str(request.url) else "control_busan.xml"
        return httpx.Response(200, text=(FIXTURES / name).read_text(encoding="utf-8"))

    return MofClient(key="test-key", transport=httpx.MockTransport(handler))


def test_collect_port_saves_reports_and_events():
    conn = FakeConn()
    result = collect_port(conn, _mof(), today=date(2026, 9, 23))

    # 입항 신고 2건(출항만 있는 신고는 빠짐), 관제 이벤트 3건(입항·접안·출항)
    assert (result["reports_seen"], result["reports_new"]) == (2, 2)
    assert (result["events_seen"], result["events_new"]) == (3, 3)
    report_rows = [p for sql, p in conn.rows if "arrival_reports" in sql]
    assert report_rows[0][:4] == ("TEST11", "테스트컨테이너11", "풀컨테이너선", "변경")


def test_second_run_adds_nothing_when_unchanged():
    """같은 신고·이벤트를 다시 받으면 새 줄이 생기지 않는다. 바뀐 신고만 쌓인다."""
    conn, mof = FakeConn(), _mof()
    collect_port(conn, mof, today=date(2026, 9, 23))
    again = collect_port(conn, mof, today=date(2026, 9, 23))
    assert (again["reports_new"], again["events_new"]) == (0, 0)


def test_asks_report_window_ahead_and_control_window_back():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        name = "arrival_report_busan.xml" if "VsslEtrynd5" in str(request.url) else "control_busan.xml"
        return httpx.Response(200, text=(FIXTURES / name).read_text(encoding="utf-8"))

    collect_port(FakeConn(), MofClient(key="k", transport=httpx.MockTransport(handler)), today=date(2026, 9, 23))
    report = next(c for c in calls if "VsslEtrynd5" in str(c.url)).url.params
    control = next(c for c in calls if "CntlVssl2" in str(c.url)).url.params
    assert (report["sde"], report["ede"]) == ("20260922", "20260930")
    assert (control["sde"], control["ede"]) == ("20260922", "20260923")
    assert "clsgn" not in report and "clsgn" not in control  # 부산 전체


# ---- 추적 대상 선정과 ShipFinder 위치. ShipFinder는 하루 50회 한도라 예산을 지키는지가 핵심이다 ----
import json
from datetime import datetime, timedelta, timezone

from backend.app.clients.mof import SailingPlan
from backend.app.clients.shipfinder import ShipFinderClient
from worker.collector import MAX_TARGETS, Budget, collect_positions, select_targets

SF_FIXTURES = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "shipfinder"
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


class ScriptedConn:
    """SELECT에는 정해 둔 행을 돌려주고, INSERT는 기록만 한다."""

    def __init__(self, known_targets=(), tracked=()):
        self.known, self.tracked, self.inserts = list(known_targets), list(tracked), []

    def execute(self, sql, params=()):
        rows = []
        if "SELECT call_sign FROM targets" in sql:
            rows = [(c,) for c in self.known]
        elif "FROM targets t" in sql:
            rows = [(m,) for m in self.tracked]
        else:
            self.inserts.append((sql, params))
        return type("Cur", (), {"rowcount": 1, "fetchall": lambda self: rows})()


def _sf(fixture: str, calls: list) -> ShipFinderClient:
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=json.loads((SF_FIXTURES / fixture).read_text(encoding="utf-8")))

    return ShipFinderClient(key="test-key", transport=httpx.MockTransport(handler))


def _report(call_sign, kind="풀컨테이너선", stage="변경", hours=24):
    return SailingPlan(call_sign=call_sign, ship_name=f"테스트{call_sign}", nationality=None, ship_kind=kind,
                       purpose=None, previous_port=None, next_port=None,
                       planned_arrival=NOW + timedelta(hours=hours), planned_departure=None,
                       facility=None, revision=stage)


def test_budget_stops_calls():
    b = Budget(2)
    assert [b.take(), b.take(), b.take()] == [True, True, False] and b.remaining == 0


def test_select_targets_matches_call_sign_and_filters_candidates():
    calls, conn = [], ScriptedConn()
    reports = [
        _report("TST01", hours=5),
        _report("TSTBULK", kind="산물선(벌크선)"),       # 컨테이너선이 아니다
        _report("TSTFINAL", stage="최종"),               # 최종 신고는 예정이 아니다
        _report("TSTPAST", hours=-5),                    # 이미 지난 예정
    ]
    result = select_targets(conn, reports, _sf("search_same_name.json", calls), Budget(10), now=NOW)
    assert len(calls) == 1  # 조건에 맞는 한 척만 검색했다
    assert result["targets_added"] == [{"call_sign": "TST01", "mmsi": 440999101}]


def test_select_targets_respects_budget_and_known_targets():
    calls = []
    conn = ScriptedConn(known_targets=["TST02"])
    reports = [_report("TST01", hours=1), _report("TST02", hours=2), _report("TST05", hours=3), _report("TST09", hours=4)]
    select_targets(conn, reports, _sf("search_same_name.json", calls), Budget(2), now=NOW)
    # 이미 대상인 TST02는 건너뛰고, 예산 2회만 쓴다
    assert len(calls) == 2
    assert [p[0] for sql, p in conn.inserts] == ["TST01", "TST05"]


def test_select_targets_keeps_unmatched_ship_so_it_is_not_searched_again():
    calls, conn = [], ScriptedConn()
    result = select_targets(conn, [_report("NOSUCH")], _sf("search_same_name.json", calls), Budget(5), now=NOW)
    assert result["targets_unmatched"] == [{"call_sign": "NOSUCH", "mmsi": None}]
    assert conn.inserts[0][1][:2] == ("NOSUCH", None)


def test_collect_positions_saves_and_respects_budget():
    calls = []
    conn = ScriptedConn(tracked=[440999002, 440999002, 440999002])
    result = collect_positions(conn, _sf("position_ok.json", calls), Budget(2), now=NOW)
    assert len(calls) == 2 and result["tracked"] == 3
    sql, params = conn.inserts[0]
    assert "INSERT INTO positions" in sql and params[0] == 440999002
    assert json.loads(params[-1])["mmsi"] == 440999002  # 원본은 raw(JSONB)로 DB에만 남긴다


def test_targets_fit_daily_shipfinder_limit():
    """대상 전부가 6시간마다(하루 4번) 위치를 받아도 ShipFinder 하루 한도 50회 안이어야 한다."""
    from worker.run import DEFAULT_INTERVAL_HOURS, DEFAULT_SHIPFINDER_CALLS
    runs_per_day = int(24 / DEFAULT_INTERVAL_HOURS)
    assert MAX_TARGETS <= DEFAULT_SHIPFINDER_CALLS and runs_per_day * DEFAULT_SHIPFINDER_CALLS <= 50


# ---- 실행 진입점. 스케줄러는 기본 꺼져 있어야 한다 ----
from worker import run as worker_run


def test_schedule_is_off_by_default(monkeypatch):
    monkeypatch.delenv("WORKER_SCHEDULE", raising=False)
    called = []
    monkeypatch.setattr(worker_run, "run_once", lambda n: called.append(n) or {})
    assert worker_run.main([]) == 0 and called == []  # 한 번도 수집하지 않고 끝난다


def test_once_runs_a_single_collection_with_given_budget(monkeypatch):
    called = []
    monkeypatch.setattr(worker_run, "run_once", lambda n: called.append(n) or {})
    assert worker_run.main(["--once", "--shipfinder-calls", "2"]) == 0 and called == [2]


def test_purge_calls_db_function_and_returns_count():
    """삭제 규칙은 DB 함수에 있다. 워커는 부르기만 한다."""
    from worker.collector import purge_positions

    class Conn:
        def execute(self, sql, params=()):
            self.sql = sql
            return type("Cur", (), {"fetchall": lambda self: [(3,)]})()

    conn = Conn()
    assert purge_positions(conn) == 3 and "purge_old_positions()" in conn.sql


def test_query_purge_calls_db_function_and_returns_count():
    """조회 기록 90일 삭제도 규칙은 DB 함수에 있다 (migrations/008). 파이썬은 부르기만 한다."""
    from backend.app.db import purge_old_queries

    class Conn:
        def execute(self, sql, params=()):
            self.sql = sql
            return type("Cur", (), {"fetchall": lambda self: [(5,)]})()

    conn = Conn()
    assert purge_old_queries(conn) == 5 and "purge_old_queries()" in conn.sql


def test_done_cargo_purge_calls_db_function_and_returns_count():
    """끝난 화물 3년 보관 정리도 규칙은 DB 함수에 있다 (migrations/015, docs/specs/memory.md). 파이썬은 부르기만 한다."""
    from backend.app.db import purge_done_cargo

    class Conn:
        def execute(self, sql, params=()):
            self.sql = sql
            return type("Cur", (), {"fetchall": lambda self: [(2,)]})()

    conn = Conn()
    assert purge_done_cargo(conn) == 2 and "purge_done_cargo()" in conn.sql


def test_watch_positions_purge_calls_db_function_and_returns_count():
    """감시 위치 정리도 규칙은 DB 함수에 있다 (migrations/021). 파이썬은 부르기만 한다."""
    from backend.app.db import MIGRATIONS_DIR, purge_watch_positions

    class Conn:
        def execute(self, sql, params=()):
            self.sql = sql
            return type("Cur", (), {"fetchall": lambda self: [(4,)]})()

    conn = Conn()
    assert purge_watch_positions(conn) == 4 and "purge_old_watch_positions()" in conn.sql
    sql = (MIGRATIONS_DIR / "021_watch_positions_purge.sql").read_text(encoding="utf-8")
    # 30일은 함수 기본값 한 곳에만 있고(002와 같은 기한), 지금 지켜보는 배는 남긴다
    assert "keep_days integer DEFAULT 30" in sql and "DELETE FROM watch_positions" in sql
    assert "c.watch AND c.status = 'active'" in sql
    assert "cron.schedule('marvia-purge-watch-positions'" in sql


def test_migration_015_has_allowed_values_and_schedule():
    """B/L 조건 세 칸은 정해진 값만 받고(CHECK), 정리 함수는 008과 같은 방식으로 pg_cron에 예약된다 (결정 5·9)."""
    from backend.app.db import MIGRATIONS_DIR

    sql = (MIGRATIONS_DIR / "015_memory_conditions_purge.sql").read_text(encoding="utf-8")
    assert "CHECK (original_bl IN ('required', 'surrendered'))" in sql
    assert "CHECK (freight_term IN ('prepaid', 'collect'))" in sql
    assert "CHECK (incoterm IN ('CIF', 'FOB', 'CFR'))" in sql
    assert "to_order_bank BOOLEAN" in sql
    assert "cron.schedule('marvia-purge-done-cargo'" in sql
    # 결정 D3: 끝난 화물은 반출 후 3년 보관 뒤 줄째 지운다. 3년은 함수 기본값 한 곳에만 있다
    assert sql.count("interval '3 years'") == 1 and "DELETE FROM user_cargo" in sql
    assert "CREATE TABLE IF NOT EXISTS user_forget" in sql  # 삭제 표시 (뒤 작업이 삭제를 되살리지 않게)

# ── 감시·지도 위치 수집 (docs/specs/cargo-watch.md, 017) ──

class _WatchConn:
    """SELECT_WATCHED에는 감시 배 목록을, INSERT에는 새 줄 수를 돌려주는 가짜 연결."""

    def __init__(self, mmsis):
        self.mmsis, self.inserted = mmsis, []

    def execute(self, sql, params=()):
        if "FROM user_cargo" in sql:
            return type("Cur", (), {"fetchall": lambda _self: [(m,) for m in self.mmsis]})()
        self.inserted.append(params)
        return type("Cur", (), {"rowcount": 1})()


class _FakeSF:
    """position(mmsi)만 흉내 낸다. 999는 위치가 없는 배."""

    def position(self, mmsi):
        from datetime import datetime, timezone
        from backend.app.clients.shipfinder import ShipFinderError
        if mmsi == 999:
            raise ShipFinderError("not_found", "없음", status=3)
        now = datetime(2026, 10, 2, tzinfo=timezone.utc)
        return type("P", (), {"mmsi": mmsi, "last_time": now, "fetched_at": now, "lat": 34.6, "lng": 128.9,
                              "sog": 12.0, "cog": 60.0, "navistat": 0})()


def test_watch_positions_saved_for_active_cargo_vessels():
    from worker.collector import Budget, collect_watch_positions
    conn = _WatchConn([440000001, 999])
    result = collect_watch_positions(conn, _FakeSF(), Budget(5))
    assert result["watched"] == 2 and result["watch_positions_new"] == 1
    assert result["watch_positions_failed"] == [{"mmsi": 999, "code": "not_found"}]
    assert conn.inserted[0][0] == 440000001 and conn.inserted[0][3:5] == (34.6, 128.9)  # 원본·목적지 글은 넣지 않는다
    assert len(conn.inserted[0]) == 8


def test_watch_positions_stop_when_budget_runs_out():
    from worker.collector import Budget, collect_watch_positions
    conn = _WatchConn([1, 2, 3])
    result = collect_watch_positions(conn, _FakeSF(), Budget(1))
    assert result["watch_positions_new"] == 1 and len(conn.inserted) == 1


def test_watch_positions_only_for_watched_cargo():
    """진행 중 화물 전체가 아니라 지켜보기를 켠 화물의 배만 받는다 (user_cargo.watch, 017_cargo_watch)."""
    from worker.collector import SELECT_WATCHED
    sql = " ".join(SELECT_WATCHED.split())
    assert "status = 'active' AND watch AND vessel_mmsi IS NOT NULL" in sql
