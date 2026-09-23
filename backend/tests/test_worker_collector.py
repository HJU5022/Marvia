"""D1 수집 워커 단위 테스트. DB 대신 가짜 연결, 외부 API 대신 가공 fixture로 키 없이 돈다."""
from datetime import date
from pathlib import Path

import httpx

from backend.app.clients.mof import MofClient
from worker.collector import collect_port

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "mof"


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

SF_FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "shipfinder"
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
    conn = ScriptedConn(tracked=[413961925, 413961925, 413961925])
    result = collect_positions(conn, _sf("position_ok.json", calls), Budget(2), now=NOW)
    assert len(calls) == 2 and result["tracked"] == 3
    sql, params = conn.inserts[0]
    assert "INSERT INTO positions" in sql and params[0] == 413961925
    assert json.loads(params[-1])["mmsi"] == 413961925  # 원본은 raw(JSONB)로 DB에만 남긴다


def test_max_targets_is_task_list_range():
    assert 20 <= MAX_TARGETS <= 30  # 작업 리스트 D1 "부산행 20~30척"


# ---- 실행 진입점. 스케줄러는 기본 꺼져 있어야 한다 (09-23 결정) ----
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
