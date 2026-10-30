import pytest

from marvia.config import Settings
from marvia.llm import chat_model


def test_builds_haiku_without_calling():
    # [왜] 객체를 만들기만 하면 인터넷 호출이 없다. 가짜 키로도 만들어진다
    llm = chat_model(Settings(_env_file=None, anthropic_api_key="sk-test-not-real"))
    assert llm.model == "claude-haiku-5-5"


def test_missing_key_stops(monkeypatch):
    monkeypatch.delenv("MARVIA_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MARVIA_ANTHROPIC_API_KEY"):
        chat_model(Settings(_env_file=None))
