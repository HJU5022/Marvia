"""채팅 답 문장 속 근거 표시([E1]) 만들기와 검증 (순수 함수만).

책임: (a) 이번 대화에서 모은 근거 카드를 LLM에게 줄 짧은 id 목록(E1, E2...)으로 만든다,
(b) LLM이 답에 붙인 [E1] 표시를 코드가 검사해 틀린 것은 지운다, (c) 표시를 모두 걷어 낸 글을 돌려준다.

왜 코드가 검사하나: 어떤 문장이 어느 근거에서 왔는지는 LLM이 "표시"만 하고, 맞는지는 코드가 정한다.
CLAUDE.md "LLM이 값을 정하게 두지 않는다". 틀린 표시는 근거 없는 말에 근거가 있는 척 보이게 하므로 지운다.
숫자 대조는 validate.py V7("근거에 없는 숫자")과 같은 방식이다: 같은 NUMBER 정규식과 정규화(_normal)를 그대로 쓴다.

이 파일은 LLM도 DB도 부르지 않는다. services/chat/chat.py가 호출한다 (연결 방법은 작업 보고).
B/L·컨테이너 번호: 근거 값에 섞여 있으면 가린 표시로 바꾼다 (CLAUDE.md "B/L 번호를 LLM에 넘기지 않는다").
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Iterable

from backend.app.services.judge.validate import NUMBER, _normal

# LLM이 붙이는 표시. [E1] 또는 [E1, E2] / [E1][E2]. 대소문자·공백 차이는 받아 준다
MARK_GROUP = re.compile(r"\[\s*E\d+(?:\s*[,，]\s*E\d+)*\s*\]", re.I)
_MARK_ID = re.compile(r"E\d+", re.I)
# 문장 끝: 마침표류 뒤 공백, 또는 줄바꿈 (validate.SENTENCE_END와 같은 기준)
_SENT_END = re.compile(r"(?<=[.!?。])\s+|\n")
# 컨테이너 번호(영문 4 + 숫자 7). 근거 값에 끼어 있어도 원문을 LLM과 화면에 넘기지 않는다
_CONTAINER = re.compile(r"\b([A-Z]{4})(\d{7})\b")
# 표시처럼 보이는 글이 근거 값 안에 있으면 괄호를 바꿔 표시로 읽히지 않게 한다 (주입 방어)
_FORGED_MARK = re.compile(r"\[\s*E\d+")

MAX_VALUE_CHARS = 200  # 근거 값 한 개의 길이 상한. 값이 길어도 프롬프트가 부풀지 않게


def _mask(value: str) -> str:
    """컨테이너 번호 모양을 가운데 *로 가린다. B/L은 근거 카드에 원래 없고, 있더라도 호출하는 쪽이 가린 글을 넘긴다."""
    def swap(m: re.Match) -> str:
        code = m.group(0)
        return code[:2] + "*" * (len(code) - 4) + code[-2:]
    return _CONTAINER.sub(swap, value)


def _safe_value(value: Any) -> str:
    """근거 값을 글자로 바꾸고 가리고 자른다. 표시 모양 글자는 무력화한다 (근거 값은 데이터이지 지시가 아니다, SDD 7절)."""
    text = value.isoformat() if isinstance(value, (datetime, date)) else str(value)
    text = _mask(" ".join(text.split()))
    text = _FORGED_MARK.sub("(E", text)  # "[E2" -> "(E2"
    return text[:MAX_VALUE_CHARS]


def _get(card: Any, key: str, default=None):
    return card.get(key, default) if isinstance(card, dict) else getattr(card, key, default)


def build_evidence_list(cards: Iterable[Any]) -> list[dict]:
    """근거 카드(Evidence)를 LLM에게 줄 목록으로 만든다. id는 E1부터.

    같은 출처(source)에 같은 조회 시각(분 단위)인 카드는 한 묶음으로 합친다. 한 번의 조회에서 나온 값들이라
    사용자에게는 "한 번 조회한 결과" 하나로 보이는 게 자연스럽고, LLM이 외울 id도 줄어든다.
    반환 항목: {id, source, fetched_at(ISO 글자), values:[{field, value}]}
    """
    groups: dict[tuple[str, str], dict] = {}
    for card in cards or []:
        value = _get(card, "value")
        if value is None or value == "":
            continue
        source = str(_get(card, "source", "") or "")
        at = _get(card, "fetched_at")
        at_text = at.isoformat() if isinstance(at, (datetime, date)) else str(at or "")
        key = (source, at_text[:16])
        group = groups.setdefault(key, {"source": source, "fetched_at": at_text, "values": []})
        group["values"].append({"field": str(_get(card, "field", "")), "value": _safe_value(value)})
    items = list(groups.values())
    for n, item in enumerate(items, 1):
        item["id"] = f"E{n}"
    return items


def evidence_prompt_block(evidence: list[dict]) -> str:
    """LLM에게 보여 줄 근거 목록 글. 한 줄에 id, 출처, 값들. 이 글 전체가 데이터다 (지시로 읽지 않는다)."""
    lines = []
    for item in evidence:
        values = "; ".join(f"{v['field']}={v['value']}" for v in item.get("values", []))
        lines.append(f"[{item['id']}] source={item['source']} | {values}")
    return "\n".join(lines)


def _numbers(text: str) -> set[str]:
    """V7과 같은 방식으로 숫자 조각을 뽑는다. 01과 1을 같은 값으로 본다."""
    return {_normal(n) for n in NUMBER.findall(text or "")}


def _evidence_numbers(item: dict) -> set[str]:
    out: set[str] = set()
    for v in item.get("values", []):
        out |= _numbers(v.get("value", ""))
    return out


def _sentence_bounds(text: str) -> list[tuple[int, int]]:
    """문장 [시작, 끝) 목록. 끝 문자는 포함한다."""
    bounds, start = [], 0
    for m in _SENT_END.finditer(text):
        bounds.append((start, m.start()))
        start = m.end()
    bounds.append((start, len(text)))
    return bounds


def parse_and_validate(answer_text: str, evidence_list: list[dict]) -> tuple[str, list[dict]]:
    """답 글의 [E#] 표시를 검사한다. 반환: (표시를 [E1] 모양으로 고른 글, citations).

    규칙:
    1. 근거 목록에 없는 id는 지운다.
    2. 한 문장에 있는 숫자·날짜는 그 문장에 표시된 근거들의 값 안에 모두 있어야 한다 (V7과 같은 기준).
       하나라도 없으면 그 문장의 표시를 모두 지운다. 숫자 없는 문장은 id가 맞기만 하면 통과.
    3. 같은 문장에서 같은 id가 두 번 나오면 하나만 둔다.
    citations 항목: {id, start, end, evidence_ref}. start/end는 반환 글 안 "[E1]" 표시의 위치(끝은 포함 안 함).
    표시가 하나도 안 남으면 citations는 빈 목록이다. 화면은 그때 글 끝에 근거 칩을 모은다.
    """
    text = answer_text or ""
    known = {item["id"].upper(): item for item in evidence_list}
    out: list[str] = []
    citations: list[dict] = []
    for start, end in _sentence_bounds(text):
        sentence = text[start:end]
        # 문장 사이 공백·줄바꿈은 sentence에 없으므로 원문에서 그대로 이어 붙인다
        gap_start = sum(len(p) for p in out)
        marks = list(MARK_GROUP.finditer(sentence))
        body = MARK_GROUP.sub("", sentence)
        ids: list[str] = []
        for m in marks:
            for found in _MARK_ID.findall(m.group(0)):
                eid = found.upper()
                if eid in known and eid not in ids:
                    ids.append(eid)
        if ids:
            allowed: set[str] = set()
            for eid in ids:
                allowed |= _evidence_numbers(known[eid])
            if not _numbers(body) <= allowed:
                ids = []  # 규칙 2: 근거에 없는 숫자가 있다
        # 표시를 지운 자리의 군더더기 공백 정리: "문장 [E9]." -> "문장."
        body = re.sub(r"\s+([.,!?。])", r"\1", body).rstrip() if marks else body
        if ids:
            tail_match = re.search(r"[.!?。]+$", body)
            insert_at = tail_match.start() if tail_match else len(body)
            # 표시는 문장 끝 마침표 앞에 모은다. 읽는 쪽은 "이 문장의 근거"로 본다
            body_core, body_tail = body[:insert_at], body[insert_at:]
            piece = body_core
            for eid in ids:
                s = gap_start + len(piece)
                piece += f"[{eid}]"
                citations.append({"id": f"C{len(citations) + 1}", "start": s, "end": gap_start + len(piece), "evidence_ref": eid})
            piece += body_tail
            body = piece
        out.append(body)
        # 다음 문장 앞의 구분자(공백 또는 줄바꿈)는 원문 그대로 되살린다
        nxt = end
        sep_m = _SENT_END.match(text, nxt) if nxt < len(text) else None
        if sep_m:
            out.append(text[sep_m.start():sep_m.end()])
    return "".join(out), citations


def strip_marks(text: str) -> str:
    """모든 [E#] 표시를 걷어 낸 글. 대화 제목, 카카오 알림, 이력처럼 표시가 필요 없는 곳에 쓴다.
    검증을 거치지 않은 글에도 쓸 수 있게 알 수 없는 id까지 모두 지운다."""
    out = MARK_GROUP.sub("", text or "")
    out = re.sub(r"[ \t]+([.,!?。])", r"\1", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()
