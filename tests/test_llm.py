import anthropic
import httpx
import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel

from marvia.config import Settings
from marvia.llm import LLMFailed, chat_model, structured
from marvia.tools.rules import load_rules


def test_builds_haiku_without_calling():
    # [왜] 객체를 만들기만 하면 인터넷 호출이 없다. 가짜 키로도 만들어진다
    llm = chat_model(Settings(_env_file=None, anthropic_api_key="sk-test-not-real"))
    assert llm.model == "claude-haiku-5-5"


def test_missing_key_stops(monkeypatch):
    monkeypatch.delenv("MARVIA_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MARVIA_ANTHROPIC_API_KEY"):
        chat_model(Settings(_env_file=None))


def test_timeout_and_retries_from_rules():
    # [왜] 시간 제한을 넘기지 않으면 ChatAnthropic은 제한 없이 기다린다. rules/agent.yaml 값이 들어갔는지 본다
    llm = chat_model(Settings(_env_file=None, anthropic_api_key="sk-test-not-real"))
    cfg = load_rules("agent")["llm"]
    assert (llm.default_request_timeout, llm.max_retries) == (cfg["timeout_s"], cfg["max_retries"])


class Answer(BaseModel):
    text: str


class Broken:
    """invoke하면 error를 내는 가짜 LLM. structured가 부르는 두 메서드만 있다."""

    def __init__(self, error: Exception):
        self.error = error

    def with_structured_output(self, schema, method):
        return self

    def invoke(self, prompt):
        raise self.error


@pytest.mark.parametrize(
    "error",
    [
        anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.test")),
        OutputParserException("모양이 다른 답"),
    ],
)
def test_structured_wraps_llm_errors(error):
    with pytest.raises(LLMFailed, match=type(error).__name__):
        structured(Broken(error), Answer)("프롬프트")


def test_status_code_is_kept_in_the_failure():
    # [왜] 429(잠시 뒤 다시)와 400(요청 모양 문제)은 다음 길이 다르다. 오류 글 없이 상태 코드만 남긴다
    request = httpx.Request("POST", "https://api.anthropic.test")
    error = anthropic.RateLimitError(
        "요청 글이 섞일 수 있는 오류 글", response=httpx.Response(429, request=request), body=None
    )
    with pytest.raises(LLMFailed, match=r"^RateLimitError\(429\)$"):
        structured(Broken(error), Answer)("프롬프트")
