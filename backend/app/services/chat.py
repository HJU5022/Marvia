"""자연어 입력 하나를 받아 알맞은 동작으로 보낸다 (docs/specs/chat-search.md).

순서: B/L 가리기(코드) → 의도 고르기(LLM, route_chat) → 실행(코드).
- cargo·follow_up은 기존 판정 흐름(routers/agent.run_agent)을 그대로 부른다. 판정·근거 규칙은 바뀌지 않는다
- vessel_search는 해수부 입항 예정의 직전 기항지로 거른다. 항구 고르기만 LLM(match_ports)이 목록 안에서 한다
- LLM이 안 되면 규칙으로 대신한다 (EC-01): B/L이 있으면 조회, 없으면 B/L을 물어본다
LLM이 낸 칸은 믿기 전에 다시 본다: bl_ref는 가린 목록 안의 것만, ports는 주어진 목록 안의 것만, days는 1~14.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

from backend.app.clients.mof import MofClient, MofError, MAX_PAGES
from backend.app.clients.replay import replay_enabled
from backend.app.observability.logging import log_failure
from backend.app.schemas.agent import AgentRequest, AgentResponse
from backend.app.services import llm

KST = timezone(timedelta(hours=9))
MESSAGE_MAX = 500          # 입력 문장 상한 (EC-07)
DAYS_DEFAULT, DAYS_MAX = 7, 14  # 입항 예정 검색 기간. 해수부 한 번 조회가 20쪽까지라 길게 잡지 않는다
DEFAULT_BL_TYPE = "HOUSE"  # 구분을 말하지 않으면 House로 조회하고 답에 알린다 (소량 수입자는 보통 House B/L)
CACHE_SEC = 600            # 같은 기간 입항 예정은 10분 동안 다시 받지 않는다

# B/L 모양: 영문·숫자 8~20자, 숫자를 하나 이상 포함 (schemas/agent.py _BL_PATTERN + 일반 영어 단어 제외)
_BL = re.compile(r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{8,20}(?![A-Za-z0-9])")

NEED_BL = "조회할 B/L 번호를 문장에 넣어 주세요. 예: TESTBL01 화물 괜찮아?"
NO_CARGO = "지금 보고 있는 화물이 없습니다. 먼저 B/L 번호로 화물을 조회해 주세요."
LLM_DOWN = "지금은 문장 이해 기능을 쓸 수 없어 B/L 번호가 있는 조회만 됩니다. " + NEED_BL
PREV_PORT_NOTE = ("해수부 입항 신고의 직전 기항지 기준입니다. 출발지 정보는 없어서, 유럽에서 출발한 배도 "
                  "중국·싱가포르 등을 거쳐 오면 그 항구로 나옵니다.")


class ChatError(Exception):
    """kind: too_long / empty."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


@dataclass
class ChatResult:
    kind: str                       # cargo / vessels / message
    reply: str
    agent: AgentResponse | None = None
    request: AgentRequest | None = None
    vessels: list[dict] = field(default_factory=list)
    place: str | None = None
    ports: list[str] = field(default_factory=list)
    days: int | None = None


def mask_bls(message: str) -> tuple[str, dict[str, str]]:
    """문장 속 B/L 모양을 [BL1], [BL2]로 바꾸고 {토큰: 원래 B/L(대문자)}을 돌려준다. LLM은 바뀐 문장만 본다."""
    refs: dict[str, str] = {}

    def swap(m: re.Match) -> str:
        bl = m.group(0).upper()
        for token, value in refs.items():
            if value == bl:
                return token
        token = f"[BL{len(refs) + 1}]"
        refs[token] = bl
        return token

    return _BL.sub(swap, message), refs


def _valid_date(value: str | None) -> str | None:
    """YYYY-MM-DD이고 실제 있는 날짜일 때만. LLM이 만든 날짜를 그대로 믿지 않는다."""
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


# ── 해수부 입항 예정 캐시 ──
_plans_cache: dict[tuple[str, int], tuple[float, list]] = {}


def _arrivals(days: int) -> list:
    """오늘부터 days일 부산 입항 예정. 10분 캐시. 실패하면 MofError."""
    today = datetime.now(KST).date()
    key = (today.isoformat(), days)
    hit = _plans_cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SEC:
        return hit[1]
    # 입항 예정 목록은 공개 정보이고 데모 B/L 3건과 무관하다. 키가 있으면 REPLAY_MODE에서도 실제 해수부를 부른다.
    # 키가 없으면(채점용) 녹화본을 읽는다 (docs/specs/chat-search.md How)
    live = replay_enabled() and os.environ.get("DATA_GO_KR_KEY")
    client = MofClient(transport=httpx.HTTPTransport()) if live else MofClient()
    try:
        plans = client.sailing_plans(today, today + timedelta(days=days), max_pages=MAX_PAGES)
    finally:
        client.close()
    _plans_cache[key] = (time.monotonic(), plans)
    return plans


def search_vessels(place: str | None, days: int | None, label: str | None = None) -> ChatResult:
    """직전 기항지로 거른 부산 입항 예정 선박. 항구는 LLM이 목록 안에서만 고른다 (EC-04)."""
    days = max(1, min(days or DAYS_DEFAULT, DAYS_MAX))
    name = label or place  # 답에는 사용자가 쓴 말(중국)을, 항구 고르기에는 영어(China)를 쓴다
    try:
        plans = _arrivals(days)
    except MofError as e:
        log_failure("chat_vessels", e.code)
        return ChatResult(kind="message", reply="해수부 입항 정보를 지금 가져오지 못했습니다. 잠시 뒤 다시 물어봐 주세요.")
    available = sorted({p.previous_port for p in plans if p.previous_port})
    ports: list[str] = []
    if place:
        try:
            picked = llm.match_ports(place, available).output.ports
            ports = [p for p in picked if p in set(available)]  # 목록 밖 이름은 버린다
        except llm.LLMError as e:
            log_failure("chat_port_match", e.kind)
            # 항구 고르기가 안 되면 글자가 그대로 들어 있는 항구만 (예: "Shanghai" → SHANGHAI)
            ports = [p for p in available if place.upper() in p.upper()]
        chosen = [p for p in plans if p.previous_port in set(ports)]
    else:
        chosen = list(plans)
    chosen.sort(key=lambda p: p.expected_arrival or datetime.max.replace(tzinfo=timezone.utc))
    vessels = [{
        "ship_name": p.ship_name, "call_sign": p.call_sign, "nationality": p.nationality, "ship_kind": p.ship_kind,
        "previous_port": p.previous_port, "next_port": p.next_port, "purpose": p.purpose,
        "expected_arrival": p.expected_arrival.isoformat() if p.expected_arrival else None, "facility": p.facility,
        # 부산을 떠나는 예정 시각 (입항 신고의 출항 detail). 처음 출발한 항구의 출발 시각은 신고에 없다
        "planned_departure": p.planned_departure.isoformat() if p.planned_departure else None,
    } for p in chosen]
    if place and not vessels:
        reply = f"앞으로 {days}일 동안 {name} 항구를 직전에 들른 부산 입항 예정 선박은 없습니다. {PREV_PORT_NOTE}"
    elif place:
        reply = f"앞으로 {days}일 동안 {name}({', '.join(ports)})를 직전에 들른 부산 입항 예정 선박 {len(vessels)}척입니다. {PREV_PORT_NOTE}"
    else:
        reply = f"앞으로 {days}일 동안 부산 입항 예정 선박 {len(vessels)}척입니다. {PREV_PORT_NOTE}"
    return ChatResult(kind="vessels", reply=reply, vessels=vessels, place=name, ports=ports, days=days)


def handle(message: str, session_id: str, context: AgentRequest | None, run_agent) -> ChatResult:
    """문장 하나를 처리한다. run_agent는 routers/agent.run_agent(사용자 묶음 포함)를 부르는 함수다."""
    message = (message or "").strip()
    if not message:
        raise ChatError("empty")
    if len(message) > MESSAGE_MAX:
        raise ChatError("too_long")
    masked, refs = mask_bls(message)
    today = datetime.now(KST).date().isoformat()

    try:
        route = llm.route_chat(masked, list(refs), context is not None, today).output
    except llm.LLMError as e:  # EC-01: 규칙으로 대신
        log_failure("chat_route", e.kind)
        if refs:
            return _cargo(next(iter(refs.values())), None, None, session_id, context, run_agent, note=None)
        return ChatResult(kind="message", reply=LLM_DOWN)

    if route.intent == "cargo":
        bl = refs.get(route.bl_ref or "") or (next(iter(refs.values())) if refs else None)
        if not bl:
            if context is None:
                return ChatResult(kind="message", reply=NEED_BL)  # EC-02
            bl = context.bl_no
        return _cargo(bl, route.bl_type, _valid_date(route.sale_due_date), session_id, context, run_agent, note=None)

    if route.intent == "follow_up":
        if context is None:
            return ChatResult(kind="message", reply=NO_CARGO)  # EC-03
        question = (route.question or masked)[:300]  # 후속 질문은 300자 (schemas/agent.py)
        req = context.model_copy(update={"session_id": session_id, "follow_up_question": question,
                                         "resolved_mmsi": None, "voyage_no": None, "forwarder_eta": None})
        resp = run_agent(req)
        return ChatResult(kind="cargo", reply=resp.answer, agent=resp, request=context)

    if route.intent == "vessel_search":
        return search_vessels(route.place, route.days, route.place_label)

    return ChatResult(kind="message", reply=route.reply.strip() or NEED_BL)


def _cargo(bl: str, bl_type: str | None, sale_due_date: str | None, session_id: str, context: AgentRequest | None,
           run_agent, note: str | None) -> ChatResult:
    """B/L 조회. 같은 화물을 다시 물으면 지금 화물의 구분·판매일을 이어 쓴다."""
    same = context is not None and context.bl_no == bl
    kind = bl_type or (context.bl_type if same else None)
    req = AgentRequest(bl_no=bl, bl_type=kind or DEFAULT_BL_TYPE, session_id=session_id,
                       sale_due_date=sale_due_date or (context.sale_due_date if same else None))
    resp = run_agent(req)
    reply = resp.answer
    if not kind:
        reply = f"{reply}\n(구분을 말하지 않아 House B/L로 조회했습니다. Master라면 \"마스터로 다시\"라고 말해 주세요.)"
    return ChatResult(kind="cargo", reply=reply, agent=resp, request=req)
