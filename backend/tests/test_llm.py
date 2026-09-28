"""services/llm.py 재시도 테스트 (C-6). 키 없이 돈다: OpenRouter 호출(_call_once)을 가짜로 바꾼다.

확인하는 것: 503·429면 한 번 더 부르고, 400 같은 건 바로 올리고, 두 번 다 실패하면 포기한다.
"""
import pytest

from backend.app.services import llm


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    # 재시도 대기(2초)를 테스트에서는 없앤다
    monkeypatch.setattr(llm, "RETRY_WAIT_SEC", 0)
    monkeypatch.setenv("MODEL_A", "test/model")


def _fake(monkeypatch, outcomes):
    """outcomes를 순서대로 돌려주는 가짜 _call_once. 예외면 raise, 아니면 return."""
    calls = []

    def fake_call_once(kwargs):
        calls.append(kwargs)
        out = outcomes[len(calls) - 1]
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(llm, "_call_once", fake_call_once)
    return calls


def test_retries_once_on_overload_then_succeeds(monkeypatch):
    calls = _fake(monkeypatch, [llm.LLMError("overloaded", code=503), llm.LLMResult(content="ok")])
    result = llm.chat([{"role": "user", "content": "hi"}])
    assert result.content == "ok"
    assert result.attempts == 2
    assert len(calls) == 2


def test_does_not_retry_bad_request(monkeypatch):
    calls = _fake(monkeypatch, [llm.LLMError("bad schema", code=400), llm.LLMResult(content="never")])
    with pytest.raises(llm.LLMError) as e:
        llm.chat([{"role": "user", "content": "hi"}])
    assert e.value.code == 400
    assert len(calls) == 1


def test_gives_up_after_max_attempts(monkeypatch):
    calls = _fake(monkeypatch, [llm.LLMError("rate", code=429), llm.LLMError("rate", code=429)])
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == llm.MAX_ATTEMPTS == 2


def test_uses_model_a_when_model_omitted(monkeypatch):
    calls = _fake(monkeypatch, [llm.LLMResult(content="ok")])
    llm.chat([{"role": "user", "content": "hi"}])
    assert calls[0]["model"] == "test/model"


def test_missing_key_or_model_is_llm_error(monkeypatch):
    """키나 모델이 없으면 서버가 500을 내지 않고 LLMError로 올린다. 라우터가 partial로 받는다 (09-23 결정)."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}])

    monkeypatch.delenv("MODEL_A", raising=False)
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}])
