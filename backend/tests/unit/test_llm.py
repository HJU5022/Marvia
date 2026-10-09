"""services/llm.py 재시도 테스트 (C-6). 키 없이 돈다: OpenRouter 호출(_call_once)을 가짜로 바꾼다.

확인하는 것: 500·503·429면 한 번 더 부르고, 400 같은 건 바로 올리고, 두 번 다 실패하면 포기한다.
모델 이름이 vertex/로 시작하면 Vertex AI로, 아니면 OpenRouter로 간다.
"""
from types import SimpleNamespace

import pytest

from backend.app.services import llm


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    # 재시도 대기(2초)를 테스트에서는 없앤다
    monkeypatch.setattr(llm, "RETRY_WAIT_SEC", 0)
    monkeypatch.setenv("LLM_MODEL", "test/model")


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


def test_retries_once_on_500_then_succeeds(monkeypatch):
    """Vertex는 과부하를 500으로 준다 (평가 3.8 Flash B09). 503과 같이 한 번 더 부른다."""
    calls = _fake(monkeypatch, [llm.LLMError("overloaded", code=500), llm.LLMResult(content="ok")])
    result = llm.chat([{"role": "user", "content": "hi"}])
    assert result.content == "ok" and result.attempts == 2
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
    """키나 모델이 없으면 서버가 500을 내지 않고 LLMError로 올린다. 라우터가 partial로 받는다."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}])

    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}])


# ── 어디로 보내나: "vertex/" 앞머리면 Vertex AI, 아니면 OpenRouter ──────────

class _FakeClient:
    """create()에 들어온 인자를 기억하고, 최소 모양의 응답을 돌려주는 가짜 OpenAI 클라이언트."""

    def __init__(self, usage=None):
        self.sent = None
        self.usage = usage  # 응답에 실을 토큰 사용량. 없으면 None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.sent = kwargs
        msg = SimpleNamespace(content="ok", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=self.usage,
                               model=kwargs["model"], id="req-1", model_extra={})


def _usage(prompt, completion, reasoning):
    """Vertex curl 응답과 같은 모양: 생각 토큰은 completion_tokens_details에 따로 온다."""
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion,
                           completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning))


def test_vertex_prefix_goes_to_vertex_without_openrouter_options(monkeypatch):
    monkeypatch.delenv("VERTEX_THINKING_BUDGET", raising=False)
    fake = _FakeClient()
    monkeypatch.setattr(llm, "_vertex_client", lambda: fake)
    monkeypatch.setattr(llm, "_client", lambda: pytest.fail("OpenRouter로 가면 안 된다"))
    result = llm._call_once({"model": "vertex/google/gemini-2.5-flash", "messages": []})
    assert fake.sent["model"] == "google/gemini-2.5-flash"  # Vertex는 앞머리 없는 이름을 받는다
    assert fake.sent["extra_body"] is None                   # provider 옵션은 OpenRouter 전용
    assert result.content == "ok"


def test_vertex_thinking_budget_is_sent_only_when_set(monkeypatch):
    """VERTEX_THINKING_BUDGET=0이면 생각을 끄는 Google 전용 칸을 붙인다 (597 → 0토큰)."""
    fake = _FakeClient()
    monkeypatch.setattr(llm, "_vertex_client", lambda: fake)
    monkeypatch.setenv("VERTEX_THINKING_BUDGET", "0")
    llm._call_once({"model": "vertex/google/gemini-2.5-flash", "messages": []})
    assert fake.sent["extra_body"] == {"extra_body": {"google": {"thinking_config": {"thinking_budget": 0}}}}


def test_thinking_budget_is_not_sent_to_openrouter(monkeypatch):
    """OpenRouter 쪽 요청은 이 값과 상관없이 그대로다."""
    fake = _FakeClient()
    monkeypatch.setattr(llm, "_client", lambda: fake)
    monkeypatch.setenv("VERTEX_THINKING_BUDGET", "0")
    llm._call_once({"model": "openai/gpt-4o-mini", "messages": []})
    assert fake.sent["extra_body"] == {"provider": {"require_parameters": True}}


def test_other_models_still_go_to_openrouter(monkeypatch):
    """vertex/를 안 쓰면 이전과 똑같이 OpenRouter로, 같은 옵션으로 간다."""
    fake = _FakeClient()
    monkeypatch.setattr(llm, "_client", lambda: fake)
    monkeypatch.setattr(llm, "_vertex_client", lambda: pytest.fail("Vertex로 가면 안 된다"))
    llm._call_once({"model": "openai/gpt-4o-mini", "messages": []})
    assert fake.sent["model"] == "openai/gpt-4o-mini"
    assert fake.sent["extra_body"] == {"provider": {"require_parameters": True}}


def test_vertex_counts_reasoning_tokens_as_output(monkeypatch):
    """Vertex는 생각 토큰을 따로 주므로 출력 토큰에 더한다. 요금은 생각 토큰도 출력으로 받는다."""
    monkeypatch.setattr(llm, "_vertex_client", lambda: _FakeClient(usage=_usage(14, 28, 191)))
    result = llm._call_once({"model": "vertex/google/gemini-2.5-flash", "messages": []})
    assert result.prompt_tokens == 14
    assert result.completion_tokens == 28 + 191


def test_openrouter_does_not_add_reasoning_tokens(monkeypatch):
    """OpenRouter는 OpenAI 방식대로 completion_tokens에 이미 포함돼 있어 더하지 않는다 (두 번 세지 않게)."""
    monkeypatch.setattr(llm, "_client", lambda: _FakeClient(usage=_usage(14, 219, 191)))
    result = llm._call_once({"model": "openai/gpt-4o-mini", "messages": []})
    assert result.completion_tokens == 219


def test_cached_tokens_are_read_from_prompt_details(monkeypatch):
    """캐시에서 읽은 입력 토큰을 prompt_tokens_details.cached_tokens에서 꺼낸다 (4,348 중 3,514)."""
    usage = SimpleNamespace(prompt_tokens=4348, completion_tokens=238, completion_tokens_details=None,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=3514))
    monkeypatch.setattr(llm, "_vertex_client", lambda: _FakeClient(usage=usage))
    result = llm._call_once({"model": "vertex/google/gemini-2.5-flash", "messages": []})
    assert (result.prompt_tokens, result.cached_tokens) == (4348, 3514)


def test_no_cache_details_means_none(monkeypatch):
    """첫 호출처럼 캐시 정보가 없으면 None. 0과 구분한다 (캐시 칸이 아예 안 온 것)."""
    monkeypatch.setattr(llm, "_vertex_client", lambda: _FakeClient(usage=_usage(14, 28, 0)))
    assert llm._call_once({"model": "vertex/google/gemini-2.5-flash", "messages": []}).cached_tokens is None


def test_vertex_without_login_is_llm_error(monkeypatch):
    """ADC 로그인 정보가 없으면 LLMError. OpenRouter 키가 없을 때와 같이 라우터가 partial로 받는다."""
    import google.auth
    import google.auth.exceptions

    def no_adc(**_):
        raise google.auth.exceptions.DefaultCredentialsError("no adc")

    monkeypatch.setattr(llm, "_vertex_creds", None)
    monkeypatch.setattr(google.auth, "default", no_adc)
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}], model="vertex/google/gemini-2.5-flash")


@pytest.mark.parametrize("status, kind", [(429, "rate_limited"), (503, "overloaded"), (500, "overloaded"),
                                          (401, "auth"), (403, "auth"), (400, "bad_request")])
def test_http_status_maps_to_failure_kind(status, kind):
    """로그에 남길 LLM 실패 종류. 해결책이 종류마다 달라서 코드 대신 이름으로 나눈다."""
    assert llm._status_kind(status) == kind


def test_missing_model_is_not_configured(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(llm.LLMError) as e:
        llm.chat([{"role": "user", "content": "hi"}])
    assert e.value.kind == "not_configured"


def test_vertex_answer_without_message_is_empty_not_crash(monkeypatch):
    """Gemini가 생각 토큰으로 한도를 다 쓰면 message 없이 finish_reason=length만 온다 (실패 훈련 judge_truncated).
    전에는 msg.tool_calls에서 AttributeError로 죽어 라우터가 못 잡고 500이 났다. 빈 답으로 받아 truncated로 가게 한다."""
    fake = _FakeClient()
    fake.chat.completions.create = lambda **kwargs: SimpleNamespace(
        choices=[SimpleNamespace(message=None, finish_reason="length")], usage=None,
        model=kwargs["model"], id="req-1", model_extra={})
    monkeypatch.setattr(llm, "_vertex_client", lambda: fake)

    result = llm._call_once({"model": "vertex/google/gemini-2.5-flash", "messages": []})

    assert result.content is None and result.tool_calls == [] and result.finish_reason == "length"
