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


def connect(url: str | None = None):
    """DATABASE_URL로 연결한다. autocommit이라 넣는 즉시 저장된다 (워커는 한 줄씩 넣는다)."""
    import psycopg

    return psycopg.connect(plain_url(url or os.environ["DATABASE_URL"]), autocommit=True)


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

    B/L 원본은 넣지 않는다. 부르는 쪽이 bl_masked만 넘긴다.
    이력 저장이 실패해도 판정 응답은 나가야 하므로 부르는 쪽에서 예외를 삼킨다.
    """
    columns = ["session_id", *fields.keys()]
    placeholders = ", ".join(["%s"] * len(columns))
    conn.execute(
        f"INSERT INTO query_log ({', '.join(columns)}) VALUES ({placeholders})",
        [session_id, *fields.values()],
    )


def recent_queries(conn, session_id: str, limit: int = 20) -> list[dict]:
    """세션의 지난 조회를 최신순으로 읽는다. 새로 계산하거나 저장하지 않는다 (SDD 4.4)."""
    rows = conn.execute(
        """
        SELECT request_id, bl_masked, status, verdict, vessel_match, decided_by, model, trace_id, created_at
        FROM query_log WHERE session_id = %s ORDER BY created_at DESC LIMIT %s
        """,
        [session_id, min(limit, 100)],
    ).fetchall()
    keys = ("request_id", "bl_masked", "status", "verdict", "vessel_match", "decided_by", "model", "trace_id", "created_at")
    return [dict(zip(keys, row)) for row in rows]
