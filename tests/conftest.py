"""모든 시험이 함께 쓰는 준비물: 로컬 DB의 시험용 스키마(db, test_url). 처음엔 tests/rag에만 있었다."""

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from marvia.config import Settings
from marvia.db import apply_migrations

URL = Settings().database_url


@pytest.fixture
def db():
    """시험용 스키마에 표를 만들고 끝나면 스키마째 지운다. 로컬 DB가 꺼져 있으면 건너뛴다."""
    try:
        conn = psycopg.connect(URL, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("로컬 Postgres가 꺼져 있음 (docker compose up -d db)")
    # [왜] 스키마는 DB 안의 폴더 같은 것. 실제 색인(public)과 섞이지 않게 marvia_test에 따로 만든다
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
    conn.execute("DROP SCHEMA IF EXISTS marvia_test CASCADE")
    conn.execute("CREATE SCHEMA marvia_test")
    conn.execute("SET search_path TO marvia_test, public")  # 표 이름을 marvia_test에서 먼저 찾는다
    apply_migrations(conn)
    yield conn
    conn.rollback()
    conn.execute("DROP SCHEMA marvia_test CASCADE")
    conn.commit()
    conn.close()


@pytest.fixture
def test_url():
    """marvia_test 스키마를 만들고 그 스키마를 먼저 보는 접속 문자열을 준다. 끝나면 스키마째 지운다."""
    try:
        conn = psycopg.connect(URL, connect_timeout=2, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("로컬 Postgres가 꺼져 있음 (docker compose up -d db)")
    conn.execute("DROP SCHEMA IF EXISTS marvia_test CASCADE")
    conn.execute("CREATE SCHEMA marvia_test")
    # [왜] search_path: 라이브러리가 만드는 표(checkpoints, store)가 public이 아니라 marvia_test에 생긴다
    yield make_conninfo(URL, options="-c search_path=marvia_test")
    conn.execute("DROP SCHEMA marvia_test CASCADE")
    conn.close()
