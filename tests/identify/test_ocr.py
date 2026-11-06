"""서류 사진 읽기 시험. 가짜 엔진을 써서 모델 없이 돈다 (실제 엔진은 scripts/check_ocr.py, Docker)."""

from types import SimpleNamespace

from marvia.graph.identify import build_identify_graph
from marvia.identify.ocr import photo_clues, read_image

BL_PHOTO = ("SHIPPER: 홍길동무역", "B/L No. DEMO0001", "TEL 01012345678", "MBL MOCK12345678TEST87654321")


def engine(*lines: str):
    """정해 둔 줄을 RapidOCR 결과 모양(txts)으로 돌려주는 가짜 엔진."""
    return lambda path: SimpleNamespace(txts=lines or None)


def test_read_image_joins_the_lines():
    assert read_image("bl.png", engine(*BL_PHOTO)).split("\n") == list(BL_PHOTO)


def test_photo_without_text_gives_an_empty_string():
    assert read_image("blank.png", engine()) == ""


def test_photo_clues_keep_only_cargo_numbers():
    # [왜] 상호·전화번호는 LLM 쪽으로 넘기지 않는다. 번호 덩어리만 남는다
    assert photo_clues(read_image("bl.png", engine(*BL_PHOTO))) == "DEMO0001 MOCK12345678TEST87654321"


def test_photo_clues_feed_the_same_number_reader():
    clues = photo_clues(read_image("bl.png", engine("B/L No. DEMO0001")))
    out = build_identify_graph().invoke({"text": clues})
    assert [c["token"] for c in out["cargos"]] == ["[BL1]"]
    assert out["cargos"][0]["facts"]["stage"] == "반입신고"
