"""services/llm.py 레이트 리밋 · 큐잉 · 요청당 토큰 상한 테스트 (가이드 원칙 2 실패 경로). 키 없이 돈다.

확인하는 것:
  429면 늘려 가며 RATE_LIMIT_ATTEMPTS번까지 부르고, Retry-After를 따르되 상한을 넘기지 않는다
  그래도 429면 LLM_FALLBACK_MODEL로 한 번만 더 부른다
  LLM_MAX_CONCURRENCY만큼만 동시에 나가고, 줄에서 오래 기다리면 queue_full
  요청 안에서 쓴 토큰이 MAX_TOKENS_PER_REQUEST에 닿으면 더 부르지 않고 request_budget
"""
import threading
import time

import pytest

from backend.app.observability.logging import llm_usage_var, request_id_var
from backend.app.services import llm


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test/model")
    monkeypatch.delenv("LLM_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("LLM_MAX_CONCURRENCY", raising=False)
    monkeypatch.delenv("MAX_TOKENS_PER_REQUEST", raising=False)
    monkeypatch.setattr(llm, "RETRY_WAIT_SEC", 0.01)
    monkeypatch.setattr(llm.quota, "add", lambda tokens: None)  # 하루 한도 DB는 건드리지 않는다
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", lambda sec: sleeps.append(sec))
    return sleeps


def _fake(monkeypatch, outcomes):
    calls = []

    def fake_call_once(kwargs):
        calls.append(kwargs)
        out = outcomes[len(calls) - 1]
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(llm, "_call_once", fake_call_once)
    return calls


def test_429_waits_longer_each_time_then_succeeds(monkeypatch, setup):
    calls = _fake(monkeypatch, [llm.LLMError("rate", code=429), llm.LLMError("rate", code=429), llm.LLMResult(content="ok")])
    result = llm.chat([{"role": "user", "content": "hi"}])
    assert result.content == "ok" and result.attempts == 3
    assert len(calls) == llm.RATE_LIMIT_ATTEMPTS == 3
    assert setup == [0.01, 0.02]  # 두 배씩 늘린다


def test_429_follows_retry_after_but_caps_it(monkeypatch, setup):
    _fake(monkeypatch, [llm.LLMError("rate", code=429, retry_after=3), llm.LLMError("rate", code=429, retry_after=60),
                        llm.LLMResult(content="ok")])
    llm.chat([{"role": "user", "content": "hi"}])
    assert setup == [3, llm.RATE_LIMIT_MAX_WAIT_SEC]  # 60초는 상한으로 자른다


def test_429_falls_back_to_other_model_once(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "other/model")
    calls = _fake(monkeypatch, [llm.LLMError("rate", code=429)] * 3 + [llm.LLMResult(content="ok", model="other/model")])
    result = llm.chat([{"role": "user", "content": "hi"}])
    assert result.content == "ok"
    assert [c["model"] for c in calls] == ["test/model"] * 3 + ["other/model"]


def test_429_on_fallback_model_gives_up(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "other/model")
    calls = _fake(monkeypatch, [llm.LLMError("rate", code=429)] * 4)
    with pytest.raises(llm.LLMError) as e:
        llm.chat([{"role": "user", "content": "hi"}])
    assert e.value.code == 429 and len(calls) == 4  # 대체 모델은 한 번만


def test_no_fallback_for_overload(monkeypatch):
    # 대체 모델은 레이트 리밋에만 쓴다. 과부하(503)는 원래대로 MAX_ATTEMPTS번에서 멈춘다
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "other/model")
    calls = _fake(monkeypatch, [llm.LLMError("busy", code=503)] * 2)
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}])
    assert [c["model"] for c in calls] == ["test/model"] * 2


def test_queue_limits_concurrent_calls(monkeypatch):
    monkeypatch.setenv("LLM_MAX_CONCURRENCY", "2")
    running, peak, lock = [0], [0], threading.Lock()

    def slow_call(kwargs):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.perf_counter()  # 아래 대기 동안 다른 스레드가 줄에 선다
        threading.Event().wait(0.05)
        with lock:
            running[0] -= 1
        return llm.LLMResult(content="ok")

    monkeypatch.setattr(llm, "_call_once", slow_call)
    threads = [threading.Thread(target=llm.chat, args=([{"role": "user", "content": "hi"}],)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 2


def test_queue_full_when_waiting_too_long(monkeypatch):
    monkeypatch.setenv("LLM_MAX_CONCURRENCY", "1")
    monkeypatch.setattr(llm, "QUEUE_WAIT_SEC", 0.01)
    queue = llm._llm_queue()
    queue.acquire()  # 자리를 미리 다 차지한다
    try:
        with pytest.raises(llm.LLMError) as e:
            llm.chat([{"role": "user", "content": "hi"}])
        assert e.value.kind == "queue_full"
    finally:
        queue.release()


def _in_request():
    """미들웨어처럼 요청 하나의 사용량 dict와 request_id를 세운다."""
    return request_id_var.set("req-1"), llm_usage_var.set({})


def test_request_token_cap_blocks_next_call(monkeypatch):
    monkeypatch.setenv("MAX_TOKENS_PER_REQUEST", "100")
    calls = _fake(monkeypatch, [llm.LLMResult(content="a", prompt_tokens=80, completion_tokens=30), llm.LLMResult(content="b")])
    rid, usage = _in_request()
    try:
        llm.chat([{"role": "user", "content": "hi"}])  # 110개를 써서 상한을 넘김
        with pytest.raises(llm.LLMError) as e:
            llm.chat([{"role": "user", "content": "again"}])
        assert e.value.kind == "request_budget" and not e.value.retryable
        assert len(calls) == 1  # 두 번째는 부르지도 않는다
    finally:
        request_id_var.reset(rid)
        llm_usage_var.reset(usage)


def test_request_token_cap_ignored_outside_request(monkeypatch):
    # 스크립트·평가 실행기는 요청 밖이라 상한을 세지 않는다 (모든 호출이 기본 dict 하나를 같이 쓰므로)
    monkeypatch.setenv("MAX_TOKENS_PER_REQUEST", "10")
    calls = _fake(monkeypatch, [llm.LLMResult(content="a", prompt_tokens=50)] * 3)
    for _ in range(3):
        llm.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 3


def test_no_cap_when_unset(monkeypatch):
    calls = _fake(monkeypatch, [llm.LLMResult(content="a", prompt_tokens=10_000)] * 2)
    rid, usage = _in_request()
    try:
        llm.chat([{"role": "user", "content": "hi"}])
        llm.chat([{"role": "user", "content": "hi"}])
        assert len(calls) == 2
    finally:
        request_id_var.reset(rid)
        llm_usage_var.reset(usage)
