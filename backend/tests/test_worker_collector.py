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
