"""별표 파일(HWP 5.0, HWPX)의 글을 읽어 호·목 단위로 자른다 (설계 5.2, 계획 3b Task 1).

하지 않는 일: 내려받기와 HWP의 OLE 상자 열기(scripts/build_annex.py가 olefile로 한다), 색인.
[왜] HWP 5.0 본문(BodyText/SectionN)은 "4바이트 머리 + 내용" 레코드의 줄이고, 문단 글은 그 가운데
     PARA_TEXT 레코드다. 레코드 읽기는 표준 라이브러리만 쓴다. 그래서 런타임 의존성이 늘지 않는다.
[주의] 수입식품안전관리 특별법 시행규칙 별표 9·10(HWP)과 보세화물관리 고시 별표 1(HWPX)로만 확인했다(11-06).
       다른 별표를 더하면 줄 머리 모양(1. 가. 1) 가) (1))을 다시 본다.
"""

from __future__ import annotations

import hashlib
import io
import re
import struct
import zipfile
import zlib
from datetime import date
from xml.etree import ElementTree

from marvia.rag.models import Unit

PARA_TEXT = 67  # HWPTAG_BEGIN(16) + 51: 문단 글 레코드 (한글 문서 파일 형식 5.0)
# [왜] 이 제어 문자들은 글자 하나가 아니라 8글자(16바이트) 자리를 차지한다. 건너뛰지 않으면 글이 깨진다
WIDE_CONTROLS = frozenset({1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23})
HWPX_NS = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
SECTION = re.compile(r"Contents/section\d+\.xml")

# 줄 머리 → (깊이, 이름표 꼴). 별표는 "1." 호, "가." 목, "1)", "가)", "(1)" 순서로 내려간다
SYLLABLES = "가나다라마바사아자차카타파하"
MARKERS = [
    (1, re.compile(r"^(\d+(?:의\d+)?)\.\s"), "{}호"),
    (2, re.compile(rf"^([{SYLLABLES}])\.\s"), "{}목"),
    (3, re.compile(r"^(\d+)\)\s"), "{})"),
    (4, re.compile(rf"^([{SYLLABLES}])\)\s"), "{})"),
    (5, re.compile(r"^\((\d+)\)\s"), "({})"),
]
AMENDED = re.compile(r"<개정\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?>")


def _clean(text: str) -> str:
    """공백을 하나로 줄인다."""
    return re.sub(r"\s+", " ", text).strip()


def _para_text(raw: bytes) -> str:
    """PARA_TEXT 레코드 한 개를 글로 바꾼다. 글자는 UTF-16LE 두 바이트씩이다."""
    chars: list[str] = []
    i = 0
    while i + 1 < len(raw):
        (code,) = struct.unpack_from("<H", raw, i)
        if code in WIDE_CONTROLS:
            i += 16
            continue
        # [왜] 나머지 제어 문자(줄 바꿈 10, 문단 끝 13 등)는 한 글자 자리라 띄어쓰기로 바꾼다
        chars.append(" " if code < 32 else chr(code))
        i += 2
    return _clean("".join(chars))


def section_paragraphs(data: bytes) -> list[str]:
    """압축을 푼 BodyText 구역 하나에서 문단 글을 순서대로 모은다. 표 칸의 문단도 같은 줄에 나온다."""
    out: list[str] = []
    pos = 0
    while pos + 4 <= len(data):
        (head,) = struct.unpack_from("<I", data, pos)
        tag, size = head & 0x3FF, head >> 20  # 머리: 태그 10비트, 수준 10비트, 크기 12비트
        pos += 4
        if size == 0xFFF:  # [왜] 크기가 4095 이상이면 다음 4바이트에 진짜 크기가 있다
            (size,) = struct.unpack_from("<I", data, pos)
            pos += 4
        if tag == PARA_TEXT:
            out.append(_para_text(data[pos : pos + size]))
        pos += size
    return out


def hwp_paragraphs(file_header: bytes, sections: list[bytes]) -> list[str]:
    """HWP 5.0의 FileHeader 스트림과 BodyText/Section0.. 스트림 바이트로 문단 글을 모은다."""
    # [왜] FileHeader 36번째 바이트부터의 속성 값 첫 비트가 "본문 압축"이다. 압축은 zlib 머리 없는 deflate다
    compressed = struct.unpack_from("<I", file_header, 36)[0] & 1
    out: list[str] = []
    for data in sections:
        out += section_paragraphs(zlib.decompress(data, -15) if compressed else data)
    return [line for line in out if line]


def hwpx_paragraphs(data: bytes) -> list[str]:
    """HWPX(zip) 바이트에서 문단 글을 모은다. 표 칸 하나가 한 줄이 된다."""
    out: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as box:
        for name in sorted(n for n in box.namelist() if SECTION.fullmatch(n)):
            for p in ElementTree.fromstring(box.read(name)).iter(f"{HWPX_NS}p"):
                # [주의] 표를 품은 문단의 run에는 t 대신 tbl이 있다. run 바로 아래 t만 읽어 겹치지 않는다
                out.append(_clean("".join(t.text or "" for run in p for t in run if t.tag == f"{HWPX_NS}t")))
    return [line for line in out if line]


def amended_on(lines: list[str]) -> date | None:
    """머리 줄의 <개정 2024. 6. 14.>를 읽는다. 단위 시행일이 아니라 기록용이다."""
    for line in lines[:3]:
        if m := AMENDED.search(line):
            return date(int(m[1]), int(m[2]), int(m[3]))
    return None


def _marker(line: str) -> tuple[int, str] | None:
    """줄 머리로 (깊이, 이름표)를 정한다. 머리가 없으면 None(앞 줄에 이어 붙일 글)."""
    for depth, pattern, form in MARKERS:
        if m := pattern.match(line):
            return depth, form.format(m[1])
    return None


def split_annex(
    lines: list[str], *, doc_id: str, law_name: str, number: str, effective: date, source_url: str
) -> list[Unit]:
    """별표 글 줄을 잎 단위 Unit으로 만든다. unit_id는 {doc_id}@{시행일}#별표9.2호.가목.7) 꼴이다."""
    first = next((i for i, line in enumerate(lines) if _marker(line)), len(lines))
    # [왜] 첫 머리 줄 앞은 제목이다. "■ … [별표 9] <개정 …>"과 "<별표 1>" 같은 표시 줄은 뺀다
    title = _clean(" ".join(line for line in lines[:first] if not line.startswith(("■", "<별표"))))
    root = f"별표{number}"
    nodes: list[tuple[int, str, str]] = [(0, root, f"[별표 {number.replace('의', '의 ')}] {title}")]
    for line in lines[first:]:
        kind = _marker(line)
        if kind is None:
            depth, name, text = nodes[-1]
            nodes[-1] = (depth, name, f"{text} {line}")  # 표 칸, 설명 문단, ※ 줄은 앞 줄에 붙인다
        else:
            nodes.append((kind[0], kind[1], line))
    heading = f"{law_name} > [별표 {number.replace('의', '의 ')}] {title}"
    units: list[Unit] = []
    stack: list[tuple[int, str, str]] = []
    for i, node in enumerate(nodes):
        while stack and stack[-1][0] >= node[0]:
            stack.pop()
        stack.append(node)
        next_depth = nodes[i + 1][0] if i + 1 < len(nodes) else -1
        # [왜] "1. 삭제 <2023. 12. 1.>"처럼 지운 줄은 단위로 만들지 않는다 (lawpage와 같은 규칙)
        deleted = node[2].split(" ", 1)[-1].startswith("삭제")
        if next_depth <= node[0] and not deleted and node[0] > 0:
            text = " ".join(n[2] for n in stack)
            units.append(
                Unit(
                    unit_id=f"{doc_id}@{effective:%Y%m%d}#{'.'.join(n[1] for n in stack)}",
                    doc_id=doc_id,
                    law_name=law_name,
                    kind="별표",
                    effective=effective,
                    source_url=source_url,
                    heading=heading,
                    text=text,
                    sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )
    return units
