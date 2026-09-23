"""수집 워커의 한 번 실행분 (작업 D1·D2, SDD 5.10). 판정은 하지 않고 저장만 한다.

한 번 돌 때 하는 일:
1. collect_port: 해수부 두 API에서 부산 전체를 받아 저장한다. 호출 한도가 넉넉해서 매번 전체를 받는다
   - 입항 신고(선박운항정보): 어제부터 LOOKAHEAD_DAYS일 뒤까지. 예정 시각이 바뀔 때마다 새 줄이 쌓인다
   - 관제 이벤트(관제정보): 어제와 오늘. 입항·투묘·양묘·접안이 쌓인다
2. collect_positions (다음 커밋): 추적 대상 선박만 ShipFinder 위치를 받는다. 하루 50회 한도라 예산을 둔다

DB 연결(conn)은 인자로 받는다. psycopg 연결이든 테스트용 가짜든 execute()만 있으면 된다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from backend.app.clients.mof import MofClient

# 입항 신고를 오늘부터 며칠 뒤까지 볼지. 해수부 신고가 1주 앞까지 나온다 (09-24~30 조회 264척, 2026-09-23 실측).
# mcp_server/tools/port_schedule.py의 LOOKAHEAD_DAYS와 같은 근거다
LOOKAHEAD_DAYS = 7
# 어제 것도 다시 받는 이유: 관제 이벤트가 늦게 올라오거나 신고가 최종으로 바뀌는 것을 놓치지 않으려고
LOOKBACK_DAYS = 1

INSERT_REPORT = """
INSERT INTO arrival_reports (call_sign, ship_name, ship_kind, stage, arrival_at, facility, mrn, fetched_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING
"""
INSERT_EVENT = """
INSERT INTO control_events (call_sign, ship_name, kind, at, facility, fetched_at)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING
"""


def _inserted(cursor) -> int:
    """ON CONFLICT DO NOTHING으로 건너뛰면 rowcount가 0이다. 새로 들어간 줄만 센다."""
    return max(getattr(cursor, "rowcount", 0) or 0, 0)


def collect_port(conn, mof: MofClient, today: date | None = None) -> dict:
    """해수부 입항 신고와 관제 이벤트를 저장하고, 받은 건수와 새로 저장한 건수를 돌려준다."""
    today = today or date.today()
    now = datetime.now(timezone.utc)

    reports = mof.arrival_reports(today - timedelta(days=LOOKBACK_DAYS), today + timedelta(days=LOOKAHEAD_DAYS))
    new_reports = 0
    for r in reports:
        cur = conn.execute(INSERT_REPORT, (r.call_sign, r.ship_name, r.ship_kind, r.stage, r.arrival_at, r.facility, r.mrn, now))
        new_reports += _inserted(cur)

    calls = mof.control_records(today - timedelta(days=LOOKBACK_DAYS), today)
    events = [(c, e) for c in calls for e in c.events if e.at]  # 시각 없는 이벤트는 쓸 데가 없다
    new_events = 0
    for c, e in events:
        cur = conn.execute(INSERT_EVENT, (c.call_sign, c.ship_name, e.kind, e.at, e.facility, now))
        new_events += _inserted(cur)

    return {
        "reports_seen": len(reports),
        "reports_new": new_reports,
        "events_seen": len(events),
        "events_new": new_events,
        "reports": reports,  # 다음 단계(추적 대상 선정)가 다시 부르지 않고 쓴다
    }
