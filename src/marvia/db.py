"""DB 연결과 마이그레이션 (설계 8절: 마이그레이션은 SQL 파일로 두고 시작할 때 적용한다).

하지 않는 일: 적용 기록 표. 1차는 migrations/*.sql을 이름 순서로 모두 돌리고,
파일마다 IF NOT EXISTS로 써서 여러 번 돌려도 같게 한다.
읽기 연결 풀(read_pool)은 마이그레이션을 돌리지 않는다. 표가 있는 DB에 붙는다 (계획 4b, R-066).
"""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool

from marvia.tools.rules import load_rules

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def apply_migrations(conn: psycopg.Connection) -> None:
    """migrations/*.sql을 이름 순서로 돌린다. 파일을 하나도 못 찾으면 실패한다."""
    paths = sorted(MIGRATIONS.glob("*.sql"))
    if not paths:
        # [왜] 조용히 끝나면 표가 없는 채로 다음 단계가 돈다. 시험 스키마가 비면 이름만 쓴 표가 public으로
        #      풀려 시험 줄이 개발 색인에 들어간다 (11-13: migrations/ 없는 나무에서 돌린 시험)
        raise RuntimeError(f"마이그레이션 파일이 없다: {MIGRATIONS}")
    for path in paths:
        # [왜] 값 자리(%s)가 없는 SQL은 한 번에 여러 문장을 보낼 수 있다.
        # 파일 글을 bytes로 넘긴다: psycopg 타입 표시는 코드에 직접 쓴 글이나 bytes만 받는다(SQL 주입 방지)
        conn.execute(path.read_bytes())
    conn.commit()


def connect(url: str) -> psycopg.Connection:
    """DB에 연결하고 마이그레이션을 적용한다."""
    conn = psycopg.connect(url)
    apply_migrations(conn)
    return conn


def read_pool(url: str) -> ConnectionPool:
    """검색·조문 조회가 부를 때마다 빌려 쓰는 읽기 연결 풀. with 블록으로 열고 닫는다.

    [왜] 연결 하나를 RAG 검색·조문 조회·MCP 서버·병렬 search_law가 함께 쓰면, SELECT 뒤 트랜잭션이
         "idle in transaction"으로 남아 VACUUM과 CREATE INDEX CONCURRENTLY를 막고(11-06 실측: 시험이 멈춤),
         한 요청의 오류가 함께 쓰는 연결을 실패 상태로 만들어 다른 요청까지 죽인다 (R-066).
    [왜] autocommit: 문장마다 바로 끝나 읽은 뒤 열린 트랜잭션이 없다. 검색은 읽기만 해서 묶을 트랜잭션이 없다.
    [주의] 쓰기(색인·감시 표)는 이 풀을 쓰지 않는다. connect()나 따로 연 연결을 쓴다.
    """
    cfg = load_rules("server")["pool"]
    # [왜] open=False: 만들기만 하고 with 블록에 들어갈 때 연다.
    #      라이브러리가 암묵적 열기를 곧 없앤다고 경고한다(psycopg_pool pool.py)
    return ConnectionPool(
        url,
        kwargs={"autocommit": True},
        min_size=cfg["min_size"],
        max_size=cfg["max_size"],
        timeout=cfg["timeout_s"],
        open=False,
    )
