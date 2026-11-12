"""DB에 닿지 못했을 때 건너뛸지 실패할지 정한다. tests/conftest.py의 DB 준비물이 쓴다."""

import os
from urllib.parse import urlparse

import pytest

from marvia.config import Settings


def db_unreachable():
    """DB에 닿지 못했을 때: 로컬은 건너뛰고, MARVIA_REQUIRE_DB=1(CI)이면 실패한다."""
    # [왜] CI에서 Postgres가 안 떠도 DB 시험이 조용히 건너뛰어져 초록불이 되는 일을 막는다
    msg = "로컬 Postgres가 꺼져 있음 (docker compose up -d db)"
    if os.environ.get("MARVIA_REQUIRE_DB") == "1":
        pytest.fail(msg)
    pytest.skip(msg)


def require_test_tables(conn, schema: str) -> None:
    """시험 스키마에 색인 표(corpus_units)가 없으면 실패한다. DB 준비물이 마이그레이션 뒤에 부른다."""
    # [왜] 표가 없는 시험 스키마로 시험이 돌면 이름만 쓴 corpus_units가 public(개발 색인)으로 풀려
    #      시험 줄이 개발 색인에 들어간다 (11-13: migrations/ 없는 나무에서 돌린 시험). 건너뛰지 않는다
    found = conn.execute("SELECT to_regclass(%s)", (f"{schema}.corpus_units",)).fetchone()[0]
    if found is None:
        pytest.fail(
            f"시험 스키마 {schema}에 corpus_units 표가 없다. 마이그레이션이 돌지 않았다 "
            "(migrations/ 폴더까지 든 나무에서 시험을 돌린다)",
            pytrace=False,
        )


def neo4j_unreachable():
    """Neo4j에 닿지 못했을 때: 로컬은 건너뛰고, MARVIA_REQUIRE_NEO4J=1(CI)이면 실패한다."""
    # [왜] 그래프 시험이 CI와 검증 Docker에서 조용히 건너뛰어지는 일을 막는다 (계획 3b 사전 부검 F8)
    msg = "로컬 Neo4j가 꺼져 있음 (docker compose up -d neo4j)"
    if os.environ.get("MARVIA_REQUIRE_NEO4J") == "1":
        pytest.fail(msg)
    pytest.skip(msg)


def _server(url: str) -> tuple[str, int]:
    """bolt 주소의 (호스트, 포트). localhost와 127.0.0.1은 같은 서버로 본다."""
    parsed = urlparse(url)
    host = "127.0.0.1" if parsed.hostname == "localhost" else (parsed.hostname or "")
    return host, parsed.port or 7687


def graph_test_settings(settings: Settings | None = None) -> Settings:
    """그래프 시험이 붙을 설정: 개발 Neo4j가 아니라 시험용 Neo4j(MARVIA_NEO4J_TEST_URL)다."""
    # [왜] 커뮤니티판은 사용자 DB가 하나라, 개발 그래프와 같은 서버에 시험을 돌리면 시험이 실제 노드를 지울 수
    #      있다(품목 그래프가 지워진 사고). 두 주소가 같으면 건너뛰지 않고 실패한다
    settings = settings or Settings()
    if _server(settings.neo4j_test_url) == _server(settings.neo4j_url):
        pytest.fail(
            "MARVIA_NEO4J_TEST_URL이 개발 그래프(MARVIA_NEO4J_URL)와 같은 서버다. "
            "시험용 Neo4j를 따로 띄워라 (docker compose up -d neo4j-test)",
            pytrace=False,
        )
    return settings.model_copy(update={"neo4j_url": settings.neo4j_test_url})


def real_graph_problem(main_graphs: int, real_units: int, fail: bool = False) -> str | None:
    """붙은 서버에 실제 그래프의 흔적이 있으면 그 까닭 글을 돌려준다(fail이면 pytest.fail). 없으면 None."""
    # [왜] 주소 글자 비교는 다른 이름으로 개발 서버를 가리키면 지나간다
    #      (bolt://neo4j:7687, host.docker.internal:7688). 그래서 서버 안을 본다:
    #      이름이 main인 Graph 노드나 doc_id가 TEST로 시작하지 않는 Unit은 시험이 만들 수
    #      없으니 실제 그래프의 것이다
    reasons = []
    if main_graphs:
        reasons.append(f"Graph 'main' 노드 {main_graphs}개")
    if real_units:
        reasons.append(f"TEST가 아닌 Unit {real_units}개")
    if not reasons:
        return None
    message = (
        f"시험용 Neo4j에 실제 그래프가 들어 있다 ({', '.join(reasons)}). "
        "개발 그래프 서버에는 시험을 돌리지 않는다"
    )
    if fail:
        pytest.fail(message, pytrace=False)
    return message
