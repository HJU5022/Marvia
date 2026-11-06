"""그래프 시험 준비물의 경계 시험 (사고 뒤 고침). 키·Neo4j 없이 돈다."""

import pytest
from db_required import graph_test_settings

from marvia.config import Settings


def test_graph_tests_use_the_test_neo4j_not_the_dev_one():
    # [왜] 커뮤니티판은 사용자 DB가 하나라, 개발 그래프와 같은 서버에 시험을 돌리면 실제 노드가 지워질 수 있다
    #      (실제로 품목 그래프가 지워졌다). 시험은 따로 띄운 neo4j-test만 쓴다
    settings = graph_test_settings(Settings(_env_file=None))
    assert settings.neo4j_url == "bolt://localhost:7689" and settings.neo4j_url != Settings().neo4j_url


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
