"""자연어 입력 하나를 받아 알맞은 동작으로 보낸다 (docs/specs/chat-search.md).

순서: B/L 가리기(코드) → 에이전트(LLM이 도구를 골라 부른다, _agent) → 답 검사(코드).
에이전트가 안 되면(키 없음, 도구를 거절하는 모델, CHAT_AGENT=off) 전 방식으로 간다: 의도 고르기(LLM, route_chat) → 실행(코드).
- cargo·follow_up은 기존 판정 흐름(routers/agent.run_agent)을 그대로 부른다. 판정·근거 규칙은 바뀌지 않는다
- vessel_search는 해수부 입항 예정의 직전 기항지로 거른다. 항구 고르기만 LLM(match_ports)이 목록 안에서 한다
- LLM이 안 되면 규칙으로 대신한다 (EC-01): B/L이 있으면 조회, 없으면 B/L을 물어본다
LLM이 낸 칸은 믿기 전에 다시 본다: bl_ref는 가린 목록 안의 것만, ports는 주어진 목록 안의 것만, days는 1~14.
화물 비서 기억 (docs/specs/memory.md, 10-02 결정 2·4): 의도 구조는 그대로다. 로그인 사용자의 화물 조회 답에는
코드가 쓴 "지난 조회" 한 줄을 붙이고, 가린 사용자 문장을 기억 뽑기 재료로 판정 흐름에 넘긴다 (memory.user_text).
채팅 에이전트 (10-05 결정): 의도 넷에 안 맞는 실무 질문이 전부 고정 안내로 가고, 앞 대화를 몰라 "이건"을 못 알아듣던 문제를 고친다.
도구는 화물 조회·화물 질문·입항 선박 검색과 읽기 전용 MCP 도구다. 등급·여유 일수는 지금처럼 판정 흐름(코드)이 정한다.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

import httpx

from backend.app.clients.mof import MofClient, MofError
from backend.app.clients.replay import replay_enabled
from backend.app.observability.logging import log_failure
from backend.app.schemas.agent import AgentRequest, AgentResponse
from backend.app.services import guard, llm, mcp_client, memory, progress, validate
from backend.app.services.rules import load_file

KST = timezone(timedelta(hours=9))
# cargo.previous_line이 만드는 줄의 머리 ("지난 조회(10.01)에서는 ..."). 채팅 답에 붙는 기억 줄은 이것 하나뿐이다 (10-02 결정 4, D1)
PREVIOUS_LINE_PREFIX = "지난 조회("
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
        if _is_date_digits(bl):  # "20261010 도착이래" 같은 날짜를 B/L로 조회하지 않게 (10-05 검토)
            return m.group(0)
        for token, value in refs.items():
            if value == bl:
                return token
        token = f"[BL{len(refs) + 1}]"
        refs[token] = bl
        return token

    return _BL.sub(swap, message), refs


def _valid_date(value: str | None) -> str | None:
    """YYYY-MM-DD이고 실제 있는 날짜일 때만. LLM이 만든 날짜를 그대로 믿지 않는다."""
    if not value or not isinstance(value, str):  # 도구 인자는 strict 스키마가 아니라 숫자·목록이 올 수 있다 (10-05 검토)
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
           user_id: str | None = None, history: list[dict] | None = None,
           run_tool: Callable[[str, dict], dict] | None = None) -> ChatResult:
    """문장 하나를 처리한다. run_agent는 routers/agent.run_agent(사용자 묶음 포함)를 부르는 함수다.
    user_id: 로그인 사용자. 있으면 화물 조회 답에 지난 조회 한 줄을 붙인다 (docs/specs/memory.md). 없으면(EC-08) 그대로.
    history: 화면이 보낸 최근 대화 [{"role", "text"}]. 에이전트가 "이건", "그 배"를 알아듣는 데만 쓴다 (10-05).
    run_tool: 읽기 전용 MCP 도구를 실제로 부르는 함수 (routers/agent._follow_up_tool). 없으면 에이전트는 MCP 도구 없이 돈다."""
    message = (message or "").strip()
    if not message:
        raise ChatError("empty")
    if len(message) > MESSAGE_MAX:
        raise ChatError("too_long")
    mrn, message = extract_mrn(message)  # B/L 가리기보다 먼저 (MRN도 B/L 모양이라 [BL]로 잘못 가려진다)
    masked, refs = mask_bls(message)
    # 기억 뽑기 재료는 가린 문장이다. B/L·MRN 원본은 넘기지 않는다 (CLAUDE.md, docs/specs/memory.md 쓰기 흐름 3)
    with memory.user_text(masked):
        return _route(masked, refs, mrn, session_id, context, run_agent, user_id, history or [], run_tool)


def _route(masked: str, refs: dict[str, str], mrn: str | None, session_id: str, context: AgentRequest | None,
           run_agent, user_id: str | None, history: list[dict] | None = None,
           run_tool: Callable[[str, dict], dict] | None = None) -> ChatResult:
    """가린 문장을 처리한다 (handle의 뒷부분). 에이전트가 먼저 맡고, 안 되면 의도 분류 방식(_classic)으로 간다."""
    today = datetime.now(KST).date().isoformat()

    # 주입 모양 문장은 LLM에 보내지 않는다 (services/guard.py, SDD 7절 10-01). 후속 질문 경로는 route_chat이 질문을
    # 다시 쓴 뒤에야 routers/agent의 guard를 지나서, 다시 쓰는 과정에서 공격문 모양이 바뀌면 빠져나갈 수 있다. 원문에서 먼저 본다
    if guard.looks_like_injection(masked):
        log_failure("chat", "blocked prompt injection pattern")
        return ChatResult(kind="message", reply=INJECTION_REPLY)

    progress.step("understand")  # 화면에 실제 단계를 알린다 (docs/specs/chat-progress.md)
    if agent_enabled():
        try:
            return _agent(masked, refs, mrn, session_id, context, run_agent, user_id, history or [], run_tool, today)
        except llm.LLMError as e:
            # 에이전트가 첫 도구를 쓰기도 전에 실패했다 (키 없음, 도구를 붙이면 거절하는 모델·제공사 등).
            # 전 방식은 도구 없이 한 번 묻는 호출이라 이런 경우에도 된다 (10-02 실측: 도구를 붙이면 404인 제공사가 있었다)
            log_failure("chat_agent", e.kind)
    return _classic(masked, refs, mrn, session_id, context, run_agent, user_id, today)


def _classic(masked: str, refs: dict[str, str], mrn: str | None, session_id: str, context: AgentRequest | None,
             run_agent, user_id: str | None, today: str) -> ChatResult:
    """의도 분류 방식 (10-05 전의 _route 뒷부분 그대로). LLM이 의도 하나와 칸을 고르고 코드가 실행한다.
    에이전트를 못 쓸 때의 대비 경로이고, CHAT_AGENT=off면 이 길만 탄다."""
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


# ── 채팅 에이전트 (10-05 결정) ─────────────────────────────────────
# LLM이 아래 도구를 골라 부르고 결과를 본 뒤 다음 도구를 또 고른다 (llm.chat_agent, 상한 llm.MAX_TOOL_ROUNDS).
# 도구 실행과 답 조립은 여기서 한다. 지키는 것은 전 방식과 같다:
#   B/L은 가린 토큰으로만 오가고 코드가 원래 번호로 바꾼다 · 등급과 여유 일수는 판정 흐름이 정한다 ·
#   LLM이 낸 칸(구분·날짜·지명)은 쓰기 전에 다시 본다 · 화면에 가는 문장은 검증된 것만

CARGO_CALLS_PER_TURN = 1  # 한 문장에서 화물 조회·화물 질문은 한 번만. 화면 카드는 하나이고, 한 번에 판정 흐름 여러 개가 돌면 비용·지연이 커진다 (10-05 검토)
DATE_HINTS = ("오늘", "내일", "모레", "글피", "다음", "이번", "주", "월", "일")  # 포워더 도착일을 사용자가 말했다고 볼 낱말 (숫자가 없을 때)
FAILED_LOOKUP = "조회하지 못했습니다. 잠시 뒤 다시 물어봐 주세요."  # 고른 도구가 모두 실패했을 때
HISTORY_TURNS = 6  # LLM에 넘길 최근 대화 줄 수. "이건", "그 배"가 가리키는 것은 보통 바로 앞 두세 턴에 있다
ARRIVALS_SHOWN = 8  # 입항 선박 검색 결과 중 LLM에 돌려줄 척 수. 전체 표는 화면이 그린다
# 읽기 전용 도구 결과를 문장으로 못 옮겼을 때 (검사에 걸렸거나 답이 비었을 때). 틀린 문장을 내보내지 않는다
LOOKUP_NOT_SUMMARIZED = "조회는 했지만 결과를 문장으로 정리하지 못했습니다. 다시 물어봐 주세요."
# 도구 없는 실무 질문인데 Skill 문서로 받칠 수 없을 때 (answer_kind=not_in_skills, 또는 근거 조각 검사 V14에 끝내 걸렸을 때).
# 도메인 조언은 제품 담당이 쓴 skills/*.md에서만 나온다. 문서에 없으면 지어내지 않고 없다고 말한다 (10-05 실측)
NOT_IN_SKILLS = "그 내용은 마르비아가 가진 자료에 없습니다. " + OTHER_REPLY
# 화면에 화물이 있는데 도구 없이 안내만 냈을 때 한 번 다시 물으며 붙이는 말 (10-05 실측: "이 배 지금 어디쯤이야?"에 ask_cargo를 안 불렀다)
CARGO_ON_SCREEN_HINT = ("You called no tool. has_current_cargo is true. If the message asks about this ship or this cargo "
                        "(where it is, when it arrives, customs, what to do), call ask_cargo. If it asks which ships come "
                        "from a place, call search_arrivals. Otherwise answer as before.")
# MCP 도구 → 화면 단계 이름 (services/progress.py STAGES, web/lib/progress.ts). 에이전트가 고른 도구가 화면에 실제 순서로 보인다
MCP_STAGES = {"get_vessel_candidates": "tool_candidates", "get_live_position": "tool_position",
              "get_port_schedule": "tool_schedule", "estimate_distance": "tool_distance"}
# 에이전트가 고를 수 있는 Marvia 도구 (OpenAI 도구 형식). MCP 도구 설명처럼 도구 설명은 도구 옆에 둔다.
# 언제 무엇을 쓰는지의 규칙은 프롬프트(marvia-chat-agent)에 있다
AGENT_TOOLS = [
    {"type": "function", "function": {
        "name": "check_cargo",
        "description": "Look up one cargo by its B/L token and assess it. Call at most once per message. Returns status, verdict, days_margin, vessel and the answer shown to the user.",
        "parameters": {"type": "object", "properties": {
            "bl_ref": {"type": ["string", "null"], "description": "A token from bl_refs such as [BL1]. null means the B/L in this message, or the cargo on screen if the message has none."},
            "bl_type": {"type": ["string", "null"], "enum": ["MASTER", "HOUSE", None], "description": "Only if the user says master or house."},
            "sale_due_date": {"type": ["string", "null"], "description": "YYYY-MM-DD, only if the user gives a sale or needed-by date."},
            "forwarder_eta": {"type": ["string", "null"], "description": "YYYY-MM-DD, the Busan arrival date the forwarder told the user."},
            "voyage_no": {"type": ["string", "null"], "description": "Voyage number exactly as the user typed it."},
        }, "required": ["bl_ref"]}}},
    {"type": "function", "function": {
        "name": "ask_cargo",
        "description": "Answer a question about the cargo already on screen, from its assessment result. Do not call it in a message where check_cargo ran.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "The question as one short Korean sentence, self-contained."},
        }, "required": ["question"]}}},
    {"type": "function", "function": {
        "name": "search_arrivals",
        "description": "List ships expected at Busan, optionally filtered by the last port they called at.",
        "parameters": {"type": "object", "properties": {
            "place": {"type": ["string", "null"], "description": "Where the ships come from, in English (country or port). null for all."},
            "place_label": {"type": ["string", "null"], "description": "The same place as the user wrote it."},
            "days": {"type": ["integer", "null"], "description": "How many days ahead (1 to 14)."},
        }, "required": ["place"]}}},
]


def agent_enabled() -> bool:
    """채팅 에이전트를 쓰는가. 기본은 켜짐. CHAT_AGENT=off면 의도 분류 방식만 쓴다 (.env.example, 시연 중 문제가 생기면 값 하나로 되돌린다)."""
    return os.environ.get("CHAT_AGENT", "on").strip().lower() not in ("0", "off", "false", "no")


def _masked_history(history: list[dict], refs: dict[str, str]) -> list[dict]:
    """화면이 보낸 최근 대화를 LLM에 넘길 모양으로 만든다. B/L·MRN을 가리고 주입 모양 줄은 뺀다.
    화면이 보낸 값이라 assistant 줄도 우리가 쓴 글이라고 믿지 않는다 (SDD 7절 신뢰 경계). LLM에는 자료로만 간다."""
    turns = []
    for turn in history[-HISTORY_TURNS:]:
        role, text = turn.get("role"), (turn.get("text") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue
        # 가린 뒤에 자른다. 먼저 자르면 경계에 걸린 B/L 앞부분(8자 미만)이 가려지지 않고 LLM에 간다 (10-05 테스트에서 발견)
        text, _ = mask_bls(_MRN.sub("[MRN]", text), refs)
        text = text[:MESSAGE_MAX]
        if guard.looks_like_injection(text):
            continue
        turns.append({"role": role, "text": text})
    return turns


def _cargo_summary(resp: AgentResponse) -> dict:
    """화물 조회 결과 중 LLM에 돌려줄 부분. 다음 도구를 고르는 데 필요한 것만 준다 (배 이름·MMSI·호출부호, 도착 예정).
    근거 카드와 통관 정보는 뺀다: 자세한 질문은 ask_cargo가 지난 결과 전체로 답한다. B/L은 응답에 없다."""
    return resp.model_dump(mode="json", include={"status", "verdict", "days_margin", "missing_inputs", "vessel", "eta", "answer"})


def _tool_error(code: str, message: str) -> dict:
    """도구가 실행되지 못했을 때 LLM에 돌려주는 모양. MCP 도구의 실패 모양과 같다 (SDD 3.4)."""
    return {"error": {"code": code, "message": message, "retryable": False}}


def _reply_violations(reply: str, grounded: str, message: str, earlier: list[str] | None = None,
                      quote: str | None = None, skills_text: str | None = None) -> list[validate.Violation]:
    """에이전트가 직접 쓴 문장을 화면에 내보내도 되는지 본다. 빈 목록이면 통과 (validate.check_chat_reply + 주입 모양).
    earlier: 앞서 보여 준 답들 (V13 베끼기). quote·skills_text: 도구 없는 실무 답의 근거 조각과 Skill 원문 (V14)."""
    if guard.looks_like_injection(reply):
        return [validate.Violation("V9", "The reply repeats instructions from the input. Answer only the user's question.")]
    return validate.check_chat_reply(reply, grounded, message, earlier, quote, skills_text)


def _agent(masked: str, refs: dict[str, str], mrn: str | None, session_id: str, context: AgentRequest | None,
           run_agent, user_id: str | None, history: list[dict], run_tool: Callable[[str, dict], dict] | None,
           today: str) -> ChatResult:
    """에이전트 한 턴. LLM이 고른 도구를 실행하고, 끝나면 화면에 보낼 결과 하나로 묶는다.

    답 조립 (틀린 문장을 내보내지 않는 쪽으로):
    - 화물 조회·화물 질문·선박 검색이 돌았으면 그 답을 그대로 쓴다. 판정 흐름과 코드가 이미 검증한 문장이다.
      읽기 전용 도구도 같이 썼을 때만 LLM 문장을 검사해 뒤에 붙인다
    - 읽기 전용 도구만 썼으면 LLM 문장을 검사해 내보낸다. 걸리면 정리하지 못했다고 한다
    - 도구를 안 썼으면 실무 질문 답이거나 안내다. 실무 답(answer_kind=skill)은 Skill 원문 근거 조각(skill_quote)이 원문에
      그대로 있어야 내보낸다 (V14). 안내는 LLM 문장 대신 고정 문구를 쓴다. 앞 답을 베꼈거나(V13) 화면에 화물이 있는데
      도구를 안 불렀으면 한 번 다시 묻는다 (10-05 실측)
    LLM이 첫 도구 전에 실패하면 LLMError를 그대로 올린다 (_route가 전 방식으로 보낸다). 도구가 이미 돌았으면
    그 결과로 답한다: 전 방식으로 넘기면 같은 조회를 한 번 더 하게 된다.
    """
    message_bls = list(refs.values())  # 이번 문장에 든 B/L (대화 기록의 것은 아래에서 refs에 더해진다)
    # 복사본에 대화 기록의 B/L을 더한다. 원본을 고치면 에이전트가 실패해 전 방식으로 갈 때 기록의 B/L을
    # 이번 문장의 B/L로 착각해 엉뚱한 화물을 조회한다 (10-05 검토)
    refs = dict(refs)
    turns = _masked_history(history, refs)
    # 답 검사에서 "사용자가 쓴 글"로 칠 것: 이번 문장과 앞에서 사용자가 쓴 줄. 사용자가 앞 턴에 말한 날짜를 되짚는 답이
    # V7에 걸리지 않게 한다. assistant 줄은 넣지 않는다 (V10이 우리 답의 낱말을 사용자 글로 오해하지 않게)
    user_text = " ".join([masked, *(t["text"] for t in turns if t["role"] == "user")])
    mcp_tools = mcp_client.read_only_tools() if run_tool else []
    mcp_names = {t["function"]["name"] for t in mcp_tools}
    done: list[ChatResult] = []  # 화물 조회·화물 질문·선박 검색 결과. 화면 카드와 검증된 답을 들고 있다
    ran: list[dict] = []  # 실제로 실행한 도구와 결과 {"name","arguments","result"}. LLM이 도중에 실패해도 남는다
    seen: dict[str, dict] = {}  # 같은 도구·같은 인자는 다시 실행하지 않고 앞 결과를 돌려준다 (프롬프트 규칙을 코드로)
    # 사용자가 이번 문장이나 앞 줄에서 날짜를 말했는가. 포워더 도착일은 판정 근거(trusted_eta)가 되므로
    # LLM이 지어낸 날짜를 받지 않으려고 본다 (10-05 검토, CLAUDE.md trusted_eta)
    user_gave_date = bool(re.search(r"\d", user_text)) or any(w in user_text for w in DATE_HINTS)

    def run(name: str, args: dict) -> dict:
        """LLM이 고른 도구 하나를 실행한다. 같은 호출은 한 번만, 화물 도구는 한 문장에 한 번만, 예외는 도구 실패로 돌려준다.
        MCP 도구가 예외를 던지지 않는 것과 같은 원칙이다 (SDD 3.4): 도구 하나가 죽어도 요청 전체가 500이 되면 안 된다."""
        key = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}"
        if key in seen:
            return seen[key]
        if name in ("check_cargo", "ask_cargo") and sum(r["name"] in ("check_cargo", "ask_cargo") for r in ran) >= CARGO_CALLS_PER_TURN:
            # 조회한 화물에 바로 이어 묻는 경우도 여기서 막힌다: ask_cargo는 화면의 지난 화물을 보므로 방금 조회한 화물과 다를 수 있다
            result = _tool_error("one_cargo_per_message", "The cargo answer for this message is already shown. Do not call another cargo tool.")
        else:
            try:
                result = _run_tool(name, args)
            except Exception as e:  # noqa: BLE001 - 모델이 낸 인자 모양이 예상과 달라도 요청을 죽이지 않는다
                log_failure("chat_agent_tool", f"{name} {type(e).__name__}")
                result = _tool_error("tool_failed", "This lookup failed.")
        seen[key] = result
        ran.append({"name": name, "arguments": args, "result": result})
        return result

    def _run_tool(name: str, args: dict) -> dict:
        """도구 하나의 실제 실행. 칸 검사는 전 방식(_classic)과 같은 기준이다."""
        if name == "check_cargo":
            token = args.get("bl_ref")
            if token is not None and not isinstance(token, str):  # 모델이 목록 등 다른 모양을 보내면 요청이 죽지 않게 도구 실패로 돌려준다
                return _tool_error("need_bl", NEED_BL)
            bl = refs.get(token) if token else (message_bls[0] if message_bls else (context.bl_no if context else None))
            if not bl:  # 목록에 없는 토큰이거나 조회할 화물이 없다 (EC-02). 번호를 지어내도 여기서 막힌다
                return _tool_error("need_bl", NEED_BL)
            bl_type = args.get("bl_type") if args.get("bl_type") in ("MASTER", "HOUSE") else None
            # 항차 번호는 사용자가 실제로 쓴 글자일 때만 쓴다. LLM이 만든 값으로 배를 가르면 안 된다
            voyage = str(args.get("voyage_no") or "").strip() or None
            if voyage and re.sub(r"\s+", "", voyage) not in re.sub(r"\s+", "", masked):
                voyage = None
            eta = _valid_date(args.get("forwarder_eta")) if user_gave_date else None
            result = _cargo(bl, bl_type, _valid_date(args.get("sale_due_date")), session_id, context, run_agent,
                            note=None, mrn=mrn, user_id=user_id, voyage_no=voyage, forwarder_eta=eta)
            if eta:  # LLM이 풀어낸 날짜라 사용자가 맞는지 볼 수 있게 답에 밝힌다 (근거 카드에도 있다, services/evidence.py)
                result = replace(result, reply=f"{result.reply}\n(포워더가 알려 준 입항일 {eta}로 조회했습니다.)")
            done.append(result)
            return _cargo_summary(result.agent)
        if name == "ask_cargo":
            if context is None:
                return _tool_error("no_cargo", NO_CARGO)  # EC-03
            question = str(args.get("question") or masked)[:300]  # 후속 질문은 300자 (schemas/agent.py)
            req = context.model_copy(update={"session_id": session_id, "follow_up_question": question,
                                             "resolved_mmsi": None, "voyage_no": None, "forwarder_eta": None})
            resp = run_agent(req)
            done.append(ChatResult(kind="cargo", reply=resp.answer, agent=resp, request=context))
            return {"answer": resp.answer}
        if name == "search_arrivals":
            # place·place_label은 LLM 출력인데 답 문장에 그대로 들어간다. 전 방식과 같은 검사를 한다 (10-01 주입 방어)
            place = str(args.get("place") or "").strip() or None
            if place and (not _PLACE.match(place) or len(place.split()) > 4 or guard.looks_like_injection(place)):
                place = None
            label = args.get("place_label")
            if not (isinstance(label, str) and label and re.sub(r"\s+", "", label) in re.sub(r"\s+", "", masked)):
                label = None
            # bool도 int라서 따로 막는다 (true가 "앞으로 True일"로 답에 들어갔다, 10-05 테스트에서 발견)
            days = args.get("days") if isinstance(args.get("days"), int) and not isinstance(args.get("days"), bool) else None
            result = search_vessels(place, days, label)
            done.append(result)
            shown = [{k: v[k] for k in ("ship_name", "call_sign", "nationality", "previous_port", "expected_arrival", "is_cargo")}
                     for v in result.vessels[:ARRIVALS_SHOWN]]
            return {"reply": result.reply, "total": len(result.vessels), "vessels": shown}
        if name in mcp_names:
            progress.step(MCP_STAGES.get(name, ""))  # 모르는 도구 이름이면 단계를 보내지 않는다 (progress.step)
            return run_tool(name, args)
        log_failure("chat_agent_tool", f"unknown_tool {name}")
        return _tool_error("unknown_tool", f"no tool named {name}")

    tools = AGENT_TOOLS + mcp_tools
    skills = llm.skills_reference(llm.CHAT_AGENT_SKILLS)  # V14 근거 조각을 찾는 원문. 지시문은 넣지 않는다 (도메인 지식의 출처가 아니다)
    reference = llm.skills_reference(llm.CHAT_AGENT_SKILLS, llm.CHAT_AGENT_PROMPT) + " " + today
    grounded = reference + OTHER_REPLY  # 도구 없는 답의 V7·V9·V10 근거. OTHER_REPLY의 낱말은 써도 된다
    # 이 대화에서 앞서 보여 준 답. 같은 답을 되풀이하면 이번 질문을 처리하지 않은 것이다 (V13, 10-05 실측)
    earlier = [t["text"] for t in turns if t["role"] == "assistant"]

    def no_tool_violations(out: llm.ChatAgentOutput, text: str, first: bool) -> list[validate.Violation]:
        """도구 없이 낸 답을 다시 물어야 하는 이유. 빈 목록이면 그대로 결론을 낸다 (아래 no_tool_reply)."""
        if out.answer_kind == "skill":
            return _reply_violations(text, grounded, user_text, earlier, out.skill_quote, skills) if text else []
        if out.answer_kind == "tool" and first:  # 도구 없이 "도구를 썼다"고 냈다 (10-05 실측). 도구를 부르라고 한 번 다시 묻는다
            return [validate.Violation("TOOL", "You set answer_kind to tool but called no tool. Call the tool this message "
                                               "needs now, then answer. If no tool fits, use another answer_kind.")]
        # 안내(not_in_skills·unrelated)는 LLM 문장을 화면에 내지 않는다 (고정 문구). 그래도 다시 물을 때가 있다:
        # 앞 답을 베꼈거나(V13, "중국에서 오는 배"에 포워더 설명을 되풀이), 화면에 화물이 있는데 도구를 안 불렀을 때(10-05 실측)
        found = [v for v in _reply_violations(text, grounded, user_text, earlier) if v.rule == "V13"] if text else []
        if first and context is not None and not found:
            found.append(validate.Violation("TOOL", CARGO_ON_SCREEN_HINT))
        return found

    # 첫 답 + 다시 묻기 한 번. 다시 물을 때도 도구를 준다: 도구가 아직 하나도 안 돌았으므로 같은 조회를 두 번 하지 않는다.
    # 베낀 답·화물 질문은 다시 물어 도구를 부르게 하는 것이 고치는 길이다 (10-05 실측)
    out, text, violations, feedback = None, "", [], None
    for attempt in range(2):
        try:
            answer = llm.chat_agent(masked, list(refs), context is not None, today, turns, tools, run, feedback=feedback)
            out, text = answer.output, (answer.output.reply or "").strip()
        except llm.LLMError as e:
            if attempt == 0 and not ran:  # 아무 도구도 안 돌았다: 전 방식이 같은 일을 처음부터 한다
                raise
            # 도구가 돌았으면 그 결과로 끝낸다. 전 방식으로 넘기면 같은 조회를 한 번 더 한다 (10-05 검토)
            log_failure("chat_agent", f"{e.kind} after tools" if ran else f"{e.kind} on retry")
            if ran:
                text = ""  # 도구 결과만으로 답한다
            break  # 도구 없이 다시 묻기가 실패했으면 첫 답과 그 위반으로 아래에서 고정 문구를 고른다
        if ran:
            break  # 도구가 돌았다: 아래에서 도구 결과로 답을 조립한다
        violations = no_tool_violations(out, text, attempt == 0)
        if not violations:
            break
        log_failure("chat_agent_reply", ",".join(v.rule for v in violations))
        feedback = "\n".join(f"{v.rule}: {v.detail}" for v in violations)
    calls = ran

    # 문장에 지금 화물과 다른 B/L이 있는데 에이전트가 조회하지 않았으면 코드가 조회한다 (전 방식의 10-01 규칙과 같다:
    # B/L을 넣었는데 다른 화물 답이 나오면 안 된다)
    new_bls = [bl for bl in message_bls if context is None or bl != context.bl_no]
    checked = {r.request.bl_no for r in done if r.kind == "cargo" and r.request}
    if new_bls and not checked.intersection(new_bls):
        done.append(_cargo(new_bls[0], None, None, session_id, context, run_agent, note=None, mrn=mrn, user_id=user_id))

    looked_up = [c for c in calls if c["name"] in mcp_names and "error" not in (c["result"] or {})]
    lookups = " ".join(str(c["result"]) for c in looked_up)
    if done:
        replies = list(dict.fromkeys(r.reply for r in done))  # 같은 답이 두 번 붙지 않게
        if looked_up and text and not _reply_violations(text, reference + lookups + " ".join(replies), user_text, earlier):
            replies.append(text)
        return replace(done[-1], reply="\n\n".join(replies))
    if looked_up:
        ok = bool(text) and not _reply_violations(text, reference + lookups, user_text, earlier)
        return ChatResult(kind="message", reply=text if ok else LOOKUP_NOT_SUMMARIZED)
    if calls:
        # 도구를 골랐는데 모두 실패했다. LLM 문장 대신 코드가 무엇이 안 됐는지 말한다 (EC-02·EC-03 고정 안내 유지, 10-05 검토)
        codes = [c["result"]["error"]["code"] for c in calls if isinstance(c["result"], dict) and "error" in c["result"]]
        fixed = {"need_bl": NEED_BL, "no_cargo": NO_CARGO}
        return ChatResult(kind="message", reply=next((fixed[c] for c in codes if c in fixed), FAILED_LOOKUP))

    # 도구를 하나도 쓰지 않았다. LLM 문장을 내보내는 것은 Skill 근거 조각까지 검사를 통과한 실무 답(skill)뿐이다.
    # 나머지는 코드의 고정 문구다: 문서에 없는 질문은 없다고(NOT_IN_SKILLS), 상관없는 말은 할 수 있는 일(OTHER_REPLY)
    if out is None or not text:
        return ChatResult(kind="message", reply=OTHER_REPLY)
    if out.answer_kind == "skill":
        return ChatResult(kind="message", reply=NOT_IN_SKILLS if violations else text)
    return ChatResult(kind="message", reply=NOT_IN_SKILLS if out.answer_kind == "not_in_skills" else OTHER_REPLY)


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
           run_agent, note: str | None, mrn: str | None = None, user_id: str | None = None,
           voyage_no: str | None = None, forwarder_eta: str | None = None) -> ChatResult:
    """B/L 조회. 같은 화물을 다시 물으면 지금 화물의 구분·판매일·MRN을 이어 쓴다.
    MRN이 있으면 세관에 아직 없는 화물도 배 상태까지 볼 수 있다 (docs/specs/mrn-fallback.md).
    로그인 사용자가 이미 조회한 화물이면 답 끝에 "지난 조회(10.01)에서는 ○○였어요." 한 줄을 붙인다 (10-02 결정 4).
    그 줄은 조회 전에 읽은 화물 표 값으로 코드가 쓴다. 응답 칸(C1)은 늘리지 않는다.
    voyage_no·forwarder_eta: 되묻기에 사용자가 문장으로 답한 값 (10-05, 에이전트만 넘긴다). 전에는 화면의 칸으로만 받았다."""
    # 답에 붙일 수 있는 것은 코드가 쓴 "지난 조회" 한 줄뿐이다 (10-02 결정 4, D1). lookup_notes가 다른 줄(메모장 가득 참 알림 등)을
    # 돌려줘도 사용자에게 보이지 않게 여기서 한 번 더 거른다. 가득 참은 설정 "내 기억" 화면만 보여 준다
    notes = [n for n in memory.lookup_notes(user_id, bl) if n.startswith(PREVIOUS_LINE_PREFIX)]
    same = context is not None and context.bl_no == bl
    kind = bl_type or (context.bl_type if same else None)
    req = AgentRequest(bl_no=bl, bl_type=kind or DEFAULT_BL_TYPE, session_id=session_id,
                       sale_due_date=sale_due_date or (context.sale_due_date if same else None),
                       mrn=mrn or (context.mrn if same else None),
                       voyage_no=voyage_no, forwarder_eta=forwarder_eta)
    resp = run_agent(req)
    reply = resp.answer
    if not kind:
        reply = (f"{reply}\n(B/L 구분을 말하지 않아 하우스 B/L(포워더가 발행한 B/L)로 조회했습니다. "
                 "선사가 발행한 마스터 B/L이면 \"마스터로 다시\"라고 말해 주세요.)")
    if notes:
        reply = "\n".join([reply, *notes])
    return ChatResult(kind="cargo", reply=reply, agent=resp, request=req)
