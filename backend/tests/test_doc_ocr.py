"""services/doc_ocr.py 테스트 (docs/specs/document-extract.md). 키 없이 돈다.

규칙 함수는 OCR 없이 글자 줄로 시험한다. 끝의 OCR 테스트는 가공 서류 사진(fixtures/documents/)을 실제로 읽는다.
rapidocr가 없으면 OCR 테스트만 건너뛴다. 처음 돌릴 때 모델 파일(약 18MB)을 받는다.
"""
import datetime
from pathlib import Path

import pytest

from backend.app.services import doc_ocr

DOCS = Path(__file__).parent / "fixtures" / "documents"
BL = "MRVA2026090001"  # 가공 번호


# ── B/L 찾기 ────────────────────────────────────────────────────

def test_take_bl_after_label():
    assert doc_ocr.take_bl(["수하인", "가나다무역", "B/L NO.", BL, "선명/항차"]) == BL


def test_take_bl_before_label_on_tilted_photo():
    """기울어진 사진: 값이 이름표보다 먼저 읽혔다 (09-29 tilt3)."""
    assert doc_ocr.take_bl(["가나다무역", "수하인", BL, "B/L NO.", "SEA STAR / 0925W"]) == BL


def test_take_bl_same_line_in_sentence():
    """문장형 안내문: 이름표가 "B/L 번호"이고 값이 같은 줄에 있다 (09-29 sentence)."""
    assert doc_ocr.take_bl([f"귀사의 수입 화물(B/L 번호 {BL}, 품명 건고추 120포)이"]) == BL


def test_take_bl_needs_label():
    """이름표가 없으면 형식이 맞아도 고르지 않는다. 컨테이너 번호와 구분이 안 되기 때문이다."""
    assert doc_ocr.take_bl(["CONTAINER", "TEMU1235474", BL]) is None


def test_mask_bl_hides_number_from_llm_input():
    text = doc_ocr.mask_bl(["B/L NO.", BL, f"B/L 번호 {BL} 건"], BL)
    assert BL not in text
    assert text.count("[BL]") == 2


# ── 검사 ───────────────────────────────────────────────────────

def test_dates_in_reads_three_formats_and_ocr_zero_for_o():
    text = "02-0CT-2026 | 2026년 10월 2일 | 2026-10-02 | 2026.9.12"
    assert doc_ocr.dates_in(text) == {datetime.date(2026, 10, 2), datetime.date(2026, 9, 12)}


def test_strip_ship_suffix_only_for_latin_names():
    assert doc_ocr.strip_ship_suffix("SEA STAR호") == "SEA STAR"
    assert doc_ocr.strip_ship_suffix("한바다호") == "한바다호"
    assert doc_ocr.strip_ship_suffix(None) is None


def _fields(**over):
    base = {"bl_no": BL, "vessel": "SEA STAR", "voyage": "0925W", "eta": "2026-10-02",
            "pol": "QINGDAO, CHINA", "pod": "부산 신항", "item": "건고추"}
    return {**base, **over}


LINES = ["B/L NO.", BL, "SEA STAR / 0925W", "QINGDAO, CHINA", "부산 신항", "02-OCT-2026", "건고추"]


def test_check_fields_all_pass():
    assert all(v == [] for v in doc_ocr.check_fields(_fields(), LINES).values())


def test_check_fields_flags_invented_and_missing_values():
    checks = doc_ocr.check_fields(_fields(vessel="OCEAN KING", item=None), LINES)
    assert checks["vessel"] == ["not_in_text"]
    assert checks["item"] == ["missing"]


def test_check_fields_compares_dates_by_value():
    assert doc_ocr.check_fields(_fields(eta="2026-10-03"), LINES)["eta"] == ["not_in_text"]
    assert doc_ocr.check_fields(_fields(eta="10월 2일"), LINES)["eta"] == ["format"]


# ── 실제 OCR (가공 사진) ────────────────────────────────────────

@pytest.fixture(scope="module")
def engine():
    pytest.importorskip("rapidocr")
    return doc_ocr._get_engine()


@pytest.mark.parametrize("name, rotation", [
    ("notice_phone.jpg", 0),
    ("notice_stamp.png", 0),    # 빨간 도장을 지워야 B/L이 온전히 읽힌다 (지우기 전 MRV60001)
    ("notice_rot90.png", 270),  # 누운 사진은 270°로 돌려 읽는다 (0°로는 0/8)
])
def test_read_lines_finds_bl_on_fabricated_photos(engine, name, rotation):
    result = doc_ocr.read_lines((DOCS / name).read_bytes(), engine)
    assert result.rotation == rotation
    assert doc_ocr.take_bl(result.lines) == BL
    assert doc_ocr.dates_in("\n".join(result.lines)) == {datetime.date(2026, 10, 2)}


def test_read_lines_rejects_non_image(engine):
    from PIL import UnidentifiedImageError

    with pytest.raises(UnidentifiedImageError):
        doc_ocr.read_lines(b"not an image", engine)
