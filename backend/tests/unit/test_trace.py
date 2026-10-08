"""Langfuse 트레이스 테스트 (SDD 5.11). 키 없이 돈다: Langfuse 서버에 보내지 않고 가짜 기록 객체로 확인한다.

확인하는 것:
  - 키가 없으면 트레이스를 건너뛰고 판정은 그대로 된다
  - 결과(모델·토큰·비용·재시도·프롬프트 버전)와 실패(level=ERROR)가 기록에 들어간다
  - _ask_json()이 성공·호출 실패·JSON 모양 실패 모두에서 기록을 닫는다
  - trace_id가 요청 ID로 정해져 같은 요청의 호출이 한 트레이스로 묶인다
  - OpenRouter 응답의 usage.cost를 읽는다
"""
import json
from types import SimpleNamespace

import pytest

from backend.app.observability import langfuse as tracing
from backend.app.observability.logging import request_id_var
from backend.app.services import llm


class FakeGeneration:
    """Langfuse generation 대신. update()로 받은 값과 end() 호출 여부만 모은다."""

    def __init__(self):
        self.fields = {}
        self.ended = False

    def update(self, **fields):
        self.fields.update(fields)

    def end(self):
        self.ended = True


@pytest.fixture
def no_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)


# ── 키가 없을 때 ──

def test_no_keys_skips_trace(no_keys):
    assert tracing.start_generation("marvia-judge", "{}") is None
    tracing.end_generation(None, llm.LLMResult(content="x"), "local")  # None이면 아무것도 안 한다
    with tracing.session_scope("s-1"):  # 아무 일 없이 지나간다
        pass


# ── end_generation이 적는 값 ──

def test_end_generation_records_result():
    gen = FakeGeneration()
    result = llm.LLMResult(content="{}", model="test/model", provider="TestCo", request_id="gen-1",
                           prompt_tokens=100, completion_tokens=20, attempts=2, cost=0.0012)
    tracing.end_generation(gen, result, "3", output={"verdict": "watch"})

    assert gen.ended
    assert gen.fields["model"] == "test/model"
    assert gen.fields["usage_details"] == {"input": 100, "output": 20}
    assert gen.fields["cost_details"] == {"total": 0.0012}
    assert gen.fields["output"] == {"verdict": "watch"}
    meta = gen.fields["metadata"]
    assert meta["prompt_version"] == "3" and meta["retry_count"] == 1 and meta["provider"] == "TestCo"
    assert "level" not in gen.fields


def test_end_generation_records_error_without_result():
    gen = FakeGeneration()
    tracing.end_generation(gen, None, "local", error="test/model: HTTP 503")

    assert gen.ended
    assert gen.fields["level"] == "ERROR" and gen.fields["status_message"] == "test/model: HTTP 503"
    assert "model" not in gen.fields and "cost_details" not in gen.fields


def test_end_generation_never_raises():
    """기록이 실패해도 판정은 계속 가야 한다."""

    class Broken(FakeGeneration):
        def update(self, **fields):
            raise RuntimeError("langfuse down")

    tracing.end_generation(Broken(), None, "local", error="x")


# ── _ask_json이 기록을 여닫는지 ──

@pytest.fixture
def recorded(monkeypatch, no_keys):
    """llm.py가 부르는 start/end를 가짜로 바꿔 무엇이 넘어갔는지 모은다."""
    calls = {"start": [], "end": []}
    gen = FakeGeneration()

    def fake_start(name, input, prompt=None):
        calls["start"].append((name, input))
        return gen

    def fake_end(generation, result, prompt_version, output=None, error=None):
        calls["end"].append({"generation": generation, "result": result, "prompt_version": prompt_version,
                             "output": output, "error": error})

    monkeypatch.setattr(llm, "start_generation", fake_start)
    monkeypatch.setattr(llm, "end_generation", fake_end)
    return calls


def _fake_chat(monkeypatch, content=None, error=None):
    def fake_chat(messages, **kwargs):
        if error:
            raise error
        return llm.LLMResult(content=content, model="test/model")

    monkeypatch.setattr(llm, "chat", fake_chat)


def test_ask_json_traces_success(monkeypatch, recorded):
    _fake_chat(monkeypatch, json.dumps({"in_scope": True, "answer": "네"}))
    llm._ask_json(llm.FOLLOW_UP_PROMPT, '{"question": "q"}', "follow_up",
                  llm.FOLLOW_UP_SCHEMA, llm.FollowUpOutput, None)

    assert recorded["start"] == [(llm.FOLLOW_UP_PROMPT, '{"question": "q"}')]  # 입력은 코드가 모은 자료만
    end = recorded["end"][0]
    assert end["output"] == {"in_scope": True, "answer": "네"} and end["error"] is None
    assert end["prompt_version"] == "local"


def test_ask_json_traces_call_failure(monkeypatch, recorded):
    _fake_chat(monkeypatch, error=llm.LLMError("test/model: HTTP 503", code=503))
    with pytest.raises(llm.LLMError):
        llm._ask_json(llm.FOLLOW_UP_PROMPT, "{}", "follow_up", llm.FOLLOW_UP_SCHEMA, llm.FollowUpOutput, None)

    end = recorded["end"][0]
    assert end["result"] is None and "503" in end["error"]


def test_ask_json_traces_bad_shape(monkeypatch, recorded):
    _fake_chat(monkeypatch, '{"answer": 1}')
    with pytest.raises(llm.LLMError):
        llm._ask_json(llm.FOLLOW_UP_PROMPT, "{}", "follow_up", llm.FOLLOW_UP_SCHEMA, llm.FollowUpOutput, None)

    end = recorded["end"][0]
    assert end["result"].model == "test/model" and "모양이 다름" in end["error"]
    assert end["output"] == '{"answer": 1}'  # 틀린 답도 원문을 남겨야 왜 틀렸는지 본다


# ── trace_id를 요청 ID로 ──

def test_same_request_id_gives_same_trace(monkeypatch):
    langfuse_sdk = pytest.importorskip("langfuse")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    started = []

    class FakeClient:
        create_trace_id = staticmethod(langfuse_sdk.Langfuse.create_trace_id)  # 실제 ID 규칙 그대로

        def start_observation(self, **kwargs):
            started.append(kwargs)
            return FakeGeneration()

    monkeypatch.setattr(langfuse_sdk, "get_client", lambda: FakeClient())
    token = request_id_var.set("req-abc123")
    try:
        tracing.start_generation("marvia-pick-vessel", "{}")
        tracing.start_generation("marvia-judge", "{}")
    finally:
        request_id_var.reset(token)

    first, second = started[0]["trace_context"]["trace_id"], started[1]["trace_context"]["trace_id"]
    assert first == second and len(first) == 32
    assert started[0]["metadata"] == {"request_id": "req-abc123"}


def test_generation_links_langfuse_prompt(monkeypatch):
    """Langfuse에서 가져온 프롬프트면 generation에 연결한다. 그래야 프롬프트 화면에서 어느 호출이 어느 버전을 썼는지 보인다 (가이드 9-2)."""
    import langfuse as langfuse_sdk

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    started = []

    class FakeClient:
        create_trace_id = staticmethod(langfuse_sdk.Langfuse.create_trace_id)

        def start_observation(self, **kwargs):
            started.append(kwargs)
            return FakeGeneration()

    monkeypatch.setattr(langfuse_sdk, "get_client", lambda: FakeClient())
    remote_prompt = object()  # Langfuse PromptClient 자리
    tracing.start_generation("marvia-judge", "{}", remote_prompt)
    tracing.start_generation("marvia-judge", "{}")  # 로컬 파일에서 왔으면 연결할 것이 없다

    assert started[0]["prompt"] is remote_prompt
    assert "prompt" not in started[1]


# ── OpenRouter usage.cost 읽기 ──

def test_call_once_reads_cost(monkeypatch):
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, cost=0.00042),
        model="test/model", id="gen-1",
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: resp)))
    monkeypatch.setattr(llm, "_client", lambda: client)

    result = llm._call_once({"model": "test/model", "messages": []})
    assert result.cost == 0.00042 and result.prompt_tokens == 10
