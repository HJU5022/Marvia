"""llm.extract_doc_fields() 테스트 (docs/specs/document-extract.md 4단계). 키 없이 돈다: chat()을 가짜로 바꾼다."""
import json

import pytest

from backend.app.services import llm

BL = "MRVA2026090001"  # 가공 번호


@pytest.fixture(autouse=True)
def local_prompt(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)


def _fake_chat(monkeypatch, answer):
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        return llm.LLMResult(content=json.dumps(answer, ensure_ascii=False), model="test/model")

    monkeypatch.setattr(llm, "chat", fake_chat)
    return calls


ANSWER = {"vessel": "SEA STAR", "voyage": "0925W", "eta": "2026-10-02",
          "pol": "QINGDAO, CHINA", "pod": "부산 신항", "item": "건고추"}


def test_returns_six_fields(monkeypatch):
    _fake_chat(monkeypatch, ANSWER)
    out = llm.extract_doc_fields("B/L NO.\n[BL]\nSEA STAR / 0925W").output
    assert out.vessel == "SEA STAR" and out.eta == "2026-10-02"


def test_system_has_prompt_but_no_skills(monkeypatch):
    """칸 옮겨 적기에는 판정 기준(skills)이 필요 없다. 약 5천 자를 매번 넣지 않는다."""
    calls = _fake_chat(monkeypatch, ANSWER)
    llm.extract_doc_fields("[BL]")
    system = calls[0]["messages"][0]["content"]
    assert "Copy each value exactly" in system
    assert "# 파일: skills/" not in system


def test_user_content_is_the_masked_text_only(monkeypatch):
    calls = _fake_chat(monkeypatch, ANSWER)
    llm.extract_doc_fields("B/L NO.\n[BL]")
    sent = json.dumps(calls[0]["messages"], ensure_ascii=False)
    assert BL not in sent
    assert calls[0]["response_format"]["json_schema"]["name"] == "doc_extract"


def test_null_fields_are_allowed(monkeypatch):
    _fake_chat(monkeypatch, {**ANSWER, "item": None, "eta": None})
    out = llm.extract_doc_fields("[BL]").output
    assert out.item is None and out.eta is None


def test_bad_shape_is_format_error(monkeypatch):
    _fake_chat(monkeypatch, {"vessel": "SEA STAR"})  # 칸이 빠진 답
    with pytest.raises(llm.LLMFormatError):
        llm.extract_doc_fields("[BL]")
