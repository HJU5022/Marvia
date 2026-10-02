"""자연어 입력 하나를 받아 알맞은 동작으로 보낸다 (docs/specs/chat-search.md).

순서: B/L 가리기(코드) → 의도 고르기(LLM, route_chat) → 실행(코드).
- cargo·follow_up은 기존 판정 흐름(routers/agent.run_agent)을 그대로 부른다. 판정·근거 규칙은 바뀌지 않는다
- vessel_search는 해수부 입항 예정의 직전 기항지로 거른다. 항구 고르기만 LLM(match_ports)이 목록 안에서 한다
- LLM이 안 되면 규칙으로 대신한다 (EC-01): B/L이 있으면 조회, 없으면 B/L을 물어본다
LLM이 낸 칸은 믿기 전에 다시 본다: bl_ref는 가린 목록 안의 것만, ports는 주어진 목록 안의 것만, days는 1~14.
화물 비서 기억 (docs/specs/memory.md, 10-02 결정 2·4): 의도 구조는 그대로다. 로그인 사용자의 화물 조회 답에는
코드가 쓴 "지난 조회" 한 줄을 붙이고, 가린 사용자 문장을 기억 뽑기 재료로 판정 흐름에 넘긴다 (memory.user_text).
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

import httpx

from backend.app.clients.mof import MofClient, MofError
from backend.app.clients.replay import replay_enabled
from backend.app.observability.logging import log_failure
from backend.app.schemas.agent import AgentRequest, AgentResponse
from backend.app.services import guard, llm, memory, progress, validate
from backend.app.services.rules import load_file

KST = timezone(timedelta(hours=9))
# 수입 화물선 기준(선종·입항 목적) 원본. 코드에 목록을 적지 않는다 (skills/port-busan/cargo-vessels.md, 10-01)
CARGO_RULES_PATH = Path(__file__).resolve().parents[3] / "skills" / "port-busan" / "cargo-vessels.md"


def is_cargo_ship(ship_kind: str | None, purpose: str | None) -> bool:
    """소량 수입 화물을 싣고 내리는 배인가. 선종과 입항 목적이 둘 다 목록에 있어야 한다."""
    rules = load_file(CARGO_RULES_PATH)
    return ship_kind in rules["cargo_ship_kinds"] and purpose in rules["cargo_purposes"]
MESSAGE_MAX = 500          # 입력 문장 상한 (EC-07)
DAYS_DEFAULT, DAYS_MAX = 7, 14  # 입항 예정 검색 기간. 해수부 한 번 조회가 20쪽까지라 길게 잡지 않는다
DEFAULT_BL_TYPE = "HOUSE"  # 구분을 말하지 않으면 House로 조회하고 답에 알린다 (소량 수입자는 보통 House B/L)
CACHE_SEC = 600            # 같은 기간 입항 예정은 10분 동안 다시 받지 않는다

# B/L 모양: 영문·숫자 8~20자, 숫자를 하나 이상 포함 (schemas/agent.py _BL_PATTERN + 일반 영어 단어 제외)
_BL = re.compile(r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{8,20}(?![A-Za-z0-9])")
# 적하목록 관리번호(MRN): 연도 2자리 + 영숫자 8자 + 입항 I/출항 E (docs/specs/mrn-fallback.md). B/L 모양과 겹치므로 먼저 뽑는다
_MRN = re.compile(r"(?<![A-Za-z0-9])([0-9]{2}[A-Za-z0-9]{8}[IEie])(?![A-Za-z0-9])")


def extract_mrn(message: str) -> tuple[str | None, str]:
    """문장에서 MRN 하나를 뽑고 그 자리를 [MRN]으로 바꾼 문장을 돌려준다. MRN은 LLM에 보내지 않는다(코드만 쓴다).
    "MRN" 이름표가 있으면 그 뒤 값을, 없으면 MRN 모양 중 숫자 2자리로 시작하는 첫 값을 쓴다."""
    labeled = re.search(r"MRN\s*[:：]?\s*([0-9]{2}[A-Za-z0-9]{8}[IEie])(?![A-Za-z0-9])", message, re.I)
    m = labeled or _MRN.search(message)
    if not m:
        return None, message
    value = m.group(1)
    return value.upper(), message.replace(value, "[MRN]")

# 예시에 테스트 B/L을 쓰지 않는다. 실제 사용자에게 가짜 번호를 보여 주게 된다 (10-02 화면 용어 점검)
NEED_BL = "조회할 B/L 번호를 문장에 넣어 주세요. 예: (내 B/L 번호) 화물 괜찮아?"
NO_CARGO = "지금 보고 있는 화물이 없습니다. 먼저 B/L 번호로 화물을 조회해 주세요."
LLM_DOWN = "지금은 문장 이해 기능을 쓸 수 없어 B/L 번호가 있는 조회만 됩니다. " + NEED_BL
PREV_PORT_NOTE = ("해수부 입항 신고의 직전 기항지 기준입니다. 출발지 정보는 없어서, 유럽에서 출발한 배도 "
                  "중국·싱가포르 등을 거쳐 오면 그 항구로 나옵니다.")
# 프롬프트 주입 방어 (SDD 7절, 10-01). 아래 두 문구는 LLM이 쓴 문장을 내보낼 수 없을 때 대신 쓰는 고정 안내다
OTHER_REPLY = ("마르비아는 B/L 번호로 화물 상태를 확인하고, 지금 보고 있는 화물에 대한 질문에 답하고, "
               "어디에서 오는 배가 부산에 들어오는지 찾아 드립니다. " + NEED_BL)
INJECTION_REPLY = "문장 속 지시는 따르지 않습니다. " + OTHER_REPLY
_PLACE = re.compile(r"^[A-Za-z][A-Za-z .'\-]{0,39}$")  # match_ports에 넘기는 place: 영문 지명 모양만 (40자까지)
_REPLY_WORDS = {"marvia"}  # other 안내에 쓸 수 있는 영문 낱말. 그 밖의 3글자 이상 영문은 주입 표식으로 본다


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
        plans = client.sailing_plans_all(today, today + timedelta(days=days))  # 쪽을 동시에 받는다
    finally:
        client.close()
    _plans_cache[key] = (time.monotonic(), plans)
    return plans


# ── 항구 고르기 캐시 ──
# 같은 지역을 같은 항구 목록으로 다시 물으면 LLM을 부르지 않는다 (10분, 입항 예정 캐시와 같은 수명).
# 열쇠에 항구 목록을 넣는다: 목록이 바뀌면(새 배가 신고) 새로 고른다
_ports_cache: dict[tuple[str, tuple[str, ...]], tuple[float, list[str]]] = {}


def _match_ports_cached(place: str, available: list[str]) -> list[str]:
    key = (place.strip().lower(), tuple(available))
    hit = _ports_cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SEC:
        return hit[1]
    picked = llm.match_ports(place, available).output.ports
    _ports_cache[key] = (time.monotonic(), picked)
    return picked


def search_vessels(place: str | None, days: int | None, label: str | None = None) -> ChatResult:
    """직전 기항지로 거른 부산 입항 예정 선박. 항구는 LLM이 목록 안에서만 고른다 (EC-04)."""
    days = max(1, min(days or DAYS_DEFAULT, DAYS_MAX))
    name = label or place  # 답에는 사용자가 쓴 말(중국)을, 항구 고르기에는 영어(China)를 쓴다
    progress.step("schedule")
    try:
        plans = _arrivals(days)
    except MofError as e:
        log_failure("chat_vessels", e.code)
        return ChatResult(kind="message", reply="해수부 입항 정보를 지금 가져오지 못했습니다. 잠시 뒤 다시 물어봐 주세요.")
    available = sorted({p.previous_port for p in plans if p.previous_port})
    ports: list[str] = []
    if place:
        progress.step("ports")
        try:
            picked = _match_ports_cached(place, available)
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
        "is_cargo": is_cargo_ship(p.ship_kind, p.purpose),  # 화면 기본값은 이 배들만 (모든 선종 보기로 전체)
    } for p in chosen]
    cargo = sum(v["is_cargo"] for v in vessels)
    if place and not vessels:
        reply = f"앞으로 {days}일 동안 {name} 항구를 직전에 들른 부산 입항 예정 선박은 없습니다. {PREV_PORT_NOTE}"
    elif place:
        reply = (f"앞으로 {days}일 동안 {name}({', '.join(ports)})를 직전에 들른 부산 입항 예정 선박 {len(vessels)}척 중 "
                 f"수입 화물선(컨테이너·일반화물·냉동냉장, 양하)은 {cargo}척입니다. {PREV_PORT_NOTE}")
    else:
        reply = f"앞으로 {days}일 동안 부산 입항 예정 선박 {len(vessels)}척 중 수입 화물선은 {cargo}척입니다. {PREV_PORT_NOTE}"
    return ChatResult(kind="vessels", reply=reply, vessels=vessels, place=name, ports=ports, days=days)


def handle(message: str, session_id: str, context: AgentRequest | None, run_agent,
           user_id: str | None = None) -> ChatResult:
    """문장 하나를 처리한다. run_agent는 routers/agent.run_agent(사용자 묶음 포함)를 부르는 함수다.
    user_id: 로그인 사용자. 있으면 화물 조회 답에 지난 조회 한 줄을 붙인다 (docs/specs/memory.md). 없으면(EC-08) 그대로."""
    message = (message or "").strip()
    if not message:
        raise ChatError("empty")
    if len(message) > MESSAGE_MAX:
        raise ChatError("too_long")
    mrn, message = extract_mrn(message)  # B/L 가리기보다 먼저 (MRN도 B/L 모양이라 [BL]로 잘못 가려진다)
    masked, refs = mask_bls(message)
    # 기억 뽑기 재료는 가린 문장이다. B/L·MRN 원본은 넘기지 않는다 (CLAUDE.md, docs/specs/memory.md 쓰기 흐름 3)
    with memory.user_text(masked):
        return _route(masked, refs, mrn, session_id, context, run_agent, user_id)


def _route(masked: str, refs: dict[str, str], mrn: str | None, session_id: str, context: AgentRequest | None,
           run_agent, user_id: str | None) -> ChatResult:
    """가린 문장을 의도에 맞는 동작으로 보낸다 (handle의 뒷부분). 동작은 10-02 전과 같고 user_id만 화물 조회로 넘긴다."""
    today = datetime.now(KST).date().isoformat()

    # 주입 모양 문장은 LLM에 보내지 않는다 (services/guard.py, SDD 7절 10-01). 후속 질문 경로는 route_chat이 질문을
    # 다시 쓴 뒤에야 routers/agent의 guard를 지나서, 다시 쓰는 과정에서 공격문 모양이 바뀌면 빠져나갈 수 있다. 원문에서 먼저 본다
    if guard.looks_like_injection(masked):
        log_failure("chat", "blocked prompt injection pattern")
        return ChatResult(kind="message", reply=INJECTION_REPLY)

    progress.step("understand")  # 화면에 실제 단계를 알린다 (docs/specs/chat-progress.md)
    try:
        route = llm.route_chat(masked, list(refs), context is not None, today).output
    except llm.LLMError as e:  # EC-01: 규칙으로 대신
        log_failure("chat_route", e.kind)
        if refs:
            return _cargo(next(iter(refs.values())), None, None, session_id, context, run_agent, note=None, mrn=mrn, user_id=user_id)
        return ChatResult(kind="message", reply=LLM_DOWN)

    # 문장에 지금 화물과 다른 B/L이 있으면 의도와 상관없이 새 화물 조회다 (10-01 실측: 화면에 화물이 있으면
    # LLM이 "[BL1] 화물 조회해줘"를 follow_up으로 골라 이전 화물 답과 카드가 나왔다). LLM이 낸 의도를 코드가 덮어쓴다
    new_bls = [bl for bl in refs.values() if context is None or bl != context.bl_no]
    if new_bls and route.intent in ("follow_up", "other"):
        return _cargo(new_bls[0], route.bl_type, _valid_date(route.sale_due_date), session_id, context, run_agent, note=None, mrn=mrn, user_id=user_id)

    if route.intent == "cargo":
        bl = refs.get(route.bl_ref or "") or (next(iter(refs.values())) if refs else None)
        if not bl:
            if context is None:
                return ChatResult(kind="message", reply=NEED_BL)  # EC-02
            bl = context.bl_no
        return _cargo(bl, route.bl_type, _valid_date(route.sale_due_date), session_id, context, run_agent, note=None, mrn=mrn, user_id=user_id)

    if route.intent == "follow_up":
        if context is None:
            return ChatResult(kind="message", reply=NO_CARGO)  # EC-03
        question = (route.question or masked)[:300]  # 후속 질문은 300자 (schemas/agent.py)
        req = context.model_copy(update={"session_id": session_id, "follow_up_question": question,
                                         "resolved_mmsi": None, "voyage_no": None, "forwarder_eta": None})
        resp = run_agent(req)
        return ChatResult(kind="cargo", reply=resp.answer, agent=resp, request=context)

    if route.intent == "vessel_search":
        # place·place_label은 LLM 출력인데 답 문장에 그대로 들어간다. place는 영문 지명 모양만,
        # place_label은 사용자가 실제로 쓴 글자일 때만 쓴다 (10-01 주입 방어). 아니면 버린다
        place = route.place.strip() if route.place else None
        if place and (not _PLACE.match(place) or len(place.split()) > 4 or guard.looks_like_injection(place)):
            place = None  # 지명은 네 낱말까지 ("New South Wales"). 문장이 섞이면 버린다
        label = route.place_label
        if not (label and re.sub(r"\s+", "", label) in re.sub(r"\s+", "", masked)):
            label = None
        return search_vessels(place, route.days, label)

    return ChatResult(kind="message", reply=_safe_reply(route.reply, masked))


def _safe_reply(reply: str | None, message: str) -> str:
    """other 의도의 LLM 안내 문장을 화면에 내보내도 되는지 본다. 안 되면 고정 안내(OTHER_REPLY).

    이 문장은 검증 없이 화면에 바로 간다. 그래서 후속 답 V9·V10과 같은 기준을 건다 (services/validate.py, 10-01):
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


def _cargo(bl: str, bl_type: str | None, sale_due_date: str | None, session_id: str, context: AgentRequest | None,
           run_agent, note: str | None, mrn: str | None = None, user_id: str | None = None) -> ChatResult:
    """B/L 조회. 같은 화물을 다시 물으면 지금 화물의 구분·판매일·MRN을 이어 쓴다.
    MRN이 있으면 세관에 아직 없는 화물도 배 상태까지 볼 수 있다 (docs/specs/mrn-fallback.md).
    로그인 사용자가 이미 조회한 화물이면 답 끝에 "지난 조회(10.01)에서는 ○○였어요." 한 줄을 붙인다 (10-02 결정 4).
    그 줄은 조회 전에 읽은 화물 표 값으로 코드가 쓴다. 응답 칸(C1)은 늘리지 않는다."""
    notes = memory.lookup_notes(user_id, bl)
    same = context is not None and context.bl_no == bl
    kind = bl_type or (context.bl_type if same else None)
    req = AgentRequest(bl_no=bl, bl_type=kind or DEFAULT_BL_TYPE, session_id=session_id,
                       sale_due_date=sale_due_date or (context.sale_due_date if same else None),
                       mrn=mrn or (context.mrn if same else None))
    resp = run_agent(req)
    reply = resp.answer
    if not kind:
        reply = (f"{reply}\n(B/L 구분을 말하지 않아 하우스 B/L(포워더가 발행한 B/L)로 조회했습니다. "
                 "선사가 발행한 마스터 B/L이면 \"마스터로 다시\"라고 말해 주세요.)")
    if notes:
        reply = "\n".join([reply, *notes])
    return ChatResult(kind="cargo", reply=reply, agent=resp, request=req)
