"""DB 연결과 마이그레이션 (설계 8절: 마이그레이션은 SQL 파일로 두고 시작할 때 적용한다).

하지 않는 일: 적용 기록 표. 1차는 migrations/*.sql을 이름 순서로 모두 돌리고,
파일마다 IF NOT EXISTS로 써서 여러 번 돌려도 같게 한다.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def apply_migrations(conn: psycopg.Connection) -> None:
    """migrations/*.sql을 이름 순서로 돌린다."""
    for path in sorted(MIGRATIONS.glob("*.sql")):
        # [왜] 값 자리(%s)가 없는 SQL은 한 번에 여러 문장을 보낼 수 있다.
        # 파일 글을 bytes로 넘긴다: psycopg 타입 표시는 코드에 직접 쓴 글이나 bytes만 받는다(SQL 주입 방지)
        conn.execute(path.read_bytes())
    conn.commit()


def connect(url: str) -> psycopg.Connection:
    """DB에 연결하고 마이그레이션을 적용한다."""
    conn = psycopg.connect(url)
    apply_migrations(conn)
    return conn
