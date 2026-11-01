"""국가법령정보센터 조문 페이지(HTML)를 조·항·호·목 단위로 자른다 (설계 5.2).

하지 않는 일: 내려받기(scripts/fetch_corpus.py), 별표·부칙 읽기(계획 3).
[주의] 페이지 구조에 기댄다. 조문 하나가 <div class="lawcon"> 하나이고, 장·절 제목은 <p class="gtit">다.
줄의 종류(조·항·호·목)는 class 이름이 아니라 글 앞머리(제N조, ①, 1., 가.)로 가린다.
10-30에 관세법과 고시 4개로 확인했다(같은 unit_id 0건).
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import date

from marvia.rag.models import Unit

# 장·절 제목(1번 묶음)과 조문 블록(2번 묶음)을 페이지에 나오는 순서대로 찾는다
BLOCK = re.compile(r'<p class="gtit"[^>]*>(.*?)</p>|<div class="lawcon">(.*?)</div>', re.S)
LINE = re.compile(r"<p[^>]*>(.*?)</p>", re.S)  # 조문 블록 안의 한 줄
NOTE = re.compile(r'<span class="sfon">.*?</span>', re.S)  # <개정 2020. 12. 22.> 같은 개정 표시
LINK = re.compile(r"</?a\b[^>]*>")  # 조문 참조 링크. [왜] 공백 없이 지워야 "제241조제1항에"가 붙어 있다
TAG = re.compile(r"<[^>]+>")

ARTICLE = re.compile(r"^제(\d+)조(?:의(\d+))?\s*(?:\(([^)]*)\))?\s*(.*)$")  # 제3조의2(제목) 나머지 글
PARAGRAPH = re.compile(r"^([①-⑳])")  # 항: ①~⑳
ITEM = re.compile(r"^(\d+(?:의\d+)?)\.\s")  # 호: 1. 또는 3의2.
SUBITEM = re.compile(r"^([가나다라마바사아자차카타파하])\.\s")  # 목: 가. 나.
CHAPTER = re.compile(r"^제\d+(?:의\d+)?\s*([편장절관])")  # 제1장 총칙, 제2절 …
CHAPTER_DEPTH = {"편": 0, "장": 1, "절": 2, "관": 3}


def clean(fragment: str) -> str:
    """태그와 개정 표시를 지우고 공백을 하나로 줄인다."""
    text = NOTE.sub(" ", fragment)
    text = LINK.sub("", text)
    text = html.unescape(TAG.sub(" ", text))  # &lt; 같은 표기를 < 로 되돌린다
    return re.sub(r"\s+", " ", text).strip()


def _line_kind(line: str) -> tuple[int, str] | None:
    """줄 앞머리로 (깊이, 이름표)를 정한다. 항·호·목이 아니면 None (앞 줄에 이어 붙일 글)."""
    if m := PARAGRAPH.match(line):
        # [왜] ①은 유니코드 2460번, ②는 2461번… 이라 차이에 1을 더하면 항 번호다
        return 1, f"{ord(m[1]) - 0x2460 + 1}항"
    if m := ITEM.match(line):
        return 2, f"{m[1]}호"
    if m := SUBITEM.match(line):
        return 3, f"{m[1]}목"
    return None


def _deleted(text: str) -> bool:
    """ "③ 삭제", "제4조 삭제"처럼 지워진 줄인가."""
    return text == "삭제" or text.endswith(" 삭제")


def _article(lines: list[str]) -> tuple[str, list[tuple[list[str], str]]] | None:
    """조문 한 개를 (조 제목, [(이름표 경로, 글)])로 나눈다. 조문 머리가 아니면 None."""
    head = ARTICLE.match(lines[0])
    if head is None:
        return None
    label = f"제{head[1]}조" + (f"의{head[2]}" if head[2] else "")
    title = f"{label}({head[3]})" if head[3] else label
    # nodes: (깊이, 이름표, 글). 깊이 0은 조, 1은 항, 2는 호, 3은 목
    nodes: list[tuple[int, str, str]] = [(0, label, title)]
    # [왜] 머리 줄은 "제3조(제목) ① …"처럼 첫 항이 붙어 오므로 제목 뒤 나머지(head[4])를 따로 한 줄로 본다
    for line in ([head[4]] if head[4] else []) + lines[1:]:
        kind = _line_kind(line)
        if kind is None:
            # 항·호·목이 아닌 줄("1)" 같은 하위 항목, 조 머리말)은 바로 앞 줄에 이어 붙인다
            depth, name, text = nodes[-1]
            nodes[-1] = (depth, name, f"{text} {line}")
        else:
            nodes.append((kind[0], kind[1], line))
    leaves = []
    stack: list[tuple[int, str, str]] = []  # 지금 줄과 그 윗줄들 (조 → 항 → 호 → 목)
    for i, node in enumerate(nodes):
        while stack and stack[-1][0] >= node[0]:
            stack.pop()  # 깊이가 같거나 더 깊은 줄은 이 줄의 윗줄이 아니다
        stack.append(node)
        next_depth = nodes[i + 1][0] if i + 1 < len(nodes) else -1
        # 다음 줄이 이 줄의 하위가 아니면 이 줄이 잎이다. 잎마다 단위 하나를 만든다
        if next_depth <= node[0] and not _deleted(node[2]):
            leaves.append(([n[1] for n in stack], " ".join(n[2] for n in stack)))
    return title, leaves


def split_units(
    page: str, *, doc_id: str, law_name: str, kind: str, effective: date, source_url: str
) -> list[Unit]:
    """조문 페이지 하나를 Unit 목록으로 만든다. unit_id는 {doc_id}@{시행일}#제26조.1항.2호.가목 (설계 5.2)."""
    units: list[Unit] = []
    chapters: list[tuple[int, str]] = []  # 지금 위치의 장·절 제목 (깊이, 제목)
    for block in BLOCK.finditer(page):
        if block[1] is not None:  # 장·절 제목 줄
            title = clean(block[1])
            if m := CHAPTER.match(title):
                depth = CHAPTER_DEPTH[m[1]]
                # [왜] 새 장이 나오면 앞 장의 절 제목은 버린다. 같거나 깊은 제목을 지우고 새 제목을 넣는다
                chapters = [c for c in chapters if c[0] < depth] + [(depth, title)]
            continue
        lines = [t for t in (clean(x) for x in LINE.findall(block[2])) if t]
        article = _article(lines) if lines else None
        if article is None:
            continue
        title, leaves = article
        heading = " > ".join([law_name, *(t for _, t in chapters), title])
        for labels, text in leaves:
            units.append(
                Unit(
                    unit_id=f"{doc_id}@{effective:%Y%m%d}#{'.'.join(labels)}",
                    doc_id=doc_id,
                    law_name=law_name,
                    kind=kind,
                    effective=effective,
                    source_url=source_url,
                    heading=heading,
                    text=text,
                    sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )
    return units
