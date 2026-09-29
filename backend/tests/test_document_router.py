"""POST /api/document 테스트 (docs/specs/document-extract.md). 키 없이 돈다.

OCR은 가공 사진(fixtures/documents/)으로 실제로 돌리고, LLM(extract_doc_fields)만 가짜로 바꾼다.
rapidocr가 없으면 건너뛴다.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import document as document_router
from backend.app.services import llm

pytest.importorskip("rapidocr")

DOCS = Path(__file__).parent / "fixtures" / "documents"
BL = "MRVA2026090001"  # 가공 번호
ANSWER = {"vessel": "SEA STAR호", "voyage": "0925W", "eta": "2026-10-02",
          "pol": "QINGDAO, CHINA", "pod": "부산 신항", "item": "건고추"}

client = TestClient(app)


def _fake_extract(monkeypatch, answer=ANSWER, error=None):
    sent = []

    def fake(masked_text, **kwargs):
        sent.append(masked_text)
        if error:
            raise error
        return SimpleNamespace(output=llm.DocFieldsOutput(**answer))

    monkeypatch.setattr(llm, "extract_doc_fields", fake)
    return sent


def _post(name="notice_phone.jpg", content=None):
    data = content if content is not None else (DOCS / name).read_bytes()
    return client.post("/api/document", files={"file": (name, data, "application/octet-stream")})


def test_reads_all_seven_fields_and_hides_bl_from_llm(monkeypatch):
    sent = _fake_extract(monkeypatch)
    body = _post().json()
    assert body["status"] == "ok"
    assert body["needs_review"] is False
    assert body["fields"]["bl_no"] == {"value": BL, "checks": []}
    assert body["fields"]["vessel"]["value"] == "SEA STAR"  # "호"는 코드가 뗀다
    assert BL not in sent[0] and "[BL]" in sent[0]
    assert body["ocr"]["rotation"] == 0


def test_invented_value_needs_review(monkeypatch):
    _fake_extract(monkeypatch, {**ANSWER, "vessel": "OCEAN KING"})
    body = _post().json()
    assert body["needs_review"] is True
    assert body["fields"]["vessel"]["checks"] == ["not_in_text"]


def test_llm_failure_keeps_code_bl_as_partial(monkeypatch):
    """LLM이 실패해도 코드가 뽑은 B/L은 돌려준다 (Spec EC-05)."""
    _fake_extract(monkeypatch, error=llm.LLMError("down", code=503, kind="overloaded"))
    body = _post().json()
    assert body["status"] == "partial"
    assert body["fields"]["bl_no"]["value"] == BL
    assert body["fields"]["vessel"] == {"value": None, "checks": ["missing"]}


def test_rotated_photo(monkeypatch):
    _fake_extract(monkeypatch)
    body = _post("notice_rot90.png").json()
    assert body["ocr"]["rotation"] == 270
    assert body["fields"]["bl_no"]["value"] == BL


def test_not_an_image_is_400(monkeypatch):
    _fake_extract(monkeypatch)
    res = _post("x.jpg", b"not an image")
    assert res.status_code == 400 and res.json()["detail"] == "invalid_image"


def test_too_large_is_400(monkeypatch):
    _fake_extract(monkeypatch)
    monkeypatch.setattr(document_router, "MAX_BYTES", 1000)
    res = _post()
    assert res.status_code == 400 and res.json()["detail"] == "too_large"
