"""읽기 연결 풀 시험 (R-066, 계획 4b Task 2). 실제 Postgres와 실제 검색 길에 가짜 임베딩·리랭커를 넣는다.

로컬 DB가 꺼져 있으면 건너뛴다(MARVIA_REQUIRE_DB=1이면 실패).
"""

from datetime import date
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from marvia.config import Settings
from marvia.db import read_pool
from marvia.rag.index import index_units
from marvia.rag.search import hybrid_search

AS_OF = date(2026, 10, 30)


def idle_in_transaction(url: str, name: str) -> int:
    """이름(application_name)이 name인 연결 가운데 idle in transaction인 수."""
    # [왜] 같은 DB에 다른 시험·작업의 연결이 있을 수 있다. 이 시험의 풀 연결만 이름으로 센다
    with psycopg.connect(url, autocommit=True) as conn:
        sql = (
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE application_name = %s AND state = 'idle in transaction'"
        )
        return conn.execute(sql, (name,)).fetchone()[0]


@pytest.fixture
def pooled(db, make_unit, fake_embed):
    """시험용 스키마에 단위 둘을 색인하고, 이 시험만의 이름을 붙인 접속 문자열과 이름을 준다."""
    units = [make_unit("제1조", "수입신고는 입항 후에 한다"), make_unit("제2조", "정밀검사를 면제할 수 있다")]
    index_units(db, units, fake_embed)
    schema = db.execute("SELECT current_schema()").fetchone()[0]
    db.commit()

    name = f"marvia-read-{uuid4().hex[:8]}"
    # [왜] pgvector 타입은 public에 있다. 시험용 스키마 다음에 public을 둔다 (tests/conftest.py의 db와 같다)
    options = f"-c search_path={schema},public"
    return make_conninfo(Settings().database_url, options=options, application_name=name), name


def test_a_search_leaves_no_connection_idle_in_transaction(pooled, fake_embed):
    url, name = pooled
    with read_pool(url) as pool:
        with pool.connection() as conn:
            hits = hybrid_search(conn, "정밀검사 면제", fake_embed, AS_OF)
        assert hits[0].unit_id == "LTEST@20261002#제2조"
        assert idle_in_transaction(url, name) == 0  # [왜] 지금(HEAD)의 공유 연결은 1이었다 (11-07 실측)
