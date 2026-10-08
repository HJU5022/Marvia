"""web_search가 Langfuse에 관측(generation)을 남기는지 가짜 클라이언트로 확인한다 (10-05).

근거: observability/langfuse.py end_web_search. 네트워크·진짜 OpenRouter 호출 없음.
"""
from types import SimpleNamespace

import pytest

from backend.app.observability import langfuse as lf
from backend.app.services import llm


class FakeObs:
    def __init__(self):
        self.updates, self.ended = [], False

    def update(self, **kw):
        self.updates.append(kw)

    def end(self):
        self.ended = True


def _resp(notes, cost=0.008):
    msg = SimpleNamespace(annotations=notes)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], model="m-1",
                           usage=SimpleNamespace(prompt_tokens=40, completion_tokens=3, cost=cost))


@pytest.fixture
def traced(monkeypatch):
    obs = FakeObs()
    started = []
    monkeypatch.setattr(llm, "start_generation", lambda name, input, prompt=None: started.append((name, input)) or obs)
    monkeypatch.setattr(llm, "_client", lambda: object())
    return obs, started


def test_records_query_results_usage_cost(monkeypatch, traced):
    obs, started = traced
    note = {"url_citation": {"url": "https://a.test/x", "title": "T1", "content": "본문은 저장 안 함"}}
    monkeypatch.setattr(llm, "_create_with_deadline", lambda *a, **k: _resp([note]))
    out = llm.web_search("부산항 혼잡 현황")
    assert out[0]["text"] == "본문은 저장 안 함"  # 반환값은 그대로
    assert started == [("web_search", "부산항 혼잡 현황")]
    u = obs.updates[0]
    assert u["output"] == [{"title": "T1", "url": "https://a.test/x"}]
    assert "본문" not in str(u)
    assert u["metadata"]["result_count"] == 1
    assert u["model"] == "m-1"
    assert u["usage_details"] == {"input": 40, "output": 3}
    assert u["cost_details"] == {"total": 0.008}
    assert obs.ended


def test_records_error(monkeypatch, traced):
    obs, _ = traced

    def boom(*a, **k):
        raise llm._DeadlineExceeded()

    monkeypatch.setattr(llm, "_create_with_deadline", boom)
    with pytest.raises(llm.LLMError):
        llm.web_search("부산항")
    assert obs.updates[0]["level"] == "ERROR" and obs.ended


def test_blocked_query_leaves_no_trace(traced):
    _, started = traced
    with pytest.raises(llm.LLMError):
        llm.web_search("")
    assert started == []


def test_no_keys_is_noop(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert lf.start_generation("web_search", "q") is None
    lf.end_web_search(None, [], None)  # 예외 없이 지나간다
