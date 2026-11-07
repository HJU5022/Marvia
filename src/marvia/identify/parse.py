"""단서 글에서 화물 번호를 읽는다. 붙여 쓴 번호를 나누고, 나누는 방법이 하나로 정해지지 않으면
애매하다고 돌려준다 (설계 4.2). LLM은 쓰지 않는다."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["cargo_no", "bl", "container"]

# 영문·숫자로 시작하고 끝나며 하이픈을 품을 수 있는 8자 이상 덩어리를 번호 후보로 본다
_SPAN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{6,}[A-Za-z0-9]")
# 화물관리번호 19자리 = MRN 11 + MSN 4 + HSN 4 (v1 customs.py:13). 뒤 8자리는 숫자로 본다
_CARGO_NO = re.compile(r"[0-9A-Z]{11}[0-9]{8}")
# 컨테이너 번호 (ISO 6346) = 소유자 부호 영문 3 + 장비 구분 U·J·Z + 일련번호 6 + 확인 숫자 1
_CONTAINER = re.compile(r"[A-Z]{3}[UJZ][0-9]{7}")
# ISO 6346 글자 값: A=10부터 차례로 매기되 11의 배수(11, 22, 33)는 건너뛴다 (A=10, B=12, ..., Z=38)
# [왜] 표준이 정한 계산이라 rules/*.yaml에 두지 않는다 (_CARGO_NO, B/L 길이와 같다)
_LETTER_VALUE = dict(zip(string.ascii_uppercase, (v for v in range(10, 39) if v % 11), strict=True))
# 띄어 쓴 컨테이너 번호 (DEMU 123456 0, DEMU 1234560). [왜] 서류·컨테이너 문에 이렇게 적는다. 나뉜 조각은
#      8자보다 짧아 _SPAN이 못 찾고, 못 찾으면 가리지 않은 채 LLM에 간다
_SPACED_CONTAINER = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{3}[UJZujz][ -]?[0-9]{6}[ -]?[0-9](?![A-Za-z0-9])")
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
    """하이픈·빈칸을 빼고 대문자로 바꾼다."""
    return raw.replace("-", "").replace(" ", "").upper()


def check_digit(code: str) -> int:
    """ISO 6346 확인 숫자: 앞 10자의 값에 자리마다 1, 2, 4, ... 512를 곱한 합을 11로 나눈 나머지(10이면 0)."""
    total = sum((_LETTER_VALUE[ch] if ch.isalpha() else int(ch)) * 2**i for i, ch in enumerate(code[:10]))
    return total % 11 % 10


def is_container(value: str) -> bool:
    """컨테이너 번호 모양이고 확인 숫자가 맞는가."""
    return bool(_CONTAINER.fullmatch(value)) and check_digit(value) == int(value[-1])


def container_typo(value: str) -> bool:
    """컨테이너 번호 모양인데 확인 숫자가 틀렸나 (오타이거나 같은 모양의 B/L)."""
    return bool(_CONTAINER.fullmatch(value)) and not is_container(value)


def kind_of(value: str) -> Kind:
    """19자리 화물관리번호 형식이면 cargo_no, 확인 숫자가 맞는 컨테이너 번호면 container, 아니면 bl."""
    if _CARGO_NO.fullmatch(value):
        return "cargo_no"
    # [왜] 확인 숫자가 틀리면 컨테이너로 보지 않는다(오타일 수도, 같은 모양 B/L일 수도 있다).
    #      식별 단계가 한 번 묻는다
    return "container" if is_container(value) else "bl"


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
    """덩어리 하나를 읽는다. 순서: 화물관리번호 → 접두어 반복 나누기 → 한 건(컨테이너 또는 B/L) → 애매함."""
    token = normalize(raw)
    if _CARGO_NO.fullmatch(token):
        return TokenRead(raw, [ReadNumber(token, "cargo_no")])
    parts = _prefix_split(token)
    if parts:
        return TokenRead(raw, [ReadNumber(p, kind_of(p)) for p in parts])
    if _MIN_LEN <= len(token) <= _MAX_LEN:
        return TokenRead(raw, [ReadNumber(token, kind_of(token))])
    # 너무 길고 나눌 근거가 없다: 반으로 나누는 안을 권장안으로, 통째로 읽는 안을 둘째로 둔다
    alternatives = [[token]]
    half = len(token) // 2
    if len(token) % 2 == 0 and _MIN_LEN <= half <= _MAX_LEN:
        alternatives.insert(0, [token[:half], token[half:]])
    return TokenRead(raw, [], ambiguous=True, alternatives=alternatives)


def find_spans(text: str) -> list[Span]:
    """글에서 번호 후보 덩어리의 위치를 찾는다. 숫자가 없거나 날짜·전화번호면 뺀다.
    띄어 쓴 컨테이너 번호는 확인 숫자가 맞을 때만 한 덩어리로 본다."""
    # [왜] 확인 숫자로 거른다. "영문 4자 숫자 7자리"처럼 띄어 쓴 다른 글을 번호로 잡지 않는다
    spans = [
        Span(m.start(), m.end(), m.group())
        for m in _SPACED_CONTAINER.finditer(text)
        if " " in m.group() and is_container(normalize(m.group()))
    ]
    # [왜] 찾은 컨테이너 번호 자리를 같은 길이의 빈칸으로 지우고 나머지를 훑는다. 조각은 다시 잡히지 않고,
    #      하이픈으로 붙은 옆 번호(HASL0001-DEMU 123456 0)는 그대로 잡힌다
    rest = text
    for s in spans:
        rest = rest[: s.start] + " " * (s.end - s.start) + rest[s.end :]
    for m in _SPAN.finditer(rest):
        raw = m.group()
        if any(ch.isdigit() for ch in raw) and not _NOT_NUMBER.fullmatch(normalize(raw)):
            spans.append(Span(m.start(), m.end(), raw))
    return sorted(spans, key=lambda s: s.start)


def read_numbers(text: str) -> list[tuple[Span, TokenRead]]:
    """글 전체를 읽어 덩어리마다 (위치, 읽은 결과)를 돌려준다."""
    return [(span, read_token(span.raw)) for span in find_spans(text)]
