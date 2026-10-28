"""단서 글에서 화물 번호를 읽는다. 붙여 쓴 번호를 나누고, 나누는 방법이 하나로 정해지지 않으면
애매하다고 돌려준다 (설계 4.2). LLM은 쓰지 않는다."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["cargo_no", "bl"]

# 영문·숫자로 시작하고 끝나며 하이픈을 품을 수 있는 8자 이상 덩어리를 번호 후보로 본다
_SPAN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{6,}[A-Za-z0-9]")
# 화물관리번호 19자리 = MRN 11 + MSN 4 + HSN 4 (v1 customs.py:13). 뒤 8자리는 숫자로 본다
_CARGO_NO = re.compile(r"[0-9A-Z]{11}[0-9]{8}")
# 번호처럼 보여도 번호가 아닌 것: 날짜(YYYYMMDD), 휴대폰 번호
_NOT_NUMBER = re.compile(r"20\d{6}|01[016789]\d{7,8}")
# B/L 한 건의 길이 범위 (v1 patterns.py와 같은 8~20자)
_MIN_LEN, _MAX_LEN = 8, 20


@dataclass(frozen=True)
class ReadNumber:
    value: str
    kind: Kind


@dataclass
class TokenRead:
    raw: str
    numbers: list[ReadNumber]
    ambiguous: bool = False
    alternatives: list[list[str]] = field(default_factory=list)


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    raw: str


def normalize(raw: str) -> str:
    """하이픈을 빼고 대문자로 바꾼다."""
    return raw.replace("-", "").upper()


def kind_of(value: str) -> Kind:
    """19자리 화물관리번호 형식이면 cargo_no, 아니면 bl."""
    return "cargo_no" if _CARGO_NO.fullmatch(value) else "bl"


def _prefix_split(token: str) -> list[str] | None:
    """맨 앞 영문 4자(선사 부호 자리)가 다시 나오는 자리마다 나눈다.
    나눈 조각이 모두 B/L 길이 범위 안이면 조각 목록, 아니면 None."""
    prefix = token[:4]
    if not prefix.isalpha():
        return None
    starts = [m.start() for m in re.finditer(re.escape(prefix), token)]
    if len(starts) < 2:
        return None
    parts = [token[a:b] for a, b in zip(starts, starts[1:] + [len(token)], strict=True)]
    return parts if all(_MIN_LEN <= len(p) <= _MAX_LEN for p in parts) else None


def read_token(raw: str) -> TokenRead:
    """덩어리 하나를 읽는다. 순서: 화물관리번호 → 접두어 반복 나누기 → 한 건 → 애매함."""
    token = normalize(raw)
    if _CARGO_NO.fullmatch(token):
        return TokenRead(raw, [ReadNumber(token, "cargo_no")])
    parts = _prefix_split(token)
    if parts:
        return TokenRead(raw, [ReadNumber(p, kind_of(p)) for p in parts])
    if _MIN_LEN <= len(token) <= _MAX_LEN:
        return TokenRead(raw, [ReadNumber(token, "bl")])
    # 너무 길고 나눌 근거가 없다: 반으로 나누는 안을 권장안으로, 통째로 읽는 안을 둘째로 둔다
    alternatives = [[token]]
    half = len(token) // 2
    if len(token) % 2 == 0 and _MIN_LEN <= half <= _MAX_LEN:
        alternatives.insert(0, [token[:half], token[half:]])
    return TokenRead(raw, [], ambiguous=True, alternatives=alternatives)


def find_spans(text: str) -> list[Span]:
    """글에서 번호 후보 덩어리의 위치를 찾는다. 숫자가 없거나 날짜·전화번호면 뺀다."""
    spans = []
    for m in _SPAN.finditer(text):
        raw = m.group()
        if any(ch.isdigit() for ch in raw) and not _NOT_NUMBER.fullmatch(normalize(raw)):
            spans.append(Span(m.start(), m.end(), raw))
    return spans


def read_numbers(text: str) -> list[tuple[Span, TokenRead]]:
    """글 전체를 읽어 덩어리마다 (위치, 읽은 결과)를 돌려준다."""
    return [(span, read_token(span.raw)) for span in find_spans(text)]
