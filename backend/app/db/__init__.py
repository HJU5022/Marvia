"""DB 연결과 마이그레이션 (SDD 3.9). 워커가 먼저 쓰고, 앱도 기동할 때 같은 함수를 쓴다.

psycopg는 함수 안에서 import한다. DB가 필요 없는 단위 테스트가 이 모듈을 불러도
psycopg 설치 없이 돌게 하려는 것이다 (CLAUDE.md: 테스트는 키 없이 돈다).
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def plain_url(url: str) -> str:
    """postgresql+asyncpg://... 같은 SQLAlchemy식 주소를 psycopg가 읽는 postgresql://... 로 바꾼다.

    compose의 api 서비스가 asyncpg 주소를 쓰고 있어서, 같은 DATABASE_URL을 워커도 읽을 수 있게 한다.
    """
    scheme, sep, rest = url.partition("://")
    return f"{scheme.split('+', 1)[0]}{sep}{rest}" if sep else url


def connect(url: str | None = None, timeout: int | None = None):
    """DATABASE_URL로 연결한다. autocommit이라 넣는 즉시 저장된다 (워커는 한 줄씩 넣는다).

    timeout(초)을 주면 그 안에 못 붙을 때 포기한다. /health처럼 빨리 답해야 하는 곳이 쓴다.
    """
    import psycopg

    extra = {"connect_timeout": timeout} if timeout else {}
    return psycopg.connect(plain_url(url or os.environ["DATABASE_URL"]), autocommit=True, **extra)


def atomic(conn):
    """여러 표를 지우는 일을 한 트랜잭션으로 묶는다 (삭제 경로, docs/specs/memory.md 개인정보, 검증).
    connect()는 autocommit이라 이 안에서만 BEGIN·COMMIT으로 묶인다(psycopg Connection.transaction).
    트랜잭션 기능이 없는 연결(테스트의 가짜 연결)은 묶지 않고 그대로 실행한다."""
    from contextlib import nullcontext

    return conn.transaction() if hasattr(conn, "transaction") else nullcontext()


# 마이그레이션 전체를 감싸는 pg advisory lock 번호. 아무 값이나 되지만 앱 안에서 이 용도로만 쓴다.
# 'marvia-migrations'의 뜻으로 고정한 64비트 정수다
MIGRATION_LOCK_ID = 7_310_620_261_006


def apply_migrations(conn) -> list[str]:
    """migrations/*.sql을 이름 순서대로 한 번씩만 적용하고, 새로 적용한 파일 이름을 돌려준다.

    점검으로 두 가지를 더했다.
    - 전체를 pg_advisory_lock으로 감싼다. api와 worker가 동시에 떠서 같은 파일을 두 번 적용하려다 한쪽이
      "already exists"나 schema_migrations 중복 키로 죽는 경쟁을 막는다. 뒤에 온 쪽은 앞쪽이 끝날 때까지 기다린 뒤
      적용된 목록을 다시 읽어 건너뛴다. 잠금은 finally에서 풀고, 연결이 끊겨도 DB가 풀어 준다(세션 잠금)
    - 파일 하나를 한 트랜잭션으로 묶는다. connect()가 autocommit이라 전에는 파일 중간 문장이 실패하면 앞 문장만 남고
      schema_migrations에는 안 적혀, 다음 기동 때 반쯤 적용된 상태에서 다시 돌았다. 이제 파일과 기록이 함께 들어가거나 함께 빠진다
    """
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())"
        )
        done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()}
        applied = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            with atomic(conn):
                # 파라미터 없는 execute는 여러 문장을 한 번에 보낼 수 있다 (psycopg 3)
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
        return applied
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))


def log_query(conn, session_id: str, **fields) -> None:
    """조회 이력 한 줄을 남긴다 (A12, SDD 3.9).

    B/L 원본을 그대로 넣지 않는다. 부르는 쪽이 bl_masked와, 로그인했으면 잠긴 bl_encrypted만 넘긴다 (crypto.py, 007).
    이력 저장이 실패해도 판정 응답은 나가야 하므로 부르는 쪽에서 예외를 삼킨다.
    """
    columns = ["session_id", *fields.keys()]
    placeholders = ", ".join(["%s"] * len(columns))
    conn.execute(
        f"INSERT INTO query_log ({', '.join(columns)}) VALUES ({placeholders})",
        [session_id, *fields.values()],
    )


def _owner(session_id: str, user_id: str | None) -> tuple[str, str]:
    """이력을 누구 기준으로 찾을지 WHERE 조건과 값으로 돌려준다 (G3, 006 마이그레이션).

    로그인했으면 사용자 ID로 찾는다. 브라우저가 바뀌어도 이어진다.
    사용자가 없으면(로그인 기능이 꺼진 채점 환경, 로그인은 필수) 세션 ID로 찾되 로그인한 채 남긴 줄은 뺀다.
    같은 DB를 로그인 켠 환경과 같이 쓰더라도 사용자 기록이 세션 조회로 새지 않게 한다 (실제 DB 확인 중 발견).
    조건 문자열은 이 두 가지로만 정해진다. 사용자 입력은 값(%s)으로만 들어간다.
    """
    return ("user_id = %s", user_id) if user_id else ("session_id = %s AND user_id IS NULL", session_id)


def recent_queries(conn, session_id: str, limit: int = 20, user_id: str | None = None,
                   since: datetime | None = None) -> list[dict]:
    """세션(로그인했으면 사용자)의 지난 조회를 최신순으로 읽는다. 새로 계산하거나 저장하지 않는다 (SDD 4.4).
    since가 있으면 그 시각 이후(>=)만 읽는다 (설정 화면 기간 필터).
    days_margin·stage_name은 저장된 결과(response JSONB)에서 두 값만 꺼낸다. 이력 한 줄 이유(routers/history)를 코드로 만드는 재료다."""
    where, owner = _owner(session_id, user_id)
    params: list = [owner]
    if since is not None:
        where += " AND created_at >= %s"
        params.append(since)
    params.append(min(limit, 100))
    rows = conn.execute(
        f"""
        SELECT request_id, bl_masked, status, verdict, vessel_match, decided_by, trace_id, created_at,
               (response->>'days_margin')::int, response->'customs'->>'stage_name'
        FROM query_log WHERE {where} ORDER BY created_at DESC LIMIT %s
        """,
        params,
    ).fetchall()
    # model 칸은 018에서 지웠다 (저장하는 코드가 없어 늘 비어 있었다). 이력 응답의 model은 null로 남긴다
    keys = ("request_id", "bl_masked", "status", "verdict", "vessel_match", "decided_by", "trace_id", "created_at",
            "days_margin", "stage_name")
    return [dict(zip(keys, row)) for row in rows]


def latest_response(conn, session_id: str, bl_masked: str, user_id: str | None = None) -> dict | None:
    """같은 세션(로그인했으면 사용자)·같은 B/L의 가장 최근 결과(AgentResponse JSON)를 읽는다. 후속 질문이 쓴다 (C-9, 004 마이그레이션).

    결과가 저장되지 않은 옛 줄(response가 NULL)은 건너뛴다. 없으면 None.
    """
    where, owner = _owner(session_id, user_id)
    row = conn.execute(
        f"""
        SELECT response FROM query_log
        WHERE {where} AND bl_masked = %s AND response IS NOT NULL
        ORDER BY created_at DESC LIMIT 1
        """,
        [owner, bl_masked],
    ).fetchone()
    return row[0] if row else None


def recent_responses(conn, session_id: str, bl_masked: str, user_id: str | None = None,
                     limit: int = 20) -> list[tuple[dict, str | None]]:
    """같은 가린 번호의 최근 결과와 잠긴 B/L 원본을 최신순으로 (결과, bl_encrypted) 목록으로 읽는다.
    가린 번호가 같은 두 화물을 가를 때 쓴다 (docs/specs/memory.md EC-05, routers/agent._previous_response)."""
    where, owner = _owner(session_id, user_id)
    rows = conn.execute(
        f"""
        SELECT response, bl_encrypted FROM query_log
        WHERE {where} AND bl_masked = %s AND response IS NOT NULL
        ORDER BY created_at DESC LIMIT %s
        """,
        [owner, bl_masked, limit],
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def delete_user_queries(conn, user_id: str) -> int:
    """로그인 사용자의 조회 기록을 전부 지우고 지운 줄 수를 돌려준다 (삭제 2단계, 개인정보보호법 제36조).

    잠긴 B/L(bl_encrypted)도 같은 줄에 있어 함께 지워진다. 다른 사용자 줄과 사용자 없는 줄은 건드리지 않는다.
    """
    return conn.execute("DELETE FROM query_log WHERE user_id = %s", [user_id]).rowcount


def purge_old_queries(conn) -> int:
    """90일 지난 조회 기록을 지우고 지운 줄 수를 돌려준다 (개인정보보호법 제21조).

    규칙(90일)은 DB 함수 purge_old_queries()에만 있다 (migrations/008). Supabase는 pg_cron이 하루 한 번
    부르고, pg_cron이 없는 로컬·채점용 DB는 워커가 실행마다 부른다. 여러 번 불러도 결과는 같다.
    """
    return conn.execute("SELECT purge_old_queries()").fetchall()[0][0]


def purge_done_cargo(conn) -> int:
    """반출 뒤 3년 지난 끝난 화물 줄과 그 화물의 메모장 항목을 지우고 지운 화물 수를 돌려준다
    (docs/specs/memory.md "보관과 크기", 결정 D3). 하루 지난 삭제 표시(user_forget)도 같이 정리한다.

    규칙(3년, 무엇을 지우나)은 DB 함수 purge_done_cargo()에만 있다 (migrations/015). purge_old_queries와 같이 pg_cron이 하루 한 번,
    pg_cron이 없는 로컬·채점용 DB는 워커가 실행마다 부른다. 여러 번 불러도 결과는 같다.
    """
    return conn.execute("SELECT purge_done_cargo()").fetchall()[0][0]


def purge_old_conversations(conn) -> int:
    """마지막 대화로부터 90일 지난 대화(말풍선 포함)를 지우고 지운 대화 수를 돌려준다 (대화 목록).

    규칙(90일)은 DB 함수 purge_old_conversations()에만 있다 (migrations/018). purge_old_queries와 같이 pg_cron이 하루 한 번,
    pg_cron이 없는 로컬·채점용 DB는 워커가 실행마다 부른다. 여러 번 불러도 결과는 같다.
    """
    return conn.execute("SELECT purge_old_conversations()").fetchall()[0][0]


def purge_watch_positions(conn) -> int:
    """더 지켜보지 않는 배의 30일 지난 감시·지도 위치(watch_positions)를 지우고 지운 줄 수를 돌려준다.

    규칙(30일, 지금 지켜보는 배는 남김)은 DB 함수 purge_old_watch_positions()에만 있다 (migrations/021). purge_old_queries와
    같이 pg_cron이 하루 한 번, pg_cron이 없는 로컬·채점용 DB는 워커가 실행마다 부른다. 여러 번 불러도 결과는 같다.
    """
    return conn.execute("SELECT purge_old_watch_positions()").fetchall()[0][0]


def recent_positions(conn, mmsi: int, limit: int = 20) -> list[dict]:
    """워커가 모은 같은 배의 위치 이력을 오래된 순으로 읽는다. anchor_wait 정지 시간 계산용 (services/judge/signals.py).

    limit 20줄은 워커 6시간 간격이면 약 5일치다. 정지 기준 24시간(rules.md anchor_wait_hours)과
    그 앞에 움직이던 점까지 보기에 넉넉하다. 모양은 signals.compute의 history와 같게 {"at", "lat", "lng", "sog"}.
    """
    rows = conn.execute(
        "SELECT ts, lat, lng, sog FROM positions WHERE mmsi = %s ORDER BY ts DESC LIMIT %s",
        [mmsi, limit],
    ).fetchall()
    return [{"at": ts, "lat": lat, "lng": lng, "sog": sog} for ts, lat, lng, sog in reversed(rows)]
