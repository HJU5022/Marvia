from marvia.config import Settings
from marvia.graph.live import agent_deps


def test_builds_without_calling():
    # [왜] 만들기만 하면 LLM·DB·Voyage를 부르지 않는다. 가짜 키와 빈 연결로도 만들어진다
    deps = agent_deps(Settings(_env_file=None, anthropic_api_key="sk-test-not-real"), None)
    assert callable(deps.plan) and callable(deps.item) and callable(deps.write) and callable(deps.rag.search)
