"""모든 시험이 함께 쓰는 준비물: 로컬 DB의 시험용 스키마(db, test_url). 처음엔 tests/rag에만 있었다."""

import os
from uuid import uuid4

import psycopg
import pytest
from db_required import (
    db_unreachable,
    graph_test_settings,
    neo4j_unreachable,
    real_graph_problem,
    require_test_tables,
)
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


@pytest.fixture(autouse=True)
def vessel_replay_only(monkeypatch):
    """모든 시험은 해수부·ShipFinder 재생 데이터만 쓴다. [왜] .env에 live와 키가 있어도 부르지 않는다"""
    monkeypatch.setenv("MARVIA_MOF_MODE", "replay")
    monkeypatch.setenv("MARVIA_SHIPFINDER_MODE", "replay")


@pytest.fixture(autouse=True)
def no_raw_langfuse_env(monkeypatch):
    """셸에 걸린 LANGFUSE_* 환경 변수를 지운다. [왜] 서버 시작 검사가 그 이름을 거절한다 (계획 6b)"""
    for name in [name for name in os.environ if name.startswith("LANGFUSE_")]:
        monkeypatch.delenv(name)
    # [왜] langfuse_trace.build가 이 이름을 직접 적는다. 없던 값으로 되돌려야 다른 시험에 새지 않는다
    monkeypatch.setenv("LANGFUSE_MEDIA_UPLOAD_ENABLED", "")
    monkeypatch.delenv("LANGFUSE_MEDIA_UPLOAD_ENABLED")


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
    # [왜] 표가 시험 스키마에 실제로 생겼는지 본다. 없으면 이름만 쓴 표가 public(개발 색인)으로 풀린다
    require_test_tables(conn, SCHEMA)
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
    # [왜] 문서 id는 저장소의 가공값 접두어 TEST로 시작한다. 실제 문서 id는 L·A로 시작한다. 거기에 더해 시험은
    #      개발 Neo4j가 아니라 시험용 Neo4j(neo4j-test)에만 붙는다. 같은 서버면 graph_test_settings가 실패한다
    driver = connect_graph(graph_test_settings())
    try:
        driver.verify_connectivity()
    except (DriverError, Neo4jError, OSError):
        driver.close()
        neo4j_unreachable()
    # [왜] 주소가 달라 보여도 개발 그래프가 든 서버면 멈춘다. 시험은 그 흔적을 만들 수 없다
    #      (main 그래프, TEST 아닌 Unit)
    main_graphs = driver.execute_query("MATCH (g:Graph {name: 'main'}) RETURN count(g) AS c").records[0]["c"]
    real_units = driver.execute_query(
        "MATCH (u:Unit) WHERE NOT u.doc_id STARTS WITH 'TEST' RETURN count(u) AS c"
    ).records[0]["c"]
    if problem := real_graph_problem(main_graphs, real_units):
        driver.close()
        pytest.fail(problem, pytrace=False)
    doc = f"TEST{uuid4().hex[:10]}"
    yield driver, doc
    # [왜] 시험 노드는 문서 id(Unit·Law)나 이름 앞머리(Graph·Item·Requirement·Document·Agency)가 doc이다
    driver.execute_query(
        "MATCH (n) WHERE n.doc_id = $doc OR n.name STARTS WITH $doc DETACH DELETE n", {"doc": doc}
    )
    driver.close()
