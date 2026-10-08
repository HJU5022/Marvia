"""문장 속 B/L·MRN·컨테이너 번호와 배 이름·사람 이름을 코드로 찾고 가리는 순수 함수 (services/chat/chat.py에서 옮김). LLM에는 가린 값만 넘긴다 (CLAUDE.md)."""
from __future__ import annotations

import re
from datetime import date
from backend.app.schemas.customs import mask_bl
from backend.app.services.judge.rules import load_file
from backend.app.services.chat.limits import CARGO_RULES_PATH, UNREAD_MAX
from backend.app.services.chat.patterns import (
    _ASKED_SPAN,
    _BL,
    _BL_TOKEN,
    _CONTAINER,
    _DATE_GIVEN,
    _DEST_FILLER,
    _DEST_WORDS,
    _ID_LIKE,
    _MRN,
    _NOT_A_NAME,
    _PERSON_TITLES,
    _PREDICATE_END,
    _SHIP_HO,
    _SHIP_HO_NOT,
    _SHIP_LOC,
    _SHIP_LOC_END,
    _SHIP_LOC_NOT,
    _SHIP_NAMED,
    _SHIP_NAMED_TAIL,
    _SHIP_TALK,
)
from backend.app.services.chat.texts import UNKNOWN_BL_WORD, _PERSON_SUFFIXES

def is_cargo_ship(ship_kind: str | None, purpose: str | None) -> bool:
    """소량 수입 화물을 싣고 내리는 배인가. 선종과 입항 목적이 둘 다 목록에 있어야 한다."""
    rules = load_file(CARGO_RULES_PATH)
    return ship_kind in rules["cargo_ship_kinds"] and purpose in rules["cargo_purposes"]

def extract_mrn(message: str) -> tuple[str | None, str]:
    """문장에서 MRN 하나를 뽑고 그 자리를 [MRN]으로 바꾼 문장을 돌려준다. MRN은 LLM에 보내지 않는다(코드만 쓴다).
    "MRN" 이름표가 있으면 그 뒤 값을, 없으면 MRN 모양 중 숫자 2자리로 시작하는 첫 값을 쓴다."""
    labeled = re.search(r"MRN\s*[:：]?\s*([0-9]{2}[A-Za-z0-9]{8}[IEie])(?![A-Za-z0-9])", message, re.I)
    m = labeled or _MRN.search(message)
    if not m:
        return None, message
    value = m.group(1)
    return value.upper(), message.replace(value, "[MRN]")

def _is_destination(text: object) -> bool:
    """place·label이 도착지 자체(Busan, 부산, Korea, 한국, KRPUS 등)인가. 낱말을 모두 목적지 낱말(+port 같은 군더더기)로만 이루면 참."""
    if not isinstance(text, str):
        return False
    words = [w for w in re.split(r"[^A-Za-z0-9가-힣]+", text.lower()) if w]
    core = [w for w in words if w not in _DEST_FILLER]
    return bool(core) and all(w in _DEST_WORDS for w in core)

def _flat_text(t: str) -> str:
    return re.sub(r"\s+", "", t or "")

def _ship_name_in(text: str) -> str | None:
    for m in _SHIP_HO.finditer(text):
        if not m.group(1).endswith(_SHIP_HO_NOT):
            return m.group(1) + "호"
    m = _SHIP_LOC.search(text)
    if m:
        cand = m.group(1).strip()
        # 조사·서술어 끝 낱말("오는", "중국에서")과 식별자 모양(TEST41: B/L 오타일 수 있어 되묻는다)은 배 이름으로 보지 않는다
        if (re.sub(r"\s+", "", cand) not in _SHIP_LOC_NOT and not cand.endswith(_SHIP_LOC_END) and not _ID_LIKE.search(cand)):
            return cand
    m = _SHIP_NAMED.search(text)
    if m:
        name = _SHIP_NAMED_TAIL.sub("", m.group(1))
        if len(name) >= 2:
            return name
    return None

def ship_name_guess(masked: str, user_turns: list[str]) -> str | None:
    """사용자가 배 이름으로 말한 글을 뽑는다. 이번 문장에 있으면 그것. 없고 이번 문장이 "배 이름이야"처럼 이름 이야기면 앞 사용자 말(최근 것부터)에서.
    B/L 토큰 안쪽 글자는 이미 가려져 있어 뽑히지 않는다."""
    found = _ship_name_in(masked)
    if found or not _SHIP_TALK.search(masked):
        return found
    for text in reversed(user_turns):
        found = _ship_name_in(text)
        if found:
            return found
    return None

def person_names(masked: str, known_words: str) -> list[str]:
    """가린 문장에서 사람 이름처럼 생긴 낱말(조사를 뗀 뿌리)을 뽑는다. known_words(Skill 문서·고정 안내)에 있는 낱말은 이름이 아니다."""
    flat_known = re.sub(r"\s+", "", known_words)
    names: list[str] = []
    first_word = (masked.split() or [""])[0].strip("?!.,~")  # (c)는 문장 맨 앞 낱말만 본다
    for token in re.findall(r"[가-힣]{2,8}", masked):
        stem = None
        for suffix in _PERSON_SUFFIXES:
            if token.endswith(suffix) and 2 <= len(token) - len(suffix) <= 4:
                stem = token[: -len(suffix)]
                break
        if stem is None and token.endswith(_PERSON_TITLES):
            stem = token
        if stem is None and token == first_word and 2 <= len(token) <= 3 and not _PREDICATE_END.search(token) and token not in _NOT_A_NAME:
            stem = token
        if stem and stem not in flat_known and not _PREDICATE_END.search(stem) and stem not in names:
            names.append(stem)
    return names

def echoes_person_name(masked: str, reply: str, known_words: str) -> bool:
    """답이 사용자 문장 속 사람 이름을 그대로 옮겨 썼는가 (이름 글자가 답에 들어 있으면 참)."""
    flat_reply = re.sub(r"\s+", "", reply or "")
    return any(name in flat_reply for name in person_names(masked, known_words))

def _is_date_digits(value: str) -> bool:
    """20YYMMDD 모양의 실제 날짜인가. B/L 모양(숫자 포함 8자 이상)과 겹치지만 B/L이 아니라 사용자가 쓴 날짜다."""
    if not re.fullmatch(r"20\d{6}", value):
        return False
    try:
        date(int(value[:4]), int(value[4:6]), int(value[6:]))
        return True
    except ValueError:
        return False

def mask_bls(message: str, refs: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """문장 속 B/L 모양을 [BL1], [BL2]로 바꾸고 {토큰: 원래 B/L(대문자)}을 돌려준다. LLM은 바뀐 문장만 본다.
    refs를 주면 그 번호표에 이어서 매긴다 (최근 대화를 같은 번호로 가릴 때, _masked_history)."""
    refs = {} if refs is None else refs

    def swap(m: re.Match) -> str:
        bl = m.group(0).upper()
        if _is_date_digits(bl):  # "20261010 도착이래" 같은 날짜를 B/L로 조회하지 않게
            return m.group(0)
        for token, value in refs.items():
            if value == bl:
                return token
        token = f"[BL{len(refs) + 1}]"
        refs[token] = bl
        return token

    return _BL.sub(swap, message), refs

def container_check_digit(code10: str) -> int:
    """ISO 6346 검산 숫자. 앞 10자(글자 4 + 숫자 6)로 계산한다.
    글자 값은 A=10부터 이어 세되 11의 배수(11, 22, 33)는 건너뛴다. 각 자리 값에 2의 (자리 번호)제곱을 곱해 더하고 11로 나눈 나머지에서 10이면 0."""
    values, value = {}, 10
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if value % 11 == 0:
            value += 1
        values[letter] = value
        value += 1
    total = sum((values[c] if c.isalpha() else int(c)) * (2 ** i) for i, c in enumerate(code10.upper()))
    return total % 11 % 10

def find_containers(message: str) -> list[str]:
    """문장 속 컨테이너 번호(대문자, 처음 나온 순서, 중복 없음). 모양과 검산 숫자가 모두 맞는 것만이다."""
    found: list[str] = []
    for m in _CONTAINER.finditer(message):
        code = m.group(0).upper()
        if int(code[10]) == container_check_digit(code[:10]) and code not in found:
            found.append(code)
    return found

def mask_containers(message: str, refs: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """문장 속 컨테이너 번호를 [CNTR1], [CNTR2]로 바꾸고 {토큰: 컨테이너}를 돌려준다. B/L 가리기(mask_bls)와 같은 방식이다.
    mask_bls보다 먼저 해야 한다: 컨테이너 모양(영숫자 11자)이 B/L 모양에도 걸려 [BL1]로 잘못 바뀐다."""
    refs = {} if refs is None else refs
    valid = set(find_containers(message))

    def swap(m: re.Match) -> str:
        code = m.group(0).upper()
        if code not in valid:
            return m.group(0)
        for token, value in refs.items():
            if value == code:
                return token
        token = f"[CNTR{len(refs) + 1}]"
        refs[token] = code
        return token

    return _CONTAINER.sub(swap, message), refs

def _valid_date(value: str | None) -> str | None:
    """YYYY-MM-DD이고 실제 있는 날짜일 때만. LLM이 만든 날짜를 그대로 믿지 않는다."""
    if not value or not isinstance(value, str):  # 도구 인자는 strict 스키마가 아니라 숫자·목록이 올 수 있다
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None

def asked_days(text: str) -> int | None:
    """사용자 글이 입항 목록의 기간을 며칠로 말했는가 (가장 긴 것). "30일", "2주", "한 달", "3개월". 기간 말이 없으면 None.
    DAYS_MAX를 넘는 요청에 한계를 밝히는 데 쓴다 (search_vessels는 말없이 DAYS_MAX로 줄였다)."""
    spans = []
    for m in _ASKED_SPAN.finditer(text or ""):
        n = int(m.group(1)) if m.group(1).isdigit() else {"한": 1, "두": 2, "세": 3, "네": 4}[m.group(1)]
        spans.append(n * {"일": 1, "주일": 7, "주": 7, "달": 30, "개월": 30}[m.group(2)])
    return max(spans) if spans else None

def user_gave_date(text: str) -> bool:
    """사용자 글에 날짜 모양이 있는가. [BLn] 번호표는 먼저 뺀다 (번호표 속 숫자는 날짜가 아니다)."""
    return bool(_DATE_GIVEN.search(re.sub(r"\[BL\d+\]", " ", text or "")))

def sale_if_given(value, text: str) -> str | None:
    """LLM이 낸 판매일(YYYY-MM-DD)을 사용자가 날짜를 말한 문장에서만 쓴다. 말하지 않았으면 버린다 (LLM이 지어낸 날짜 방지)."""
    return _valid_date(value) if user_gave_date(text) else None

def unread_ids(masked: str, bls: list[str]) -> list[str]:
    """가린 문장에서 B/L로 읽히지 않은 식별자 모양 글자(영문+숫자 섞임)를 사용자가 쓴 그대로 뽑는다. 조회한 B/L과 같은 글자는 뺀다.
    날짜(숫자·한글뿐)와 일반 낱말은 _ID_LIKE가 영문+숫자를 모두 요구해 걸리지 않는다."""
    known = {b.upper() for b in bls}
    found = [m.group(0) for m in _ID_LIKE.finditer(masked) if m.group(0).upper() not in known]
    return list(dict.fromkeys(found))[:UNREAD_MAX]

def hide_bl_tokens(reply: str, refs: dict[str, str]) -> str:
    """답에 남은 내부 번호표 [BL1] 같은 글자를 사용자가 알아볼 수 있는 가린 B/L(TE****01)로 바꾼다.

    왜: LLM은 B/L 대신 [BLn]만 보므로(CLAUDE.md "B/L 번호를 LLM에 넘기지 않는다"), 지난 대화를 보고 "B/L 번호가 뭐였지?"에 답하면
    번호표가 그대로 화면에 나갔다. 원문이 아니라 가운데를 가린 값으로 되돌린다(SDD 3.5, schemas/customs.mask_bl):
    사용자는 어느 화물인지 알아보고, 원문은 새 곳에 퍼지지 않는다. 표에 없는 토큰은 일반 말로 바꾼다.
    여러 B/L 표 답은 _agent_turn이 이미 사용자가 쓴 B/L로 되돌려 둔 뒤라 여기서는 남은 토큰만 본다."""
    return _BL_TOKEN.sub(lambda m: mask_bl(refs[m.group(0)]) if m.group(0) in refs else UNKNOWN_BL_WORD, reply or "")
