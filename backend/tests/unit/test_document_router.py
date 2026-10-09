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
from backend.app.services.chat import doc_ocr
from backend.app.services import llm

pytest.importorskip("rapidocr")

DOCS = Path(__file__).parents[1] / "fixtures" / "documents"
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


def test_conditions_and_contact_are_returned_and_checked(monkeypatch):
    """결정 6: 조건·연락처 칸을 돌려준다. 서류에 없는 근거 글은 not_in_text, 서류 종류는 B/L·A/N 이름으로."""
    _fake_extract(monkeypatch, {**ANSWER, "doc_kind": "arrival_notice", "freight_term": "collect",
                                "freight_term_text": "FREIGHT COLLECT", "contact_phone": "010-1234-5678"})
    body = _post().json()
    assert body["doc_kind"] == "A/N"
    assert body["fields"]["freight_term"] == {"value": "collect", "checks": ["not_in_text"]}  # 가공 통지서에 그 글이 없다
    assert body["fields"]["contact_phone"] == {"value": None, "checks": ["format"]}            # 휴대폰은 돌려주지 않는다
    assert body["fields"]["incoterm"] == {"value": None, "checks": []}                         # 없으면 검사 안 함
    assert body["needs_review"] is True


def test_old_shape_answer_keeps_needs_review_false(monkeypatch):
    """조건 칸이 비면 확인 필요를 올리지 않는다. 6칸만 있던 답도 그대로 통과한다."""
    _fake_extract(monkeypatch)
    body = _post().json()
    assert body["needs_review"] is False and body["doc_kind"] is None
    assert set(body["fields"]) >= {"original_bl", "to_order_bank", "freight_term", "incoterm",
                                   "contact_company", "contact_role", "contact_phone"}


def test_etd_same_day_is_returned_and_missing_etd_is_not_flagged(monkeypatch):
    """etd: 서류에 있는 날짜면 그대로 돌려주고, null이어도(Langfuse 프롬프트에 아직 없을 때) 확인 필요를 올리지 않는다."""
    _fake_extract(monkeypatch, {**ANSWER, "etd": "2026-10-02"})  # 가공 통지서에 있는 날짜(입항일과 같은 날)
    body = _post().json()
    assert body["fields"]["etd"] == {"value": "2026-10-02", "checks": []}
    assert body["needs_review"] is False
    _fake_extract(monkeypatch, {**ANSWER, "etd": None})
    body = _post().json()
    assert body["fields"]["etd"] == {"value": None, "checks": []}
    assert body["needs_review"] is False


def test_invented_etd_needs_review(monkeypatch):
    """프롬프트에 etd가 없는 모델이 날짜를 지어내도(strict 스키마가 칸을 요구한다) 서류에 없으면 걸린다."""
    _fake_extract(monkeypatch, {**ANSWER, "etd": "2026-09-20"})
    body = _post().json()
    assert body["fields"]["etd"]["checks"] == ["not_in_text"]
    assert body["needs_review"] is True


# ---- POST /api/document/bl: B/L만 찾기 ----

def _post_bl(name="notice_phone.jpg", content=None):
    data = content if content is not None else (DOCS / name).read_bytes()
    return client.post("/api/document/bl", files={"file": (name, data, "application/octet-stream")})


def test_bl_mode_returns_code_bl_without_calling_llm(monkeypatch):
    """채팅 첨부는 B/L(과 MRN)만 코드로 뽑는다. LLM 판독은 부르지 않는다."""
    def boom(*a, **k):
        raise AssertionError("LLM must not be called in bl mode")
    monkeypatch.setattr(llm, "extract_doc_fields", boom)
    res = _post_bl()
    assert res.status_code == 200
    body = res.json()
    assert body["bl_no"] == BL
    assert set(body) == {"bl_no", "mrn", "ocr", "trace_id"}  # LLM 칸이 없다
    assert body["ocr"]["rotation"] == 0


def test_bl_mode_rotated_photo(monkeypatch):
    monkeypatch.setattr(llm, "extract_doc_fields", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no llm")))
    assert _post_bl("notice_rot90.png").json()["bl_no"] == BL


def test_bl_mode_bad_inputs_are_400(monkeypatch):
    res = _post_bl("x.jpg", b"not an image")
    assert res.status_code == 400 and res.json()["detail"] == "invalid_image"
    monkeypatch.setattr(document_router, "MAX_BYTES", 1000)
    res = _post_bl()
    assert res.status_code == 400 and res.json()["detail"] == "too_large"


def _white_png(side):
    """흰 바탕 정사각형 PNG 바이트. 용량은 작고 픽셀은 많다 (압축 폭탄 모양)."""
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("L", (side, side), 255).save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.parametrize("path", ["/api/document", "/api/document/bl"])
def test_decompression_bomb_is_400_not_500(monkeypatch, path):
    """PIL 한도의 2배를 넘는 그림(14000x14000, 약 200KB)은 500이 아니라 해상도 초과 400이다 (5번)."""
    _fake_extract(monkeypatch)
    res = client.post(path, files={"file": ("bomb.png", _white_png(14000), "image/png")})
    assert res.status_code == 400 and res.json()["detail"] == document_router.IMAGE_TOO_LARGE_MESSAGE


@pytest.mark.parametrize("path", ["/api/document", "/api/document/bl"])
def test_too_many_pixels_is_400_before_ocr(monkeypatch, path):
    """폭탄 한도 밑이라도 MAX_IMAGE_PIXELS를 넘으면 OCR 전에 400이다 (14번). OCR이 불리면 실패한다."""
    _fake_extract(monkeypatch)
    monkeypatch.setattr(doc_ocr, "_ocr_image", lambda *a, **k: (_ for _ in ()).throw(AssertionError("OCR must not run")))
    res = client.post(path, files={"file": ("big.png", _white_png(10000), "image/png")})
    assert res.status_code == 400 and res.json()["detail"] == document_router.IMAGE_TOO_LARGE_MESSAGE


def test_pixel_limit_boundary_is_inclusive(monkeypatch):
    """상한과 같은 픽셀 수는 통과하고, 한 픽셀 더 많으면 막는다."""
    data = _white_png(100)
    monkeypatch.setattr(doc_ocr, "_ocr_image", lambda image, engine=None: doc_ocr.OcrResult(lines=[], rotation=0, runs=1, ocr_ms=0))
    monkeypatch.setattr(doc_ocr, "MAX_IMAGE_PIXELS", 100 * 100)
    assert doc_ocr.read_lines(data).runs == 1
    monkeypatch.setattr(doc_ocr, "MAX_IMAGE_PIXELS", 100 * 100 - 1)
    with pytest.raises(doc_ocr.ImageTooLarge):
        doc_ocr.read_lines(data)
