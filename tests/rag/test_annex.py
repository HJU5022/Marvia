"""별표 읽기·자르기 시험 (계획 3b Task 1). 키·DB·olefile 없이 돈다."""

import io
import struct
import zipfile
import zlib
from datetime import date

from marvia.rag.annex import amended_on, hwp_paragraphs, hwpx_paragraphs, split_annex

# 별표 9의 앞부분을 줄인 글 (11-06 원문, 줄 머리 모양만 남김)
LINES = [
    "■ 수입식품안전관리 특별법 시행규칙 [별표 9] <개정 2024. 6. 14.>",
    "수입식품등의 검사방법(제30조 관련)",
    "1. 삭제 <2023. 12. 1.>",
    "2. 검사의 종류 및 대상",
    "가. 서류검사 및 그 대상",
    "서류검사란 신고서류 등을 검토하는 검사를 말하며, 다음의 수입식품등을 대상으로 한다.",
    "7) 정밀검사를 받은 것 중 별표 10 제4호의 동일사 동일수입식품등의 조건을 충족하는 것",
    "12) 외국으로부터 반송된 수입식품등 중 다음의 어느 하나에 해당하는 수입식품등",
    "가) 국내에서 재가공하여 수출하려는 수입식품등",
    "다. 정밀검사 및 대상",
    "2) 별표 10에 따른 2등급 수입식품등",
    "나) 별표 10 제2호나목에 해당하는 경우에는 합산하여 5회까지 실시한다.",
    "(1) 부적합 처분을 받은 날부터 1년 이내에 재수입되는 수입식품등",
]


def _split(lines=LINES):
    return split_annex(
        lines,
        doc_id="LTEST",
        law_name="시험법 시행규칙",
        number="9",
        effective=date(2026, 9, 30),
        source_url="https://example.test",
    )


def test_split_makes_one_unit_per_leaf_with_annex_keys():
    keys = [u.unit_id.split("#")[1] for u in _split()]
    assert keys == ["별표9.2호.가목.7)", "별표9.2호.가목.12).가)", "별표9.2호.다목.2).나).(1)"]
    assert all(u.unit_id.startswith("LTEST@20260930#") and u.kind == "별표" for u in _split())


def test_unit_text_carries_its_parents_and_continuation_lines():
    unit = _split()[0]
    assert unit.text.startswith(
        "[별표 9] 수입식품등의 검사방법(제30조 관련) 2. 검사의 종류 및 대상 가. 서류검사"
    )
    assert "서류검사란 신고서류" in unit.text  # 머리 없는 줄은 앞 줄(가목)에 붙는다
    assert unit.text.endswith("동일사 동일수입식품등의 조건을 충족하는 것")
    assert unit.heading == "시험법 시행규칙 > [별표 9] 수입식품등의 검사방법(제30조 관련)"


def test_deleted_items_are_not_units_and_amendment_date_is_read():
    assert not any(".1호" in u.unit_id for u in _split())
    assert amended_on(LINES) == date(2024, 6, 14)


def _record(tag: int, payload: bytes) -> bytes:
    return struct.pack("<I", tag | (len(payload) << 20)) + payload


def test_hwp_records_give_paragraph_text_and_skip_wide_controls():
    # [왜] 표 칸 같은 확장 제어 문자(코드 11)는 16바이트를 차지한다. 건너뛰지 않으면 뒤 글이 깨진다
    control = struct.pack("<H", 11) + b"\x00" * 14
    para = _record(67, control + "가. 서류검사".encode("utf-16-le") + struct.pack("<H", 13))
    other = _record(66, b"\x01\x02\x03\x04")  # 문단 머리 레코드는 글이 아니다
    header = b"\x00" * 36 + struct.pack("<I", 1)  # 속성 첫 비트: 본문 압축
    deflate = zlib.compressobj(wbits=-15)
    section = deflate.compress(other + para) + deflate.flush()
    assert hwp_paragraphs(header, [section]) == ["가. 서류검사"]


def test_hwpx_reads_each_paragraph_and_table_cell_once():
    ns = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    xml = (
        f'<hs:sec xmlns:hs="urn:s" xmlns:hp="{ns}">'
        "<hp:p><hp:run><hp:t>1. 지정장치장</hp:t></hp:run></hp:p>"
        "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>"
        "<hp:p><hp:run><hp:t>부산세관</hp:t></hp:run></hp:p>"
        "</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
        "</hs:sec>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as box:
        box.writestr("Contents/section0.xml", xml)
    assert hwpx_paragraphs(buffer.getvalue()) == ["1. 지정장치장", "부산세관"]
