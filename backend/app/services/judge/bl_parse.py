"""흐트러지게 쓴 B/L 번호를 읽어 내고, 세관에 실제로 있는지 확인해서만 받아들인다.

왜 이렇게 하나: 사용자는 "test-bl-01", "TEST-BL/01", "test bl01"처럼 기호·띄어쓰기를 섞어 쓰고,
두 B/L을 붙여 "TESTBL01TESTBL02"로 쓰기도 한다. B/L 길이는 8~20자로 제각각이라 글자 모양만으로는
100% 알 수 없다. 그래서 후보를 만들고 → UNI-PASS에 있는지 확인하고 → 확인된 것만 쓴다.
확인된 후보가 없으면 아무것도 바꾸지 않고, 평소처럼 되묻는다. 고쳐 읽었으면 답에 코드가 쓴 문장을 붙인다 (LLM 아님).

이 파일은 순수 함수 + 세관 확인 어댑터만 둔다. chat.py 연결 위치는 handle()의 extract_mrn 뒤와 not found 처리 자리다.
"""
import re
from typing import Callable

from backend.app.observability.logging import log_failure
from backend.app.services.judge.customs import CustomsError, UnipassClient

# 후보를 세관에 물어볼 최대 횟수. exists 한 번이 UNI-PASS 최대 2번 호출(하우스, 마스터)이라 상한을 둔다
MAX_CHECKS = 6
BL_MIN, BL_MAX = 8, 20  # chat.py _BL과 같은 길이 범위
GLUED_MIN, GLUED_MAX = 16, 40  # 붙여 쓴 토큰 길이. 2개(8+8)부터 3개(최대 40)까지만 본다
RUN_MAX_PIECES = 6  # 한 줄에 이어진 조각을 이보다 길게 보지 않는다 (문장 전체를 붙여 보는 것을 막는다)

# 알림 문장. B/L 번호는 넣지 않는다 (번호는 답에 쓰지 않는 규칙)
NOTE_SYMBOL = "(기호를 빼고 B/L 번호로 읽었어요.)"
NOTE_SPACE = "(띄어쓰기를 붙여 B/L 번호로 읽었어요.)"
NOTE_GLUED = "(붙어 있던 번호를 두 B/L로 나눠 읽었어요.)"

# 영문·숫자 조각이 기호(- /. _) 또는 공백 한 칸으로 이어진 줄. 한글이 끼면 거기서 끊긴다
_RUN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]+(?:[-/._ ][A-Za-z0-9]+)+(?![A-Za-z0-9])")
_PIECE = re.compile(r"[A-Za-z0-9]+")
_ALNUM = re.compile(r"[A-Za-z0-9]+")


def _looks_like_bl(text: str) -> bool:
    """8~20자 영문·숫자이고 숫자가 하나는 있다 (chat.py _BL과 같은 모양)."""
    return BL_MIN <= len(text) <= BL_MAX and text.isascii() and text.isalnum() and any(c.isdigit() for c in text)


def _windows(text: str) -> list[tuple[int, int, str]]:
    """문장에서 (시작, 끝, 붙인 값) 후보를 모두 찾는다. 위치가 필요한 repair_message가 쓴다."""
    found = []
    for run in _RUN.finditer(text):
        pieces = list(_PIECE.finditer(text, run.start(), run.end()))[:RUN_MAX_PIECES]
        # 조각 i부터 j까지를 한 번호로 붙여 본다
        for i in range(len(pieces)):
            for j in range(i + 1, len(pieces)):
                start, end = pieces[i].start(), pieces[j].end()
                span = text[start:end]
                joined = "".join(p.group() for p in pieces[i:j + 1])
                if not _looks_like_bl(joined):
                    continue
                if joined.isdigit():
                    continue  # 날짜(2026-10-05)·전화번호·금액은 숫자만이라 B/L로 읽지 않는다
                if " " in span and any(_looks_like_bl(p.group()) for p in pieces[i:j + 1]):
                    continue  # 공백으로 이으면서 이미 B/L 모양인 조각이 있으면 원래 그 번호를 쓴 것이다
                if not any(c.isdigit() for c in pieces[j].group()):
                    continue  # B/L은 숫자로 끝나는 경우가 많다. "test bl01 now"의 now까지 붙이지 않는다
                found.append((start, end, joined))
    # 강한 후보(기호로만 이음) 먼저, 그다음 조각이 적은 것(덜 붙인 것), 그다음 앞쪽 위치
    found.sort(key=lambda w: (" " in text[w[0]:w[1]], len(_PIECE.findall(text[w[0]:w[1]])), w[0]))
    return found


def separator_candidates(text: str) -> list[tuple[str, str]]:
    """(문장 속 원래 글자, 붙인 값) 쌍. 기호(-, /,., _)로 이은 것이 강한 후보, 공백으로 이은 것은 약한 후보라 뒤로 간다.
    둘 다 세관 확인을 거쳐야 한다."""
    return [(text[s:e], joined.upper()) for s, e, joined in _windows(text)]


def split_candidates(token: str) -> list[tuple[str, ...]]:
    """못 찾은 긴 토큰을 두 개(드물게 세 개)로 나눈 후보. 각 조각은 8~20자이고 숫자가 있다.

    순서: 앞 4글자가 같은 문자로 시작하는 나눔을 먼저 본다. 선사가 B/L 앞에 4글자 코드를 붙이는 일이 많아서 쓰는
    경험칙이지 사실은 아니다. 그다음 2개 나눔, 그다음 조각 길이가 비슷한 것. 상한은 MAX_CHECKS."""
    token = token.upper()
    if not (GLUED_MIN <= len(token) <= GLUED_MAX and token.isascii() and token.isalnum()):
        return []
    n = len(token)
    splits: list[tuple[str, ...]] = []
    for k in range(BL_MIN, n - BL_MIN + 1):  # 2개로
        splits.append((token[:k], token[k:]))
    for a in range(BL_MIN, n):  # 3개로
        for b in range(a + BL_MIN, n - BL_MIN + 1):
            splits.append((token[:a], token[a:b], token[b:]))
    splits = [s for s in splits if all(_looks_like_bl(p) for p in s)]

    def key(parts: tuple[str, ...]):
        lead = parts[0][:4]
        same_prefix = lead.isalpha() and all(p.startswith(lead) for p in parts)
        return (not same_prefix, len(parts), max(len(p) for p in parts) - min(len(p) for p in parts))

    splits.sort(key=key)
    return splits[:MAX_CHECKS]


class _Checker:
    """exists 호출을 세고 같은 번호는 한 번만 묻는다. 한도에 닿으면 더 묻지 않는다 (결과가 늘 같도록 순서는 후보 순서)."""

    def __init__(self, exists: Callable[[str], bool], max_checks: int):
        self.exists = exists
        self.left = max_checks
        self.cache: dict[str, bool] = {}

    def has(self, bl: str) -> bool:
        if bl in self.cache:
            return self.cache[bl]
        if self.left <= 0:
            return False  # 한도 초과: 확인 못 한 것은 없는 것으로 본다
        self.left -= 1
        self.cache[bl] = bool(self.exists(bl))
        return self.cache[bl]

    def all_exist(self, parts: tuple[str, ...]) -> bool:
        # 한 조각이라도 없으면 거기서 멈춘다 (나머지를 묻지 않는다)
        return all(self.has(p) for p in parts)


def resolve(candidates: list[tuple[str, ...]], exists: Callable[[str], bool], max_checks: int = MAX_CHECKS) -> list[tuple[str, ...]]:
    """후보 중 모든 조각이 세관에 있는 것만 돌려준다. 후보 하나는 B/L 하나(기호 후보) 또는 둘 이상(붙은 후보)."""
    checker = _Checker(exists, max_checks)
    return [c for c in candidates if checker.all_exist(c)]


def repair_message(message: str, exists: Callable[[str], bool], max_checks: int = MAX_CHECKS) -> tuple[str, list[str]]:
    """기호·띄어쓰기로 흐트러진 B/L을 확인된 것만 붙여서 문장에 되돌려 넣는다. (새 문장, 알림 문장들).

    바꾼 문장은 chat.py의 mask_bls가 평소처럼 [BL1]로 가린다. 확인 못 하면 문장은 그대로다."""
    checker = _Checker(exists, max_checks)
    accepted: list[tuple[int, int, str]] = []
    notes: list[str] = []
    for start, end, joined in _windows(message):
        if any(start < e and s < end for s, e, _ in accepted):
            continue  # 이미 받아들인 자리와 겹치면 더 묻지 않는다
        if checker.has(joined.upper()):
            accepted.append((start, end, joined.upper()))
            note = NOTE_SPACE if " " in message[start:end] else NOTE_SYMBOL
            if note not in notes:
                notes.append(note)
    for start, end, joined in sorted(accepted, reverse=True):  # 뒤에서부터 바꿔야 앞 위치가 안 밀린다
        message = message[:start] + joined + message[end:]
    return message, notes


def split_not_found(token: str, exists: Callable[[str], bool], max_checks: int = MAX_CHECKS) -> list[str]:
    """세관에서 못 찾은 긴 토큰을 나눠 본다. 모든 조각이 세관에 있는 첫 나눔을 돌려준다. 없으면 빈 목록 (되묻는다)."""
    verified = resolve(split_candidates(token), exists, max_checks)
    return list(verified[0]) if verified else []


def exists_in_customs(bl: str) -> bool:
    """UNI-PASS에 이 B/L이 있는가. 기존 UnipassClient.fetch를 그대로 쓴다 (더 가벼운 조회 API는 없다, 같은 한 번의 호출).

    하우스를 먼저, 없으면 마스터로 한 번 더 본다. 사용자가 붙여 쓴 번호가 어느 쪽인지 모르고, 잘못 고르면 "없음"이 나와서
    진짜 B/L을 못 읽기 때문이다. 대가는 없는 후보 하나당 UNI-PASS 2번 호출이다.
    클라이언트에 캐시는 없다. 오류·키 없음은 "확인 못 함"(False)이다. B/L 원문은 로그에 쓰지 않는다."""
    try:
        client = UnipassClient()
    except CustomsError as e:
        log_failure("bl_parse", e.code)
        return False
    try:
        for bl_type in ("HOUSE", "MASTER"):
            if client.fetch(bl, bl_type) is not None:
                return True
        return False
    except CustomsError as e:
        log_failure("bl_parse", e.code)
        return False
    finally:
        client.close()
