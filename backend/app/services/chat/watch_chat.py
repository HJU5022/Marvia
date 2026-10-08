"""지켜보기·카카오톡 보내기 제안 글과 지금 상태 글 만들기 (services/chat/chat.py에서 옮김). 켜고 끄는 동작은 chat.py가 훅으로 부른다."""
from __future__ import annotations

from datetime import date
from backend.app.schemas.agent import AgentResponse
from backend.app.services.watch import cargo
from backend.app.services.judge.verdict import VERDICT_LABEL
from backend.app.services.chat.patterns import FUTURE_WORDS, SEND_NOW
from backend.app.services.chat.texts import WATCH_ASK, WATCH_LOGIN_TAIL

def wants_send_now(masked: str) -> bool:
    """가린 문장이 "지금 카카오톡으로 보내 줘"인가. 앞날 낱말(바뀌면 등)이 있으면 지켜보기 요청이라 아니다."""
    return bool(SEND_NOW.search(masked)) and not FUTURE_WORDS.search(masked)

def kakao_now_text(row: dict, today: date) -> str | None:
    """"지금 상태" 카카오톡 문장. 화물 줄의 마지막 판정으로만 쓴다. 판정이 없으면 None.
    이름은 지켜보기 알림(services/watch/watch._notify)과 같다: 이름표, 없으면 가린 번호. B/L 원문은 쓰지 않는다.
    값이 없는 칸은 줄째 뺀다 (지어내지 않는다). 날짜는 한국 날짜 기준이다."""
    verdict = row.get("last_verdict")
    if verdict not in VERDICT_LABEL:
        return None
    lines = [f"[Marvia] {row.get('label') or row['bl_masked']} 화물 현재 상태", f"판정: {VERDICT_LABEL[verdict]}"]
    if row.get("last_eta"):
        lines.append(f"도착 예정: {row['last_eta'].isoformat()}")
    sale = row.get("sale_due_date")
    if sale:
        left = (sale - today).days
        lines.append(f"판매 예정일({sale.isoformat()})까지: " + (f"{left}일" if left >= 0 else f"{-left}일 지남"))
    if cargo.margin_text(row.get("last_days_margin")):
        lines.append(f"도착 기준: {cargo.margin_text(row['last_days_margin'])}")
    if row.get("last_stage"):
        lines.append(f"통관: {cargo.clean_stage(row['last_stage'])}")
    if row.get("last_checked_at"):
        lines.append(f"마지막 확인: {cargo._md(row['last_checked_at'])}")
    lines.append("Marvia에서 이유와 할 일을 확인하세요.")
    return "\n".join(lines)

def _offered(text: str) -> bool:
    """대화 기록의 글에 우리의 지켜보기 제안이 들어 있나."""
    return WATCH_ASK in text

def _josa_ira(text: str) -> str:
    """"…걱정" + 이라고/라고. 마지막 글자가 받침 있는 한글이면 이라고."""
    last = text[-1:]
    return "이라고" if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 else "라고"

def watch_offer_text(response: AgentResponse, logged_in: bool, worry: str | None) -> str | None:
    """"이 화물을 지켜볼까요?" 제안 문장. 이유는 코드가 가진 사실뿐이다: 판정 이름, 여유 일수, 사용자의 걱정 메모.
    판정이 없으면(되묻기·실패) 말할 이유가 없어 None. 없는 이유를 지어내지 않는다."""
    if response.verdict not in VERDICT_LABEL:
        return None
    label = VERDICT_LABEL[response.verdict]
    margin = response.days_margin
    if margin is None:
        reason = f"'{label}' 판정이에요."
    elif margin >= 0:
        reason = f"판매 예정일까지 여유가 {margin}일이고 '{label}' 판정이에요."
    else:
        reason = f"판매 예정일보다 {abs(margin)}일 늦게 도착할 예정이고 '{label}' 판정이에요."
    if worry:
        worry = " ".join(worry.replace("'", "").split())
        reason += f" 지난번에 '{worry}'{_josa_ira(worry)} 하셨죠."
    return f"{reason} {WATCH_ASK}" + ("" if logged_in else f" {WATCH_LOGIN_TAIL}")
