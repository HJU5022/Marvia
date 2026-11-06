import pytest

from marvia.config import Settings
from marvia.graph.live import agent_deps, live_memory


def test_builds_without_calling():
    # [왜] 만들기만 하면 LLM·DB·Voyage를 부르지 않는다. 가짜 키와 빈 연결로도 만들어진다
    deps = agent_deps(Settings(_env_file=None, anthropic_api_key="sk-test-not-real"), None)
    assert callable(deps.plan) and callable(deps.item) and callable(deps.write) and callable(deps.rag.search)


@pytest.mark.parametrize("secret", ["", "short-typed-secret"])
def test_memory_refuses_a_missing_or_bad_key_before_connecting(secret):
    # [왜] 없는 주소라도 연결 오류가 아니라 키 오류가 먼저 난다. 메모리 대화 기록으로 바꿔 쓰지 않는다
    with pytest.raises(ValueError, match="MARVIA_DATA_KEY"):
        with live_memory("postgresql://nowhere.invalid/x", secret):
            pass
