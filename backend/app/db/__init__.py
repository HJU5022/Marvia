"""DB 연결과 마이그레이션 (SDD 3.9). 워커가 먼저 쓰고, 앱도 기동할 때 같은 함수를 쓴다.

psycopg는 함수 안에서 import한다. DB가 필요 없는 단위 테스트가 이 모듈을 불러도
psycopg 설치 없이 돌게 하려는 것이다 (CLAUDE.md: 테스트는 키 없이 돈다).
"""
from __future__ import annotations

import os
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
    """여러 표를 지우는 일을 한 트랜잭션으로 묶는다 (삭제 경로, docs/specs/memory.md 개인정보, 10-02 검증).
    connect()는 autocommit이라 이 안에서만 BEGIN·COMMIT으로 묶인다(psycopg Connection.transaction).
    트랜잭션 기능이 없는 연결(테스트의 가짜 연결)은 묶지 않고 그대로 실행한다."""
    from contextlib import nullcontext

    return conn.transaction() if hasattr(conn, "transaction") else nullcontext()


def apply_migrations(conn) -> list[str]:
    """migrations/*.sql을 이름 순서대로 한 번씩만 적용하고, 새로 적용한 파일 이름을 돌려준다."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())"
    )
    done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()}
    applied = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in done:
            continue
        # 파라미터 없는 execute는 여러 문장을 한 번에 보낼 수 있다 (psycopg 3)
        conn.execute(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied


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
    사용자가 없으면(로그인 기능이 꺼진 채점 환경, 로그인은 09-30부터 필수) 세션 ID로 찾되 로그인한 채 남긴 줄은 뺀다.
    같은 DB를 로그인 켠 환경과 같이 쓰더라도 사용자 기록이 세션 조회로 새지 않게 한다 (09-30 실제 DB 확인 중 발견).
    조건 문자열은 이 두 가지로만 정해진다. 사용자 입력은 값(%s)으로만 들어간다.
    """
    return ("user_id = %s", user_id) if user_id else ("session_id = %s AND user_id IS NULL", session_id)


def recent_queries(conn, session_id: str, limit: int = 20, user_id: str | None = None) -> list[dict]:
    """세션(로그인했으면 사용자)의 지난 조회를 최신순으로 읽는다. 새로 계산하거나 저장하지 않는다 (SDD 4.4)."""
    where, owner = _owner(session_id, user_id)
    rows = conn.execute(
        f"""
        SELECT request_id, bl_masked, status, verdict, vessel_match, decided_by, trace_id, created_at
        FROM query_log WHERE {where} ORDER BY created_at DESC LIMIT %s
        """,
        [owner, min(limit, 100)],
    ).fetchall()
    # model 칸은 018에서 지웠다 (저장하는 코드가 없어 늘 비어 있었다). 이력 응답의 model은 null로 남긴다
    keys = ("request_id", "bl_masked", "status", "verdict", "vessel_match", "decided_by", "trace_id", "created_at")
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
    """90일 지난 조회 기록을 지우고 지운 줄 수를 돌려준다 (09-30 결정, 개인정보보호법 제21조).

    규칙(90일)은 DB 함수 purge_old_queries()에만 있다 (migrations/008). Supabase는 pg_cron이 하루 한 번
    부르고, pg_cron이 없는 로컬·채점용 DB는 워커가 실행마다 부른다. 여러 번 불러도 결과는 같다.
    """
    return conn.execute("SELECT purge_old_queries()").fetchall()[0][0]


def purge_done_cargo(conn) -> int:
    """반출 뒤 3년 지난 끝난 화물 줄과 그 화물의 메모장 항목을 지우고 지운 화물 수를 돌려준다
    (docs/specs/memory.md "보관과 크기", 10-02 결정 D3). 하루 지난 삭제 표시(user_forget)도 같이 정리한다.

    규칙(3년, 무엇을 지우나)은 DB 함수 purge_done_cargo()에만 있다 (migrations/015). purge_old_queries와 같이 pg_cron이 하루 한 번,
    pg_cron이 없는 로컬·채점용 DB는 워커가 실행마다 부른다. 여러 번 불러도 결과는 같다.
    """
    return conn.execute("SELECT purge_done_cargo()").fetchall()[0][0]


def purge_old_conversations(conn) -> int:
    """마지막 대화로부터 90일 지난 대화(말풍선 포함)를 지우고 지운 대화 수를 돌려준다 (10-06 결정, 대화 목록).

    규칙(90일)은 DB 함수 purge_old_conversations()에만 있다 (migrations/018). purge_old_queries와 같이 pg_cron이 하루 한 번,
    pg_cron이 없는 로컬·채점용 DB는 워커가 실행마다 부른다. 여러 번 불러도 결과는 같다.
    """
    return conn.execute("SELECT purge_old_conversations()").fetchall()[0][0]


def recent_positions(conn, mmsi: int, limit: int = 20) -> list[dict]:
    """워커가 모은 같은 배의 위치 이력을 오래된 순으로 읽는다. anchor_wait 정지 시간 계산용 (services/signals.py).

    limit 20줄은 워커 6시간 간격(09-23 결정)이면 약 5일치다. 정지 기준 24시간(rules.md anchor_wait_hours)과
    그 앞에 움직이던 점까지 보기에 넉넉하다. 모양은 signals.compute의 history와 같게 {"at", "lat", "lng", "sog"}.
    """
    rows = conn.execute(
        "SELECT ts, lat, lng, sog FROM positions WHERE mmsi = %s ORDER BY ts DESC LIMIT %s",
        [mmsi, limit],
    ).fetchall()
    return [{"at": ts, "lat": lat, "lng": lng, "sog": sog} for ts, lat, lng, sog in reversed(rows)]
