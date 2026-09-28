"""services/llm.py 재시도 테스트 (C-6). 키 없이 돈다: OpenRouter 호출(_call_once)을 가짜로 바꾼다.

확인하는 것: 503·429면 한 번 더 부르고, 400 같은 건 바로 올리고, 두 번 다 실패하면 포기한다.
모델 이름이 vertex/로 시작하면 Vertex AI로, 아니면 OpenRouter로 간다.
"""
from types import SimpleNamespace

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


# ── 어디로 보내나: "vertex/" 앞머리면 Vertex AI, 아니면 OpenRouter (09-28) ──────────

class _FakeClient:
    """create()에 들어온 인자를 기억하고, 최소 모양의 응답을 돌려주는 가짜 OpenAI 클라이언트."""

    def __init__(self):
        self.sent = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.sent = kwargs
        msg = SimpleNamespace(content="ok", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None,
                               model=kwargs["model"], id="req-1", model_extra={})


def test_vertex_prefix_goes_to_vertex_without_openrouter_options(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(llm, "_vertex_client", lambda: fake)
    monkeypatch.setattr(llm, "_client", lambda: pytest.fail("OpenRouter로 가면 안 된다"))
    result = llm._call_once({"model": "vertex/google/gemini-2.5-flash", "messages": []})
    assert fake.sent["model"] == "google/gemini-2.5-flash"  # Vertex는 앞머리 없는 이름을 받는다
    assert fake.sent["extra_body"] is None                   # provider 옵션은 OpenRouter 전용
    assert result.content == "ok"


def test_other_models_still_go_to_openrouter(monkeypatch):
    """vertex/를 안 쓰면 이전과 똑같이 OpenRouter로, 같은 옵션으로 간다."""
    fake = _FakeClient()
    monkeypatch.setattr(llm, "_client", lambda: fake)
    monkeypatch.setattr(llm, "_vertex_client", lambda: pytest.fail("Vertex로 가면 안 된다"))
    llm._call_once({"model": "openai/gpt-4o-mini", "messages": []})
    assert fake.sent["model"] == "openai/gpt-4o-mini"
    assert fake.sent["extra_body"] == {"provider": {"require_parameters": True}}


def test_vertex_without_login_is_llm_error(monkeypatch):
    """ADC 로그인 정보가 없으면 LLMError. OpenRouter 키가 없을 때와 같이 라우터가 partial로 받는다 (09-23 결정)."""
    import google.auth
    import google.auth.exceptions

    def no_adc(**_):
        raise google.auth.exceptions.DefaultCredentialsError("no adc")

    monkeypatch.setattr(llm, "_vertex_creds", None)
    monkeypatch.setattr(google.auth, "default", no_adc)
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}], model="vertex/google/gemini-2.5-flash")
