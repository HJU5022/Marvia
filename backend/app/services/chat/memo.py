"""메모장 질문·저장 요청 판별과 메모 답 글 만들기 (services/chat/chat.py에서 옮김, docs/specs/memory.md). DB 읽기(_load_memo)는 chat.py에 있다."""
from __future__ import annotations

import re
from backend.app.services.judge import guard
from backend.app.services.chat.patterns import (
    MEMO_CONTACT,
    MEMO_RECALL_END,
    MEMO_REF,
    SAVE_REQUEST,
    _DATE_ISO,
    _PHONE_IN_TEXT,
)
from backend.app.services.chat.texts import MEMO_ANON, MEMO_NONE

def is_save_request(masked: str) -> bool:
    """이번 문장이 새 사실을 저장해 달라는 부탁인가. 저장 부탁에는 꺼내 보기 답(MEMO_NONE)을 내지 않는다 (운영 점검)."""
    return bool(SAVE_REQUEST.search(masked)) and not re.search(r"[?？]", masked)

def is_memo_question(masked: str) -> bool:
    """이번 문장이 전에 저장한·말한 것을 묻는가 (메모 꺼내 보기 대상). "자료에 없다" 재질문을 메모 꺼내 보기로 바꿀 때만 쓴다."""
    return bool(MEMO_REF.search(masked) or (MEMO_CONTACT.search(masked) and MEMO_RECALL_END.search(masked)))

def _norm_name(text: object) -> str:
    """배·화물 이름 비교용: 공백·기호를 빼고 대문자로. "호" 같은 꼬리 낱말은 건드리지 않는다."""
    return re.sub(r"[^0-9A-Z가-힣]", "", str(text or "").upper())

def _memo_view(item: dict, linked: bool) -> dict:
    """도구 결과로 줄 항목 하나. 값이 있는 칸만. 사용자가 넣은 글이라 주입 모양이면 그 칸을 뺀다 (이중 방어: 저장 때도 걸렀다)."""
    fields = {k: v for k, v in (item.get("fields") or {}).items() if isinstance(v, str) and v and not guard.looks_like_injection(v)}
    out = {"kind": item.get("kind"), **fields}
    if item.get("kind") == "contact":
        out["linked_to_cargo"] = linked
    return out

def _companies_text(companies: list[dict]) -> str:
    """"A(포워더), B(수출자)" 모양. 전화번호는 넣지 않는다."""
    return ", ".join(f"{c['company']}({c['role']})" if c.get("role") else str(c["company"]) for c in companies if c.get("company"))

def memo_reply_text(result: dict, ship_ask: bool) -> str | None:
    """코드가 쓰는 메모 답. ok가 아닌 모든 상태와, ok인데 LLM 문장이 검사에 걸렸을 때의 목록이다. 항목이 없으면 None."""
    status, companies = result.get("status"), result.get("companies") or []
    if status == "anonymous":
        return MEMO_ANON
    if status == "ambiguous":
        who = _companies_text(companies)
        return f"저장된 거래처는 {who}예요. " + ("이 배 담당이 어느 쪽인가요?" if ship_ask else "어느 쪽을 찾으세요?")
    if status in ("none", "no_match"):
        who = _companies_text(companies)
        return f"{MEMO_NONE} 저장된 거래처는 {who}예요." if who else MEMO_NONE
    if status == "ok":
        lines = []
        for it in result.get("items") or []:
            if it.get("kind") == "contact":
                parts = [it.get("company"), it.get("role"), it.get("duty"), it.get("phone")]
                lines.append("- " + " · ".join(p for p in parts if p) + (f" ({it['source']}에서)" if it.get("source") else ""))
            else:
                lines.append("- " + " · ".join(str(v) for k, v in it.items() if k not in ("kind", "done") and v))
        return "저장된 메모에서 찾았어요.\n" + "\n".join(lines) if lines else None
    return None

def memo_phones_ok(text: str, result: dict) -> bool:
    """LLM이 쓴 답 속 전화번호가 모두 돌려준 항목에 글자 그대로 있는가 (지어낸 번호 차단)."""
    allowed = {str(it.get("phone")).strip() for it in result.get("items") or [] if it.get("phone")}
    return all(p.strip() in allowed for p in _PHONE_IN_TEXT.findall(_DATE_ISO.sub("", text)))
