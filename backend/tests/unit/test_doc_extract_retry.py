"""끊긴 LLM 답 재시도와 서류 응답의 llm_error 테스트. 키 없이 돈다: llm.chat()을 가짜로 바꾼다.

배경: 서류 판독에서 HTTP 200인데 스트림이 JSON 중간(`{"vessel":`)에서 끊기고 finish_reason이 None인 답이 왔다.
확인하는 것:
  - 끊긴 답(finish_reason 없음 + JSON 깨짐)은 같은 메시지로 한 번만 더 묻는다 (_ask_json)
  - 두 번 다 끊기면 LLMFormatError(bad_format)로 올리고, POST /api/document는 partial + llm_error를 돌려준다
  - finish_reason="error"(제공사가 생성 중 멈춤, 판정 평가)도 끊김으로 보고 같은 방식으로 한 번 더 묻는다
  - finish_reason=length(토큰 한도)와 정상 답은 추가 호출이 없다
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services import llm

DOCS = Path(__file__).parents[1] / "fixtures" / "documents"
BL = "MRVA2026090001"  # 가공 번호
ANSWER = {"vessel": "SEA STAR", "voyage": "0925W", "eta": "2026-10-02",
          "pol": "QINGDAO, CHINA", "pod": "부산 신항", "item": "건고추"}
CUT = '{"vessel":'  # 실제로 온 모양


@pytest.fixture(autouse=True)
def local_prompt(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setattr(llm, "RETRY_WAIT_SEC", 0)  # 재시도 대기를 테스트에서는 없앤다


def _fake_chat(monkeypatch, outcomes):
    """outcomes를 순서대로 돌려주는 가짜 chat. (본문, finish_reason) 쌍이다. 호출 인자를 기록한다."""
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        content, reason = outcomes[len(calls) - 1]
        return llm.LLMResult(content=content, model="test/model", finish_reason=reason)

    monkeypatch.setattr(llm, "chat", fake_chat)
    return calls


GOOD = (json.dumps(ANSWER, ensure_ascii=False), "stop")


def test_valid_first_time_does_not_retry(monkeypatch):
    calls = _fake_chat(monkeypatch, [GOOD])
    assert llm.extract_doc_fields("[BL]").output.vessel == "SEA STAR"
    assert len(calls) == 1


def test_cut_then_valid_succeeds_with_one_retry(monkeypatch):
    calls = _fake_chat(monkeypatch, [(CUT, None), GOOD])
    answer = llm.extract_doc_fields("[BL]")
    assert answer.output.vessel == "SEA STAR"
    assert len(calls) == 2
    assert calls[0]["messages"] == calls[1]["messages"]  # 같은 대화로 다시 묻는다
    assert answer.llm.attempts == 2  # Langfuse retry_count = attempts - 1 = 1


def test_error_finish_then_valid_succeeds_with_one_retry(monkeypatch):
    """제공사가 생성 중 멈춘 답(finish_reason="error", 판정 평가 실측)도 끊김으로 보고 한 번 더 묻는다."""
    calls = _fake_chat(monkeypatch, [('{\n  "verdict": "act",\n  "answer": "', "error"), GOOD])
    answer = llm.extract_doc_fields("[BL]")
    assert answer.output.vessel == "SEA STAR"
    assert len(calls) == 2
    assert calls[0]["messages"] == calls[1]["messages"]  # 형식 오류 안내 없이 같은 대화로 다시 묻는다
    assert answer.llm.attempts == 2


def test_error_finish_twice_raises_format_error(monkeypatch):
    calls = _fake_chat(monkeypatch, [(CUT, "error"), (CUT, "error")])
    with pytest.raises(llm.LLMFormatError):
        llm.extract_doc_fields("[BL]")
    assert len(calls) == 2  # 끊김 재시도는 한 번뿐이다


def test_cut_twice_raises_format_error(monkeypatch):
    calls = _fake_chat(monkeypatch, [(CUT, None), (CUT, None)])
    with pytest.raises(llm.LLMFormatError) as e:
        llm.extract_doc_fields("[BL]")
    assert e.value.kind == "bad_format"
    assert len(calls) == 2  # 세 번째는 없다


def test_length_is_not_retried(monkeypatch):
    calls = _fake_chat(monkeypatch, [(CUT, "length"), GOOD])
    with pytest.raises(llm.LLMFormatError) as e:
        llm.extract_doc_fields("[BL]")
    assert e.value.kind == "truncated"
    assert len(calls) == 1


def test_bad_shape_with_stop_is_not_retried(monkeypatch):
    """정상 종료(stop)인데 모양이 틀린 답은 프롬프트 문제라 같은 질문을 되풀이하지 않는다."""
    calls = _fake_chat(monkeypatch, [(json.dumps({"vessel": "SEA STAR"}), "stop"), GOOD])
    with pytest.raises(llm.LLMFormatError):
        llm.extract_doc_fields("[BL]")
    assert len(calls) == 1


def test_retry_call_failure_is_raised(monkeypatch):
    """다시 묻는 호출이 타임아웃 등으로 실패하면 그 LLMError가 그대로 올라간다."""
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return llm.LLMResult(content=CUT, model="test/model")
        raise llm.LLMError("timeout", kind="timeout")

    monkeypatch.setattr(llm, "chat", fake_chat)
    with pytest.raises(llm.LLMError) as e:
        llm.extract_doc_fields("[BL]")
    assert e.value.kind == "timeout" and len(calls) == 2


# ── POST /api/document ─────────────────────────────────────────

def _post():
    pytest.importorskip("rapidocr")
    client = TestClient(app)
    data = (DOCS / "notice_phone.jpg").read_bytes()
    return client.post("/api/document", files={"file": ("notice_phone.jpg", data, "application/octet-stream")}).json()


def test_endpoint_cut_twice_returns_partial_with_llm_error(monkeypatch):
    _fake_chat(monkeypatch, [(CUT, None), (CUT, None)])
    body = _post()
    assert body["status"] == "partial"
    assert body["llm_error"] == "bad_format"
    assert body["fields"]["bl_no"]["value"] == BL  # 코드가 뽑은 B/L은 그대로
    assert body["fields"]["vessel"]["value"] is None


def test_endpoint_cut_then_valid_has_no_llm_error(monkeypatch):
    _fake_chat(monkeypatch, [(CUT, None), GOOD])
    body = _post()
    assert body["status"] == "ok"
    assert body["llm_error"] is None
    assert body["fields"]["vessel"]["value"] == "SEA STAR"
