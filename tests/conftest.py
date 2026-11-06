"""모든 시험이 함께 쓰는 준비물: 로컬 DB의 시험용 스키마(db, test_url). 처음엔 tests/rag에만 있었다."""

from uuid import uuid4

import psycopg
import pytest
from db_required import db_unreachable, neo4j_unreachable
from neo4j.exceptions import DriverError, Neo4jError
from psycopg.conninfo import make_conninfo

from marvia.config import Settings
from marvia.db import apply_migrations
from marvia.rag.graphdb import connect_graph

URL = Settings().database_url
# [왜] 시험 실행마다 다른 스키마 이름. 이름이 같으면 동시에 돈 실행(host·Docker·다른 작업)이 서로의
#      스키마를 지운다. [주의] 컨테이너마다 pid가 겹칠 수 있어 pid 대신 무작위 글자를 붙인다
SCHEMA = f"marvia_test_{uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def unipass_replay_only(monkeypatch):
    """모든 시험은 UNI-PASS 재생 데이터만 쓴다. [왜] .env에 live와 키가 있어도 실제 API를 부르지 않는다"""
    monkeypatch.setenv("MARVIA_UNIPASS_MODE", "replay")


@pytest.fixture
def db():
    """시험용 스키마에 표를 만들고 끝나면 스키마째 지운다. 로컬 DB가 꺼져 있으면 건너뛴다."""
    try:
        conn = psycopg.connect(URL, connect_timeout=2)
    except psycopg.OperationalError:
        db_unreachable()
    # [왜] 스키마는 DB 안의 폴더 같은 것. 실제 색인(public)과 섞이지 않게 시험용 스키마에 따로 만든다
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
    conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    conn.execute(f"CREATE SCHEMA {SCHEMA}")
    # 표 이름을 시험용 스키마에서 먼저 찾는다. [주의] public은 뺄 수 없다. pgvector 확장(vector 타입, <=>)이
    # public에 있다(11-06 확인, 빼면 'type "vector" does not exist'). 시험용 스키마는 이 실행만 지우므로
    # 실행 중에 스키마가 사라져 이름 없는 쓰기가 public으로 가는 일은 없다
    conn.execute(f"SET search_path TO {SCHEMA}, public")
    apply_migrations(conn)
    yield conn
    conn.rollback()
    conn.execute(f"DROP SCHEMA {SCHEMA} CASCADE")
    conn.commit()
    conn.close()


@pytest.fixture
def test_url():
    """시험용 스키마를 만들고 그 스키마만 보는 접속 문자열을 준다. 끝나면 스키마째 지운다."""
    try:
        conn = psycopg.connect(URL, connect_timeout=2, autocommit=True)
    except psycopg.OperationalError:
        db_unreachable()
    conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    conn.execute(f"CREATE SCHEMA {SCHEMA}")
    # [왜] search_path: 라이브러리가 만드는 표(checkpoints, store)가 public이 아니라 시험용 스키마에 생긴다
    yield make_conninfo(URL, options=f"-c search_path={SCHEMA}")
    conn.execute(f"DROP SCHEMA {SCHEMA} CASCADE")
    conn.close()


@pytest.fixture
def graph_db():
    """시험용 Neo4j 드라이버와 이 실행만 쓰는 문서 id. 끝나면 그 노드만 지운다. 꺼져 있으면 건너뛴다."""
    # [왜] Neo4j 커뮤니티판은 사용자 DB가 하나라 Postgres처럼 스키마를 나눌 수 없다. 문서 id로 나눈다.
    #      로컬 그래프(name "main")의 노드는 건드리지 않는다
    # [왜] 문서 id는 저장소의 가공값 접두어 TEST로 시작한다. 실제 문서 id는 L·A로 시작하므로, 개발용 Neo4j에
    #      시험을 돌려도 아래 지우기가 실제 문서를 건드리지 못한다
    driver = connect_graph(Settings())
    try:
        driver.verify_connectivity()
    except (DriverError, Neo4jError, OSError):
        driver.close()
        neo4j_unreachable()
    doc = f"TEST{uuid4().hex[:10]}"
    yield driver, doc
    # [왜] 시험 노드는 문서 id(Unit·Law)나 이름 앞머리(Graph·Item·Requirement·Document·Agency)가 doc이다
    driver.execute_query(
        "MATCH (n) WHERE n.doc_id = $doc OR n.name STARTS WITH $doc DETACH DELETE n", {"doc": doc}
    )
    driver.close()
