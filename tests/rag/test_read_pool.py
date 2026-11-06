"""읽기 연결 풀 시험 (R-066, 계획 4b Task 2). 실제 Postgres와 실제 검색 길에 가짜 임베딩·리랭커를 넣는다.

로컬 DB가 꺼져 있으면 건너뛴다(MARVIA_REQUIRE_DB=1이면 실패).
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from marvia.config import Settings
from marvia.db import read_pool
from marvia.rag import voyage
from marvia.rag.index import index_units
from marvia.rag.live import live_deps
from marvia.rag.models import SearchFailed
from marvia.rag.search import hybrid_search

AS_OF = date(2026, 10, 30)
BROKEN = "고장 난 질의"  # 이 질의만 임베딩 차원이 틀려 DB 오류를 낸다


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


SETTINGS = Settings(_env_file=None, anthropic_api_key="sk-test-not-real", voyage_api_key="test", graph="off")


def test_a_search_leaves_no_connection_idle_in_transaction(pooled, fake_embed):
    url, name = pooled
    with read_pool(url) as pool:
        with pool.connection() as conn:
            hits = hybrid_search(conn, "정밀검사 면제", fake_embed, AS_OF)
            # [왜] 빌린 동안 열린 트랜잭션이 없어야 한다. autocommit을 빼면 여기서 1이 된다
            assert idle_in_transaction(url, name) == 0
        assert hits[0].unit_id == "LTEST@20261002#제2조"
        assert idle_in_transaction(url, name) == 0  # [왜] 지금(HEAD)의 공유 연결은 1이었다 (11-07 실측)


def test_concurrent_mcp_searches_do_not_break_each_other(pooled, fake_embed, monkeypatch):
    url, name = pooled

    def embed(texts, settings, input_type):
        # [왜] 차원이 3인 벡터는 vector(1024) 칸과 맞지 않아 DB 오류가 난다.
        #      동시 요청 하나만 일부러 실패시킨다
        return [[0.0] * 3 for _ in texts] if BROKEN in texts[0] else fake_embed(texts)

    monkeypatch.setattr(voyage, "embed", embed)
    monkeypatch.setattr(
        voyage, "rerank", lambda query, texts, settings: [1.0 / (i + 1) for i in range(len(texts))]
    )
    queries = ["정밀검사 면제"] * 7 + [BROKEN]
    with read_pool(url) as pool:
        rag = live_deps(SETTINGS, pool)  # 기본 rag_via=mcp: 같은 MCP 서버를 메모리 통로로 부른다
        assert rag.ranked is not None

        def one(query: str):
            try:
                return rag.ranked(query, AS_OF)
            except SearchFailed as error:
                return error

        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(one, queries))
        assert idle_in_transaction(url, name) == 0
    # [왜] 한 요청의 DB 오류가 같은 연결을 쓰는 다른 요청을 실패 상태로 만들지 않는다. 고장 난 질의만 실패한다
    assert [isinstance(r, SearchFailed) for r in results] == [False] * 7 + [True]
    assert all(r[0].unit_id == "LTEST@20261002#제2조" for r in results[:7])
