"""PDF 입력 테스트 (docs/specs/document-extract.md "PDF"). 키 없이 돈다.

PDF는 전부 테스트 안에서 만든다 (가공 번호·가공 문구만 쓴다, 실제 서류 없음).
글자 PDF는 손으로 쓴 최소 PDF, 그림 PDF는 pypdfium2로 가공 그림을 한 쪽에 넣어 만든다.
pypdfium2가 없으면 건너뛴다. 스캔 PDF 테스트는 무거운 OCR 대신 _ocr_image를 가짜로 바꾼다.
"""
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import app
from backend.app.services.chat import doc_ocr
from backend.app.services import llm

pdfium = pytest.importorskip("pypdfium2")

BL = "MRVA2026090001"  # 가공 번호
ANSWER = {"vessel": "SEA STAR호", "voyage": "0925W", "eta": "2026-10-02",
          "pol": "QINGDAO, CHINA", "pod": "부산 신항", "item": "건고추"}
client = TestClient(app)


def _text_pdf(pages: list[list[str]]) -> bytes:
    """쪽마다 줄 목록을 Helvetica 글자로 쓴 최소 PDF. 영문 줄만 쓴다 (기본 글꼴이라 한글은 못 쓴다)."""
    objs: list[bytes] = []
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")  # 3번
    for i, lines in enumerate(pages):
        stream = "BT /F1 12 Tf 14 TL 40 700 Td " + " T* ".join(f"({ln}) Tj" for ln in lines) + " ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {5 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 3 0 R >> >> >>".encode())
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream".encode())
    out = b"%PDF-1.4\n"
    offsets = []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def _image_pdf(page_count: int) -> bytes:
    """글자층 없이 가공 그림만 든 PDF (스캔 PDF 흉내)."""
    pdf = pdfium.PdfDocument.new()
    for n in range(page_count):
        page = pdf.new_page(300, 400)
        img = pdfium.PdfImage.new(pdf)
        img.set_bitmap(pdfium.PdfBitmap.from_pil(Image.new("RGB", (60, 80), (200 - n * 50, 200, 200))))
        img.set_matrix(pdfium.PdfMatrix().scale(300, 400))
        page.insert_obj(img)
        page.gen_content()
    buf = BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def _post(data: bytes, name="doc.pdf"):
    return client.post("/api/document", files={"file": (name, data, "application/octet-stream")})


def _fake_llm(monkeypatch):
    sent = []

    def fake(masked_text, **kwargs):
        sent.append(masked_text)
        return SimpleNamespace(output=llm.DocFieldsOutput(**ANSWER))

    monkeypatch.setattr(llm, "extract_doc_fields", fake)
    return sent


def _fake_ocr(monkeypatch):
    """_ocr_image를 가짜로 바꾼다. 부른 횟수와, 쪽마다 다른 줄을 돌려줘 이어 붙는 순서를 본다."""
    calls = []

    def fake(image, engine=None):
        calls.append(image.size)
        n = len(calls)
        return doc_ocr.OcrResult(lines=[f"PAGE {n} LINE"], rotation=0, runs=1, ocr_ms=5)

    monkeypatch.setattr(doc_ocr, "_ocr_image", fake)
    return calls


# ── 글자층 ──────────────────────────────────────────────────────

def test_text_layer_used_without_ocr(monkeypatch):
    calls = _fake_ocr(monkeypatch)
    pdf = _text_pdf([[f"B/L NO. {BL}", "VESSEL SEA STAR VOYAGE 0925W", "ETA 2026-10-02 PUSAN KOREA"]])
    ocr = doc_ocr.read_pdf(pdf)
    assert calls == []  # OCR을 부르지 않았다
    assert ocr.runs == 0 and ocr.rotation == 0
    assert any(BL in ln for ln in ocr.lines)
    assert doc_ocr.take_bl(ocr.lines) == BL


def test_router_text_pdf_extracts_bl(monkeypatch):
    _fake_ocr(monkeypatch)
    sent = _fake_llm(monkeypatch)
    body = _post(_text_pdf([[f"B/L NO. {BL}", "VESSEL SEA STAR VOYAGE 0925W", "ETA 2026-10-02 PUSAN KOREA"]])).json()
    assert body["fields"]["bl_no"]["value"] == BL
    assert BL not in sent[0] and "[BL]" in sent[0]  # 글자 PDF도 B/L은 LLM에 안 간다
    assert body["ocr"]["runs"] == 0


def test_pdf_detected_by_magic_not_filename(monkeypatch):
    """파일 이름이 .jpg여도 %PDF로 시작하면 PDF다."""
    _fake_llm(monkeypatch)
    body = _post(_text_pdf([[f"B/L NO. {BL}", "VESSEL SEA STAR VOYAGE 0925W", "ETA 2026-10-02"]]), name="a.jpg").json()
    assert body["fields"]["bl_no"]["value"] == BL


def test_only_first_two_pages_are_read():
    pdf = _text_pdf([["PAGE ONE " + "A" * 30], ["PAGE TWO " + "B" * 30], ["PAGE THREE " + "C" * 30]])
    text = " ".join(doc_ocr.read_pdf(pdf).lines)
    assert "PAGE ONE" in text and "PAGE TWO" in text and "PAGE THREE" not in text


# ── 스캔 PDF ────────────────────────────────────────────────────

def test_scanned_pdf_runs_ocr_per_page_and_joins_lines(monkeypatch):
    calls = _fake_ocr(monkeypatch)
    ocr = doc_ocr.read_pdf(_image_pdf(2))
    assert len(calls) == 2
    assert ocr.lines == ["PAGE 1 LINE", "PAGE 2 LINE"]  # 쪽 순서
    assert ocr.runs == 2
    assert calls[0] == (600, 800)  # 300x400pt를 배율 2로 그렸다


def test_scanned_three_pages_reads_two(monkeypatch):
    calls = _fake_ocr(monkeypatch)
    assert len(doc_ocr.read_pdf(_image_pdf(3)).lines) == 2 and len(calls) == 2


def test_tiny_text_layer_falls_back_to_ocr(monkeypatch):
    """쪽 번호 정도(40자 미만)의 글자층은 믿지 않고 OCR로 넘어간다."""
    calls = _fake_ocr(monkeypatch)
    doc_ocr.read_pdf(_text_pdf([["PAGE 1 OF 1"]]))
    assert len(calls) == 1


# ── 오류 ────────────────────────────────────────────────────────

def test_garbage_pdf_is_400_invalid_pdf(monkeypatch):
    _fake_llm(monkeypatch)
    res = _post(b"%PDF-1.4 this is not a real pdf")
    assert res.status_code == 400 and res.json()["detail"] == "invalid_pdf"


def test_zero_pages_is_invalid_pdf():
    pdf = pdfium.PdfDocument.new()
    buf = BytesIO()
    pdf.save(buf)
    with pytest.raises(doc_ocr.InvalidPdf):
        doc_ocr.read_pdf(buf.getvalue())


def test_non_pdf_non_image_still_invalid_image(monkeypatch):
    _fake_llm(monkeypatch)
    res = _post(b"plain text, not an image", name="a.txt")
    assert res.status_code == 400 and res.json()["detail"] == "invalid_image"


# ── 사진 경로는 그대로 ──────────────────────────────────────────

def test_image_path_unchanged(monkeypatch):
    pytest.importorskip("rapidocr")
    _fake_llm(monkeypatch)
    photo = Path(__file__).parents[1] / "fixtures" / "documents" / "notice_phone.jpg"
    body = _post(photo.read_bytes(), name="notice_phone.jpg").json()
    assert body["fields"]["bl_no"]["value"] == BL
    assert body["ocr"]["runs"] >= 1
