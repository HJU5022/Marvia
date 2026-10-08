"""llm._ask_json 도구 라운드의 response_format 처리와 _call_once의 전체 시간 상한 테스트. 키 없이 돈다.

- 도구가 열린 라운드에는 response_format을 보내지 않는다 (deepseek-v4-flash는 둘이 같이 오면 도구를 안 부른다)
- 도구 없이 낸 본문이 JSON이면(코드 울타리 포함) 두 번째 호출 없이 쓴다. 못 읽으면 response_format + tool_choice=none으로 딱 한 번 더 묻는다
- 도구가 없는 호출은 예전과 같다: response_format을 붙인 한 번의 호출
- _call_once는 TIMEOUT_SEC이 지나면 LLMError(kind=timeout)를 낸다 (OpenRouter가 연결을 살려 두면 httpx 읽기 상한이 안 걸린다)
"""
import json
import time
from types import SimpleNamespace

import pytest

from backend.app.services import llm

ANSWER = {"in_scope": True, "answer": "현재 속력은 12.3노트입니다."}
TOOLS = [{"type": "function", "function": {"name": "get_live_position", "description": "", "parameters": {}}}]


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)


def _ask(tools=TOOLS, run_tool=lambda name, args: {"sog": 12.3}):
    return llm._ask_json("marvia-follow-up", "질문", "follow_up", llm.FOLLOW_UP_SCHEMA, llm.FollowUpOutput,
                         "test/model", tools=tools, run_tool=run_tool)


def _script(monkeypatch, replies):
    """chat() 호출 인자를 기록하고 replies를 순서대로 돌려준다."""
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append(kwargs)
        return replies[len(calls) - 1]

    monkeypatch.setattr(llm, "chat", fake_chat)
    return calls


def _text(content):
    return llm.LLMResult(content=content, model="test/model")


def test_tool_round_sends_no_response_format(monkeypatch):
    call = {"id": "c1", "name": "get_live_position", "arguments": "{}"}
    calls = _script(monkeypatch, [llm.LLMResult(content=None, tool_calls=[call], model="m"),
                                  _text(json.dumps(ANSWER, ensure_ascii=False))])
    answer = _ask()
    assert "response_format" not in calls[0] and calls[0]["tools"] == TOOLS
    assert len(calls) == 2 and "response_format" not in calls[1]  # 두 번째도 도구를 더 부를 수 있는 라운드
    assert answer.output.answer == ANSWER["answer"]
    assert [c["name"] for c in answer.tool_calls] == ["get_live_position"]


def test_content_json_is_parsed_without_second_call(monkeypatch):
    calls = _script(monkeypatch, [_text(f"  {json.dumps(ANSWER, ensure_ascii=False)}\n")])
    assert _ask().output.in_scope is True
    assert len(calls) == 1


def test_fenced_json_is_parsed(monkeypatch):
    calls = _script(monkeypatch, [_text("```json\n" + json.dumps(ANSWER, ensure_ascii=False) + "\n```")])
    assert _ask().output.answer == ANSWER["answer"]
    assert len(calls) == 1


def test_unparseable_content_makes_exactly_one_extra_call(monkeypatch):
    calls = _script(monkeypatch, [_text("속력은 12.3노트입니다."), _text(json.dumps(ANSWER, ensure_ascii=False))])
    assert _ask().output.answer == ANSWER["answer"]
    assert len(calls) == 2
    assert "response_format" not in calls[0]
    assert calls[1]["response_format"]["json_schema"]["strict"] is True
    assert calls[1]["tool_choice"] == "none" and calls[1]["tools"] == TOOLS


def test_extra_call_that_is_still_bad_raises_format_error(monkeypatch):
    # 실제 제공사 답은 정상 종료면 finish_reason="stop"을 단다. 없으면(None) 끊긴 답으로 보고 한 번 더 묻는다 (test_doc_extract_retry.py)
    stopped = lambda content: llm.LLMResult(content=content, model="test/model", finish_reason="stop")  # noqa: E731
    _script(monkeypatch, [stopped("아님"), stopped("여전히 아님")])
    with pytest.raises(llm.LLMFormatError):
        _ask()


def test_no_tools_call_is_unchanged(monkeypatch):
    calls = _script(monkeypatch, [_text(json.dumps(ANSWER, ensure_ascii=False))])
    _ask(tools=None, run_tool=None)
    assert len(calls) == 1
    assert calls[0]["response_format"]["json_schema"]["name"] == "follow_up"
    assert calls[0]["tools"] is None and calls[0]["tool_choice"] is None


# ── 전체 시간 상한 ──

def test_call_once_times_out_even_if_connection_stays_alive(monkeypatch):
    """create()가 안 끝나면(연결은 살아 있는 상태) TIMEOUT_SEC 뒤 LLMError(kind=timeout), 재시도 대상 아님."""
    def slow_create(**kwargs):
        time.sleep(2)

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=slow_create)))
    monkeypatch.setattr(llm, "_client", lambda: fake)
    monkeypatch.setattr(llm, "TIMEOUT_SEC", 0.1)
    start = time.monotonic()
    with pytest.raises(llm.LLMError) as info:
        llm._call_once({"model": "openai/gpt-4o-mini", "messages": []})
    assert time.monotonic() - start < 1.0
    assert info.value.kind == "timeout" and not info.value.retryable
    assert 100 <= info.value.latency_ms < 1000


def test_call_once_still_reraises_sdk_errors(monkeypatch):
    def failing_create(**kwargs):
        raise ValueError("boom")

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=failing_create)))
    monkeypatch.setattr(llm, "_client", lambda: fake)
    with pytest.raises(ValueError):
        llm._call_once({"model": "openai/gpt-4o-mini", "messages": []})


def test_generation_records_usage_summed_over_tool_rounds(monkeypatch):
    """도구 고리는 chat()을 여러 번 부르는데 Langfuse에는 마지막 라운드 토큰만 남았다. 모든 라운드의 합을 남긴다."""
    call = {"id": "c1", "name": "get_live_position", "arguments": "{}"}
    _script(monkeypatch, [
        llm.LLMResult(content=None, tool_calls=[call], model="m", prompt_tokens=100, completion_tokens=10, cost=0.001,
                      cached_tokens=40, attempts=2),
        llm.LLMResult(content=json.dumps(ANSWER, ensure_ascii=False), model="m", prompt_tokens=150, completion_tokens=20,
                      cost=0.002, cached_tokens=None),
    ])
    recorded = []
    monkeypatch.setattr(llm, "start_generation", lambda *a, **k: object())
    monkeypatch.setattr(llm, "end_generation", lambda gen, result, version, **kw: recorded.append(result))
    answer = _ask()
    [result] = recorded
    assert (result.prompt_tokens, result.completion_tokens, result.cached_tokens) == (250, 30, 40)
    assert result.cost == pytest.approx(0.003) and result.attempts == 2  # 재시도는 첫 라운드의 1번뿐
    assert answer.llm.prompt_tokens == 250 and answer.output.answer == ANSWER["answer"]


def test_single_round_usage_is_unchanged(monkeypatch):
    _script(monkeypatch, [llm.LLMResult(content=json.dumps(ANSWER, ensure_ascii=False), model="m", prompt_tokens=7,
                                        completion_tokens=3, cost=None)])
    recorded = []
    monkeypatch.setattr(llm, "start_generation", lambda *a, **k: object())
    monkeypatch.setattr(llm, "end_generation", lambda gen, result, version, **kw: recorded.append(result))
    _ask()
    assert recorded[0].prompt_tokens == 7 and recorded[0].cost is None


def test_tool_call_extra_content_is_sent_back(monkeypatch):
    """Vertex 실험: Gemini 3.x는 도구 호출마다 thought_signature(extra_content)를 주고, 결과를 돌려줄 때 그대로 되돌려 받는다.
    없으면 HTTP 400. 값이 없는 제공사(OpenRouter 등)는 칸 자체를 넣지 않는다."""
    sent = []
    extra = {"google": {"thought_signature": "SIG"}}
    first = llm.LLMResult(content=None, tool_calls=[{"id": "c1", "name": "get_live_position", "arguments": "{}", "extra_content": extra},
                                                    {"id": "c2", "name": "get_live_position", "arguments": "{}"}], model="m")
    replies = [first, _text(json.dumps(ANSWER, ensure_ascii=False))]

    def fake_chat(messages, **kwargs):
        sent.append([dict(m) for m in messages])
        return replies[len(sent) - 1]

    monkeypatch.setattr(llm, "chat", fake_chat)
    _ask()
    calls = sent[1][-3]["tool_calls"]  # 두 번째 요청의 assistant 메시지
    assert calls[0]["extra_content"] == extra and "extra_content" not in calls[1]
