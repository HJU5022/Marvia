"""그래프 시험 준비물의 경계 시험 (사고 뒤 고침). 키·Neo4j 없이 돈다."""

import pytest
from db_required import _server, graph_test_settings, real_graph_problem

from marvia.config import Settings


def test_graph_tests_connect_to_the_configured_test_url_on_another_server_than_dev():
    # [왜] 커뮤니티판은 사용자 DB가 하나라, 개발 그래프와 같은 서버에 시험을 돌리면 실제 노드가 지워질 수 있다
    #      (실제로 품목 그래프가 지워졌다). 지킬 성질은 "설정한 시험 주소로 붙고, 개발과 다른 서버"다.
    #      기본값 문자열은 검증 세션처럼 다른 주소를 줄 때 달라지므로 여기서 단언하지 않는다
    configured = Settings(_env_file=None)
    used = graph_test_settings(configured)
    assert used.neo4j_url == configured.neo4j_test_url
    assert _server(used.neo4j_url) != _server(configured.neo4j_url)


def test_the_test_url_defaults_to_the_compose_neo4j_test_only_when_the_variable_is_unset(monkeypatch):
    monkeypatch.delenv("MARVIA_NEO4J_TEST_URL", raising=False)
    monkeypatch.delenv("MARVIA_NEO4J_URL", raising=False)
    assert graph_test_settings(Settings(_env_file=None)).neo4j_url == "bolt://localhost:7689"
    monkeypatch.setenv("MARVIA_NEO4J_TEST_URL", "bolt://other:7687")
    assert graph_test_settings(Settings(_env_file=None)).neo4j_url == "bolt://other:7687"


def test_the_fixture_refuses_to_run_when_the_test_url_is_the_dev_url():
    same = Settings(_env_file=None, neo4j_test_url="bolt://localhost:7688")
    with pytest.raises(pytest.fail.Exception, match="개발 그래프"):
        graph_test_settings(same)
    # 같은 서버를 다르게 적은 것도 같은 서버다
    alias = Settings(
        _env_file=None, neo4j_url="bolt://localhost:7689", neo4j_test_url="bolt://127.0.0.1:7689"
    )
    with pytest.raises(pytest.fail.Exception, match="개발 그래프"):
        graph_test_settings(alias)


def test_a_server_holding_the_real_graph_is_refused_whatever_its_address_says():
    # [왜] 주소 글자만 비교하면 bolt://neo4j:7687이나 host.docker.internal:7688처럼 다른 이름으로 개발 서버를
    #      가리킬 때 지나간다. 붙은 서버 안에 실제 그래프의 흔적이 있으면 멈춘다 (가짜 결과로 판정만 본다)
    assert real_graph_problem(main_graphs=0, real_units=0) is None  # 빈 시험 서버, 또는 TEST 노드만 있는 서버
    assert "main" in (real_graph_problem(main_graphs=1, real_units=0) or "")
    assert "7412" in (real_graph_problem(main_graphs=0, real_units=7412) or "")
    with pytest.raises(pytest.fail.Exception, match="실제 그래프"):
        real_graph_problem(main_graphs=1, real_units=7412, fail=True)
