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


def test_etd_is_read_and_defaults_to_none(monkeypatch):
    """etd: 프롬프트가 Langfuse에 등록되기 전에는 LLM이 null을 내도, 칸이 없는 옛 모양이어도 읽힌다."""
    _fake_chat(monkeypatch, {**ANSWER, "etd": "2026-09-28"})
    assert llm.extract_doc_fields("[BL]").output.etd == "2026-09-28"
    _fake_chat(monkeypatch, {**ANSWER, "etd": None})
    assert llm.extract_doc_fields("[BL]").output.etd is None
    _fake_chat(monkeypatch, ANSWER)  # etd 키가 아예 없는 답
    assert llm.extract_doc_fields("[BL]").output.etd is None


def test_schema_asks_for_etd_and_repo_prompt_describes_it(monkeypatch):
    calls = _fake_chat(monkeypatch, ANSWER)
    llm.extract_doc_fields("[BL]")
    assert "etd" in calls[0]["response_format"]["json_schema"]["schema"]["required"]
    assert "etd: departure date" in calls[0]["messages"][0]["content"]  # 레포 예비 프롬프트 (Langfuse 키 없음)
