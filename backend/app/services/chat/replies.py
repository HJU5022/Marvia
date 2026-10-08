"""답 문장을 고르고 검사하는 순수 함수: 되묻기 변형, 선박 목록 글, 같은 답 반복 방지, 답 검증 (services/chat/chat.py에서 옮김)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from backend.app.observability.logging import log_failure
from backend.app.schemas.agent import AgentResponse
from backend.app.services.judge import guard
from backend.app.services import llm
from backend.app.services.judge import validate
from backend.app.services.chat.ids import _flat_text, is_cargo_ship
from backend.app.services.chat.texts import (
    BL_TYPE_KO,
    CLARIFY_AGAIN,
    CLARIFY_NO_ID,
    CLARIFY_TAIL,
    NEED_BL,
    NOT_FOUND_BOTH,
    NO_RESULT_AGAIN,
    NO_RESULT_BOTH,
    NO_RESULT_REPLY,
    NO_RESULT_THIRD,
    OTHER_REPLY,
    ROW_NOTE_MORE_INFO,
    ROW_NOTE_NOT_FOUND,
    ROW_NOTE_SAME_NAME,
    ROW_SAY_MORE_INFO,
    ROW_SAY_NOT_FOUND,
    ROW_SAY_SAME_NAME,
    ROW_SAY_STILL_SAME,
)
from backend.app.services.chat.patterns import (
    ACTION_ENDING,
    ACTION_WORDS,
    WATCH_REQUEST,
    _ID_LIKE,
    _OLD_NOTICE,
    _REPLY_WORDS,
)
from backend.app.services.chat.limits import ARRIVALS_SHOWN, SHIP_LIST_SHOWN
from backend.app.services.chat.screen import _fmt_time
from backend.app.services.chat.models import ChatResult

def not_same_twice(reply: str, alternatives: list[str], last: str | None) -> str:
    """바로 앞 assistant 답과 글자가 같으면 다른 문장으로 바꾼다 (같은 되묻기가 세 번 나갔다).
    alternatives는 차례대로 시도한다. 모두 앞 답과 같으면 마지막 것을 쓴다."""
    if not last or _flat_text(reply) != _flat_text(last):
        return reply
    for alt in alternatives:
        if _flat_text(alt) != _flat_text(last):
            return alt
    return alternatives[-1] if alternatives else reply

def clarify_reply(masked: str, last: str | None = None) -> str:
    """B/L도 배 이름도 확정 못 했을 때 되묻는 고정 문장. 식별자는 가린 문장에서 코드가 뽑는다 (LLM 글은 쓰지 않는다).
    가려진 B/L·MRN 토큰은 뽑히지 않으므로 번호가 되돌아가지 않는다. last: 바로 앞 assistant 답. 같은 문장을 두 번 연달아 내지 않는다."""
    m = _ID_LIKE.search(masked)
    reply = CLARIFY_NO_ID if not m else f"'{m.group(0)}'가 B/L 번호인지 배 이름인지 알려 주세요. {CLARIFY_TAIL}"
    return not_same_twice(reply, [CLARIFY_AGAIN, CLARIFY_NO_ID], last)

def _vessel_rows(chosen: list) -> list[dict]:
    """입항 예정 줄(해수부 신고)을 화면이 받는 선박 목록 모양으로. 검색 둘(지역·이름)이 같이 쓴다."""
    return [{
        "ship_name": p.ship_name, "call_sign": p.call_sign, "nationality": p.nationality, "ship_kind": p.ship_kind,
        "previous_port": p.previous_port, "next_port": p.next_port, "purpose": p.purpose,
        "expected_arrival": p.expected_arrival.isoformat() if p.expected_arrival else None, "facility": p.facility,
        # 부산을 떠나는 예정 시각 (입항 신고의 출항 detail). 처음 출발한 항구의 출발 시각은 신고에 없다
        "planned_departure": p.planned_departure.isoformat() if p.planned_departure else None,
        "is_cargo": is_cargo_ship(p.ship_kind, p.purpose),  # 화면 기본값은 이 배들만 (모든 선종 보기로 전체)
    } for p in chosen]

def _arrival_text(iso: str | None) -> str:
    """입항 예정 시각을 "10월 8일 08:00"으로. 시간대가 붙어 있으면 한국 시간으로 바꾼다. 없거나 못 읽으면 빈 글자."""
    if not iso:
        return ""
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    if t.tzinfo:
        t = t.astimezone(timezone(timedelta(hours=9)))  # 한국 시간 (evidence.KST와 같은 값)
    return f"{t.month}월 {t.day}일 {t:%H:%M}"

def _ship_list_lines(vessels: list[dict]) -> str:
    """검색 결과 앞쪽 배를 한 척에 한 줄로 ("· 이름 · 10월 8일 08:00 도착 예정 · 직전 기항지"). 건수만 말하면 "어떤 배냐"를 또 물어야 한다.
    한 문단에 다 붙이면 읽기 힘들어 줄로 나눴다. 말풍선이 줄바꿈을 그대로 보인다 (chat.css.bubble).
    수입 화물선이 있으면 그 배들을, 없으면 전체에서 SHIP_LIST_SHOWN척까지. 값은 해수부 입항 신고 그대로이고 코드가 쓴다 (LLM 문장 아님).
    vessels는 _vessel_rows가 이미 입항 예정 시각순으로 정렬한 목록이다. 비면 빈 글자."""
    picked = [v for v in vessels if v["is_cargo"]] or vessels
    if not picked:
        return ""
    lines = []
    for v in picked[:SHIP_LIST_SHOWN]:
        eta = _arrival_text(v.get("expected_arrival"))
        cols = [str(v["ship_name"]), f"{eta} 도착 예정" if eta else "", v.get("previous_port") or ""]
        lines.append("· " + " · ".join(c for c in cols if c))
    more = len(picked) - SHIP_LIST_SHOWN
    if more > 0:
        lines.append(f"외 {more}척")
    return "\n".join(lines)

def _period_text(days: int) -> str:
    """기간을 사람 말로: 14일은 "2주", 그 밖에는 "N일"."""
    if days == 1:
        return "오늘부터 1일"  # "1일 안에"만 쓰면 내일 하루만 보여 주는 것으로 읽힌다. 오늘부터 하루 안이라고 밝힌다
    return f"{days // 7}주" if days % 7 == 0 else f"{days}일"

# 통관 시기 질문 낱말. 꼬리표는 없어졌지만 화면에 화물이 있을 때 ask_cargo로 다시 묻는 판단(CLEARANCE_HINT)이 쓴다
def _strip_notice(text: str) -> str:
    """답에서 예전 고정 꼬리표 문구를 지운다 (모델이 스스로 쓴 경우). 지운 뒤 양끝 공백을 정리한다."""
    return _OLD_NOTICE.sub("", text).strip()

def is_action_request(masked: str) -> bool:
    """이번 문장이 무언가를 해 달라는 요청인가 (넣어·켜·지켜봐 줘 등). 메모 재질문을 건너뛸 때만 쓴다."""
    return bool(ACTION_ENDING.search(masked) and any(w in masked for w in ACTION_WORDS)) or bool(WATCH_REQUEST.search(masked))

def lookup_fallback(calls: list[dict]) -> str | None:
    """읽기 전용 MCP 도구가 성공했는데 LLM 문장을 쓸 수 없을 때, 결과 값을 코드가 그대로 문장으로 옮긴다.
    도구별 결과 모양은 mcp_server/schemas.py (C4). 모르는 도구나 비어 있는 결과는 건너뛴다. 쓸 것이 하나도 없으면 None."""
    lines = []
    for c in calls:
        r, name = c["result"], c["name"]
        if not isinstance(r, dict):
            continue
        if name == "get_vessel_candidates" and r.get("candidates"):
            found = r["candidates"]
            shown = ", ".join(f"{v.get('name')}({v.get('flag') or '국적 미상'}, 목적지 {v.get('dest') or '미상'})"
                              for v in found[:ARRIVALS_SHOWN])
            lines.append(f"이름이 비슷한 배는 {len(found)}척이에요: {shown}" + (" 등" if len(found) > ARRIVALS_SHOWN else ""))
        elif name == "get_live_position" and r.get("lat") is not None and r.get("lng", r.get("lon")) is not None:
            sog = f", 속력 {round(r['sog'], 1)}노트" if r.get("sog") is not None else ""
            dest = f", 목적지 {r['dest']}" if r.get("dest") else ""
            at = f" ({_fmt_time(r.get('last_time'))} 기준)" if r.get("last_time") else ""
            lines.append(f"현재 위치는 위도 {round(r['lat'], 2)}, 경도 {round(r.get('lng', r.get('lon')), 2)}{sog}{dest}예요.{at}")
        elif name == "get_port_schedule":
            parts = [f"{k} {t}" for k, t in (("입항 예정", _fmt_time(r.get("planned_arrival"))), ("실제 입항", _fmt_time(r.get("actual_arrival")))) if t]
            if parts:
                lines.append("해수부 기록은 " + ", ".join(parts) + (f", 부두는 {r['facility']}" if r.get("facility") else "") + "이에요.")
        elif name == "estimate_distance" and r.get("distance_nm") is not None:
            hours = f", 지금 속력이면 약 {round(r['calc_hours_at_sog'], 1)}시간" if r.get("calc_hours_at_sog") is not None else ""
            lines.append(f"부산까지 남은 거리는 약 {round(r['distance_nm'], 1)}해리{hours}예요.")
    return " ".join(lines) if lines else None

def _tool_error(code: str, message: str) -> dict:
    """도구가 실행되지 못했을 때 LLM에 돌려주는 모양. MCP 도구의 실패 모양과 같다 (SDD 3.4)."""
    return {"error": {"code": code, "message": message, "retryable": False}}

def _reply_violations(reply: str, grounded: str, message: str, earlier: list[str] | None = None,
                      quote: str | None = None, skills_text: str | None = None, copy_allowed: str = "",
                      ) -> list[validate.Violation]:
    """에이전트가 직접 쓴 문장을 화면에 내보내도 되는지 본다. 빈 목록이면 통과 (validate.check_chat_reply + 주입 모양).
    earlier: 앞서 보여 준 답들 (V13 베끼기). quote·skills_text: 도구 없는 실무 답의 근거 조각과 Skill 원문 (V14).
    copy_allowed: V10에 더 허용할 글 (대화에 나온 마스터·포워더 같은 낱말을 쓸 수 있게)."""
    if guard.looks_like_injection(reply):
        return [validate.Violation("V9", "The reply repeats instructions from the input. Answer only the user's question.")]
    return validate.check_chat_reply(reply, grounded, message, earlier, quote, skills_text, copy_allowed=copy_allowed)

def row_need(agent: AgentResponse) -> tuple[str, str] | None:
    """판정을 못 낸 줄(insufficient)이 무엇을 필요로 하는가: (표에 적을 짧은 이유, 답에 넣을 문장 틀). 판정이 났으면 None.
    판정 흐름이 정한 answer 문구로 갈래를 정한다 (같은 이름 되묻기·되묻기 뒤에도 못 가름·결과 없음). 그 밖은 일반 안내."""
    if agent.status != "insufficient":
        return None
    from backend.app.routers import agent as agent_router  # noqa: PLC0415 - 서로 불러오는 순환을 피하려고 쓰는 자리에서 가져온다
    if agent.answer == agent_router.NO_CARGO:
        return ROW_NOTE_NOT_FOUND, ROW_SAY_NOT_FOUND
    if agent.answer == agent_router.ASK_BACK:
        return ROW_NOTE_SAME_NAME.format(n=len(agent.vessel_candidates)), ROW_SAY_SAME_NAME
    if agent.answer == agent_router.ASK_BACK_AFTER_EVIDENCE:
        return ROW_NOTE_SAME_NAME.format(n=len(agent.vessel_candidates)), ROW_SAY_STILL_SAME
    return ROW_NOTE_MORE_INFO, ROW_SAY_MORE_INFO

def _multi_table(found: list[ChatResult]) -> tuple[list[str], list[dict], ChatResult]:
    """B/L 2~3개 조회 결과로 (판정 못 낸 줄마다의 안내 문장, 말풍선 표 줄, 문맥이 될 결과)를 만든다.
    에이전트(_agent_turn)와 전 방식(_classic_cargo)이 같이 쓴다 (점검: 전 방식은 첫 B/L만 보고 나머지를 말없이 버렸다)."""
    # 판정을 못 낸 줄마다 무엇이 필요한지 코드가 한 문장씩 쓴다
    needs = [(r, row_need(r.agent)) for r in found]
    lines = [need[1].format(bl=r.request.bl_no) for r, need in needs if need]
    rows = [{"bl_no": r.request.bl_no, "status": r.agent.status, "verdict": r.agent.verdict,
             "ship_name": r.agent.vessel.name if r.agent.vessel else None,
             "eta": r.agent.eta.trusted_eta if r.agent.eta else None, "days_margin": r.agent.days_margin,
             "sale_due_date": r.request.sale_due_date, "note": need[0] if need else None,
             "agent": r.agent, "request": r.request} for r, need in needs]
    # 문맥(다음 문장의 "이 화물")과 아래 결과 칸은 같은 이름 되묻기가 필요한 줄이 먼저고, 없으면 첫 B/L (화면:
    # 되묻기 줄이 문맥이 아니면 사용자가 "항차 V123"이라고 답해도 엉뚱한 화물에 붙는다). 말풍선 미니 지도는 만들지 않는다: 결과 칸 지도가 대신 보여 준다
    chosen = next((r for r, need in needs if need and r.agent.vessel_candidates), found[0])
    return lines, rows, chosen

def _repeats_reply(text: str, replies: list[str]) -> bool:
    """LLM 문장이 화물 답에 이미 있는 문장을 되풀이하는가. 같은 되묻기가 두 번 나가던 것을 막는다.
    공백을 정리한 뒤 문장 단위로 비교한다. 짧은 문장은 우연히 겹칠 수 있어 12자 이상만 본다 (버그 찾기)"""
    flat = " ".join(" ".join(replies).split())
    sentences = re.split(r"(?<=[.!?。])\s+|\n+", text)
    return any(len(n) >= 12 and n in flat for n in (" ".join(x.split()) for x in sentences))

def _copies_user_marker(resp: AgentResponse, message: str) -> bool:
    """후속 답(resp.answer)이 사용자 원문의 낱말을 근거 없이 옮기거나 원문 조각을 이어 붙였는가 (V10과 같은 기준, validate.copied_words).
    허용 낱말은 답을 뺀 결과와 후속 답 LLM이 받은 Skill·지시문이다 (routers/agent._follow_up의 V10과 같은 출처)."""
    # 판정 흐름이 이미 고정 문구(주입 차단·답 실패)로 답했으면 볼 것이 없다. 고정 문구 낱말이 원문과 겹쳐 잘못 걸리지 않게 뺀다.
    # 함수 안에서 가져온다: routers/agent가 이 모듈을 쓰는 라우터와 같은 앱에 묶여 있어 모듈 머리에서 가져오면 순환이 생길 수 있다
    from backend.app.routers.agent import FOLLOW_UP_BLOCKED, FOLLOW_UP_FAILED

    answer = resp.answer or ""
    if not answer or answer in (FOLLOW_UP_BLOCKED, FOLLOW_UP_FAILED):
        return False
    try:
        reference = llm.skills_reference(llm.FOLLOW_UP_SKILLS, llm.FOLLOW_UP_PROMPT)
    except Exception as e:  # 지시문·Skill 파일을 못 읽어도 답은 막지 않는다. 판정 흐름의 V10은 이미 걸렸다
        log_failure("chat", f"reference unavailable {type(e).__name__}")
        return False
    base = resp.model_copy(update={"answer": ""})
    return bool(validate.check_follow_up_echo(answer, message, base, reference))

def _safe_reply(reply: str | None, message: str) -> str:
    """other 의도의 LLM 안내 문장을 화면에 내보내도 되는지 본다. 안 되면 고정 안내(OTHER_REPLY).

    이 문장은 검증 없이 화면에 바로 간다. 그래서 후속 답 V9·V10과 같은 기준을 건다 (services/judge/validate.py):
    숫자 없음(판정·숫자 없는 짧은 안내, docs/specs/chat-search.md), 정한 것 밖의 영문 낱말 없음,
    사용자 문장에서 옮겨 온 낱말이 안내 문구에 없는 것이면 안 됨, 주입 모양 아님.
    """
    text = (reply or "").strip()
    if not text:
        return NEED_BL
    english = {w.lower() for w in validate.WORD.findall(text)} - _REPLY_WORDS
    if (re.search(r"\d", text) or english or guard.looks_like_injection(text)
            or validate.copied_words(text, message, OTHER_REPLY + validate.SERVICE_WORDS)):
        return OTHER_REPLY
    return text

def _is_no_result(r: ChatResult) -> bool:
    """판정 흐름이 "조회 결과 없음"(routers/agent.NO_CARGO)으로 끝낸 결과인가."""
    from backend.app.routers import agent as agent_router  # noqa: PLC0415 - 서로 불러오는 순환을 피하려고 쓰는 자리에서 가져온다
    return bool(r.agent and r.agent.status == "insufficient" and r.agent.answer == agent_router.NO_CARGO)

def _no_result_text(r: ChatResult, last: str | None) -> str:
    """"조회 결과 없음" 답이 바로 앞 답과 같은 안내면 다른 문장으로 바꾼다. 아니면 reply 그대로.
    같은 조회를 되풀이하면 같은 결과라서, 두 번째부터는 번호 확인과 마스터·하우스 구분 바꾸기를 권한다.
    "지금 쓴 구분"은 요청에 든 값(코드가 아는 값)이고, 권하는 쪽은 그 반대다. 구분을 못 알면 되풀이 방지만 한다."""
    if not _is_no_result(r) or not last or "결과가없어요" not in _flat_text(last):
        return r.reply
    # 하우스·마스터를 둘 다 본 결과(NO_RESULT_BOTH)면 구분을 바꾸라고 권하지 않는다
    tried_both = NOT_FOUND_BOTH in r.agent.missing_inputs
    base = NO_RESULT_BOTH if tried_both else NO_RESULT_REPLY
    if "다시조회해도" in _flat_text(last):  # 세 번째부터는 번호를 다시 받아 오라고 한다. 같은 문장을 세 번 내지 않는다
        return r.reply.replace(base, NO_RESULT_THIRD)
    now = r.request.bl_type if r.request else None
    if tried_both or now not in BL_TYPE_KO:
        return r.reply.replace(base, "같은 번호로 다시 조회해도 결과가 없어요. 번호를 한 글자씩 다시 확인해 주세요.")
    other = "HOUSE" if now == "MASTER" else "MASTER"
    return r.reply.replace(NO_RESULT_REPLY, NO_RESULT_AGAIN.format(now=BL_TYPE_KO[now], other=BL_TYPE_KO[other], other_ko=BL_TYPE_KO[other]))
