"""자연어 입력 하나를 받아 알맞은 동작으로 보낸다 (docs/specs/chat-search.md).

순서: B/L 가리기(코드) → 에이전트(LLM이 도구를 골라 부른다, _agent) → 답 검사(코드).
에이전트가 안 되면(키 없음, 도구를 거절하는 모델, CHAT_AGENT=off) 전 방식으로 간다: 의도 고르기(LLM, route_chat) → 실행(코드).
- cargo·follow_up은 기존 판정 흐름(routers/agent.run_agent)을 그대로 부른다. 판정·근거 규칙은 바뀌지 않는다
- vessel_search는 해수부 입항 예정의 직전 기항지로 거른다. 항구 고르기만 LLM(match_ports)이 목록 안에서 한다
- LLM이 안 되면 규칙으로 대신한다 (EC-01): B/L이 있으면 조회, 없으면 B/L을 물어본다
LLM이 낸 칸은 믿기 전에 다시 본다: bl_ref는 가린 목록 안의 것만, ports는 주어진 목록 안의 것만, days는 1~14.
화물 비서 기억 (docs/specs/memory.md): 의도 구조는 그대로다. 로그인 사용자의 화물 조회 답에는
코드가 쓴 "지난 조회" 한 줄을 붙이고, 가린 사용자 문장을 기억 뽑기 재료로 판정 흐름에 넘긴다 (memory.user_text).
채팅 에이전트: 의도 넷에 안 맞는 실무 질문이 전부 고정 안내로 가고, 앞 대화를 몰라 "이건"을 못 알아듣던 문제를 고친다.
도구는 화물 조회·화물 질문·입항 선박 검색과 읽기 전용 MCP 도구, 이다. 등급·여유 일수는 지금처럼 판정 흐름(코드)이 정한다.
컨테이너 번호로 찾기: 문장 속 컨테이너 번호(ISO 6346)는 B/L처럼 LLM에 원문을 주지 않는다. 로그인 사용자의 화물 표에서
그 번호를 찾으면 코드가 원본 B/L로 바꿔 기존 B/L 흐름에 넘기고, 못 찾으면 [CNTR1] 번호표로 가린다 (_swap_containers).
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import httpx

from backend.app import crypto
from backend.app.clients.mof import MofClient, MofError
from backend.app.clients.replay import replay_enabled
from backend.app.db import connect
from backend.app.observability.langfuse import tool_span
from backend.app.observability.logging import log_failure
from backend.app.schemas.agent import AgentRequest
from backend.app.services.judge import bl_parse
from backend.app.services.watch import cargo
from backend.app.services.judge import guard
from backend.app.services import llm
from backend.app.services import mcp_client
from backend.app.services.account import memory
from backend.app.services.chat import progress
from backend.app.services.chat import referrals
from backend.app.services.judge import validate
from backend.app.services.watch import vessel_pick
from backend.app.services.chat import citations as cite
from backend.app.services.watch.watch import MAX_WATCH
from backend.app.services.chat.limits import (
    ARRIVALS_SHOWN,
    CACHE_SEC,
    CARGO_CALLS_PER_TURN,
    HISTORY_TURNS,
    KAKAO_COOLDOWN_SEC,
    KST,
    MAX_BLS_PER_TURN,
    MEMO_MAX_ITEMS,
    MESSAGE_MAX,
    SEND_ONLY_MAX,
    UNRELATED_MAX_CHARS,
    WATCH_ONLY_MAX,
)
from backend.app.services.chat.texts import (
    ARRIVALS_LIMIT_NOTE,
    BROKER_ONLY,
    BROKER_SHORT,
    CARGO_ON_SCREEN_HINT,
    CLEARANCE_HINT,
    CONTAINER_NEED_LOGIN,
    CONTAINER_NOT_FOUND,
    DATE_PROMISE_NOTE,
    DEFAULT_BL_TYPE,
    FAILED_LOOKUP,
    FOLLOW_UP_REFUSED,
    GREETING_REPLY,
    INJECTION_REPLY,
    KAKAO_COOLDOWN_REPLY,
    KAKAO_FAILED,
    KAKAO_FAIL_REPLY,
    KAKAO_HOW,
    KAKAO_LINKED_TAIL,
    KAKAO_NEED_LOGIN,
    KAKAO_NOT_LINKED,
    KAKAO_NOT_READY,
    KAKAO_NO_CARGO,
    KAKAO_NO_VERDICT,
    KAKAO_ONE_AT_A_TIME,
    KAKAO_SENT,
    KAKAO_UNLINKED_TAIL,
    LLM_DOWN,
    LOOKUP_FALLBACK_LEAD,
    LOOKUP_FALLBACK_SAME,
    LOOKUP_NOT_SUMMARIZED,
    MEMO_HINT,
    MEMO_SAVE_LEAD,
    MULTI_BL_NOTICE,
    MULTI_FAILED_NOTICE,
    MULTI_TABLE_LEAD,
    NEED_BL,
    NOT_FOUND_BOTH,
    NOT_IN_SKILLS,
    NO_CARGO,
    NO_RESULT_BOTH,
    NO_RESULT_REPLY,
    OTHER_REPLY,
    PERSON_ASK,
    PREVIOUS_LINE_PREFIX,
    PREV_PORT_EMPTY_NOTE,
    PREV_PORT_NOTE,
    ROW_SAY_NOT_FOUND,
    SALE_PAST,
    SALE_UNREADABLE,
    SHORT_NOTICE,
    SHORT_NOTICE_2,
    UNREAD_NOTICE,
    USAGE_GUIDE,
    VESSEL_ASK_WHICH,
    VESSEL_DEFAULT_ERROR,
    VESSEL_MANY,
    VESSEL_NEED_LOGIN,
    VESSEL_NOT_FOUND,
    VESSEL_OFF_NO_MMSI,
    VESSEL_OFF_REPLY,
    VESSEL_ON_REPLY,
    VESSEL_UNAVAILABLE,
    WATCH_ALREADY_HEAD,
    WATCH_ALREADY_OFF,
    WATCH_ALREADY_ON,
    WATCH_FAIL_REPLY,
    WATCH_HOW,
    WATCH_NEED_LOGIN,
    WATCH_NOT_FOUND,
    WATCH_NO_CARGO,
    WATCH_OFF_REPLY,
    WATCH_ONE_AT_A_TIME,
    WATCH_ON_PLAIN,
    WATCH_ON_REPLY,
    WATCH_PAGE_LINE,
)
from backend.app.services.chat.patterns import (
    AFFIRM,
    BROKER_TOPIC,
    CARGO_TALK,
    CLEARANCE_TIMING,
    DATE_PROMISE_ASK,
    KAKAO_WORD,
    MEMO_TOPICS,
    VESSEL_WATCH_WORDS,
    WATCH_REQUEST,
    WATCH_STOP,
    WATCH_WORDS,
    _ID_LIKE,
    _PLACE,
    _SAYS_NOT_FOUND,
    _VOYAGE_OK,
)
from backend.app.services.chat.models import ChatError, ChatResult, KakaoHooks, WatchHooks
from backend.app.services.chat.ids import (
    _flat_text,
    _is_destination,
    _valid_date,
    asked_days,
    echoes_person_name,
    extract_mrn,
    find_containers,
    hide_bl_tokens,
    mask_bls,
    sale_if_given,
    ship_name_guess,
    unread_ids,
    user_gave_date,
)
from backend.app.services.chat.map_card import _map_payload
from backend.app.services.chat.memo import (
    _memo_view,
    _norm_name,
    is_memo_question,
    is_save_request,
    memo_phones_ok,
    memo_reply_text,
)
from backend.app.services.chat.screen import _cargo_summary, _masked_history, _masked_screen
from backend.app.services.chat.tools import (
    AGENT_TOOLS,
    MCP_STAGES,
)
from backend.app.services.chat.replies import (
    _copies_user_marker,
    _is_no_result,
    _multi_table,
    _no_result_text,
    _period_text,
    _repeats_reply,
    _reply_violations,
    _safe_reply,
    _ship_list_lines,
    _strip_notice,
    _tool_error,
    _vessel_rows,
    clarify_reply,
    is_action_request,
    lookup_fallback,
    not_same_twice,
)
from backend.app.services.chat.watch_chat import _offered, kakao_now_text, wants_send_now, watch_offer_text


DAYS_DEFAULT, DAYS_MAX = 7, 14  # 입항 예정 검색 기간. 해수부 한 번 조회가 20쪽까지라 길게 잡지 않는다



SKILL_TAG = re.compile(r"\s*\[(?:SKILL|Skill|skill|skills/)[^\]\n]{0,40}\]")  # 모델이 붙인 Skill 파일 꼬리표

def search_ship_name(name: str, last: str | None = None) -> ChatResult | None:
    """부산 입항 예정 목록(앞으로 DAYS_MAX일)에서 배 이름으로 찾는다. 이름 글자가 선박 이름에 들어 있으면 맞는 것 (대소문자 무시, 끝의 "호" 뺌).
    찾으면 선박 표, 없으면 무엇을 찾았는지 말하는 문장. 입항 목록을 못 받으면 None (호출한 쪽이 되묻는다)."""
    needle = re.sub(r"호$", "", name).strip().upper() or name.upper()
    try:
        plans = _arrivals(DAYS_MAX)
    except MofError as e:
        log_failure("chat_vessels", e.code)
        return None
    chosen = [p for p in plans if needle in (p.ship_name or "").upper()]
    if not chosen:
        reply = (f"'{name}' 이름의 배는 앞으로 {DAYS_MAX}일 부산 입항 예정 목록에서 찾지 못했어요. "
                 "목록은 영문 배 이름이 기준이라 한글 이름은 안 나올 수 있어요. 영문 배 이름이나 B/L 번호를 알려 주세요.")
        reply = not_same_twice(reply, [f"'{name}'는 이번에도 목록에 없어요. 영문 배 이름이나 B/L 번호가 있으면 알려 주세요."], last)
        return ChatResult(kind="message", reply=reply)
    chosen.sort(key=lambda p: p.expected_arrival or datetime.max.replace(tzinfo=timezone.utc))
    return ChatResult(kind="vessels", reply=f"앞으로 {DAYS_MAX}일 부산 입항 예정 선박 중 '{name}' 이름이 들어간 배는 {len(chosen)}척이에요.",
                      vessels=_vessel_rows(chosen), place=None, ports=[], days=DAYS_MAX)


# 컨테이너 번호로 찾은 화물의 저장된 B/L 구분 {대문자 B/L: MASTER|HOUSE}. handle이 요청마다 채운다.
# 이유: 구분을 말하지 않으면 _cargo가 HOUSE로 조회하는데, 저장된 화물이 MASTER면 세관에서 못 찾는다.
# 인자로 내려보내려면 handle~_cargo 사이 시그니처 여럿을 바꿔야 해서, memory.user_text처럼 contextvar로 둔다
# (여러 B/L을 동시에 조회하는 스레드는 contextvars.copy_context로 이 값을 이어 받는다)
_STORED_TYPES: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar("chat_stored_bl_types", default=None)


def _stored_type(bl: str) -> str | None:
    """컨테이너 번호로 찾은 화물의 저장된 B/L 구분. 컨테이너로 온 B/L이 아니면 None."""
    kind = (_STORED_TYPES.get() or {}).get(bl.upper())
    return kind if kind in ("MASTER", "HOUSE") else None


def _own_cargo_by_container(user_id: str | None, container: str) -> tuple[str, str | None] | None:
    """로그인 사용자의 화물 표에서 이 컨테이너의 (원본 B/L, 저장된 B/L 구분). 못 찾으면 None.
    로그인 안 함, DB 없음(채점 환경), 읽기 실패, 열쇠가 없어 B/L을 못 여는 경우 모두 "못 찾음"이다: 채팅은 계속 돈다 (EC-08, memory.lookup_notes와 같다).
    원본 B/L은 이 함수 밖으로 나가도 LLM에는 가지 않는다. 호출한 쪽이 문장에 끼운 뒤 mask_bls가 [BLn]으로 가린다."""
    if not user_id or not os.environ.get("DATABASE_URL"):
        return None
    try:
        with connect() as conn:
            row = cargo.find_by_container(conn, user_id, container)
    except Exception as e:  # noqa: BLE001 - 화물 찾기는 부가 기능이다. 종류만 남기고 못 찾음으로 처리한다
        log_failure("container_lookup", type(e).__name__)
        return None
    if not row or not row.get("bl_encrypted"):
        return None
    bl = crypto.decrypt(row["bl_encrypted"])
    return (bl.strip().upper(), row.get("bl_type")) if bl else None


def _swap_containers(message: str, user_id: str | None,
                     exists: Callable[[str], bool] | None = None) -> tuple[str, int, dict[str, str]]:
    """문장 속 컨테이너 번호를 LLM에 원문이 안 가는 모양으로 바꾼다. (바뀐 문장, 못 찾은 개수, {B/L: 저장된 구분})을 돌려준다.
    - 내 화물에서 찾았으면 그 자리를 원본 B/L로 바꾼다. 이어지는 B/L 흐름(repair_message, mask_bls, check_cargo)이 그대로 맡는다
    - 내 화물에 없으면 세관에 같은 번호의 B/L이 있는지 본다(exists, 보통 bl_parse.exists_in_customs). 있으면 컨테이너가 아니라
      우연히 컨테이너 모양·검산까지 맞은 B/L이다: 그대로 두면 아래 mask_bls가 [BL1]로 가려 B/L로 조회한다 (결정:
      B/L을 넣었는데 "못 찾음"이 뜨는 게 가장 나쁘다). 대가는 이런 번호 하나당 UNI-PASS 최대 2번 호출이다
    - 세관에도 없으면 [CNTR1] 번호표로 바꾼다 (mask_containers와 같은 모양). 이 번호표는 아무 도구에도 연결되지 않는다"""
    containers = find_containers(message)
    if not containers:
        return message, 0, {}
    types: dict[str, str] = {}
    unmatched: list[str] = []
    for code in containers:
        own = _own_cargo_by_container(user_id, code)
        if own is not None:
            bl, kind = own
            replacement = bl
            if kind in ("MASTER", "HOUSE"):
                types[bl] = kind
        elif exists is not None and exists(code):
            continue  # 세관에 있는 B/L이다. 글자를 그대로 두고 B/L 흐름에 맡긴다
        else:
            unmatched.append(code)
            replacement = f"[CNTR{len(unmatched)}]"
        # 번호 하나씩 그 자리만 바꾼다. 끼워 넣은 B/L이 우연히 컨테이너 모양이어도 다시 가려지지 않는다
        message = re.sub(rf"(?<![A-Za-z0-9]){code}(?![A-Za-z0-9])", lambda _m, r=replacement: r, message, flags=re.I)
    return message, len(unmatched), types


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
        # 캐시 미스일 때만 도는 해수부 구간을 Langfuse에 남긴다
        with tool_span("mof:sailing_plans_all", {"days": days}) as span:
            plans = client.sailing_plans_all(today, today + timedelta(days=days))  # 쪽을 동시에 받는다
            span.metadata["count"] = len(plans)
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
    """직전 기항지로 거른 부산 입항 예정 선박. 항구는 LLM이 목록 안에서만 고른다 (EC-04).
    place가 도착지 자체(부산·한국, _is_destination)면 거르지 않고 전체를 보인다 (점검: "이번 주 부산 들어오는 배"가
    "부산(고현, 광양,...)를 직전에 들른 배 86척"이 됐다. 항구 고르기 LLM이 부산과 비슷한 국내 항구를 골랐다).
    부산 입항 목록에서 "부산에서 오는 배"는 뜻이 없으므로 사용자의 뜻은 "부산에 오는 배 전부"다. 전 방식과 에이전트가 같이 탄다"""
    if _is_destination(place) or _is_destination(label):
        place, label = None, None
    days = max(1, min(days or DAYS_DEFAULT, DAYS_MAX))
    name = label or place  # 답에는 사용자가 쓴 말(중국)을, 항구 고르기에는 영어(China)를 쓴다
    progress.step("schedule")
    try:
        plans = _arrivals(days)
    except MofError as e:
        log_failure("chat_vessels", e.code)
        return ChatResult(kind="message", reply="해수부 서버에 지금 연결되지 않아 입항 정보를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.")
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
    vessels = _vessel_rows(chosen)
    cargo = sum(v["is_cargo"] for v in vessels)
    listing = _ship_list_lines(vessels)
    period = _period_text(days)
    where = f"{name}에서 " if place else ""
    if place and not vessels:
        reply = f"{name}에서 {period} 안에 부산 오는 입항 예정 선박은 없어요.\n{PREV_PORT_EMPTY_NOTE}"
    else:
        # 첫 줄은 결론만. 수입 화물선이 하나도 없으면 그 사실을 먼저 말하고, 줄에는 전체 입항 선박을 보인다
        head = (f"{where}{period} 안에 부산 오는 수입 화물선 {cargo}척이에요." if cargo
                else f"{where}{period} 안에 부산 오는 수입 화물선은 없고, 입항 예정 선박은 {len(vessels)}척이에요.")
        reply = "\n".join(x for x in (head, listing, PREV_PORT_NOTE) if x)
    return ChatResult(kind="vessels", reply=reply, vessels=vessels, place=name, ports=ports, days=days)


def handle(message: str, session_id: str, context: AgentRequest | None, run_agent,
           user_id: str | None = None, history: list[dict] | None = None,
           run_tool: Callable[[str, dict], dict] | None = None, watch: WatchHooks | None = None,
           kakao: KakaoHooks | None = None, on_screen: dict | None = None) -> ChatResult:
    """문장 하나를 처리한다. run_agent는 routers/agent.run_agent(사용자 묶음 포함)를 부르는 함수다.
    user_id: 로그인 사용자. 있으면 화물 조회 답에 지난 조회 한 줄을 붙인다 (docs/specs/memory.md). 없으면(EC-08) 그대로.
    history: 화면이 보낸 최근 대화 [{"role", "text"}]. 에이전트가 "이건", "그 배"를 알아듣는 데만 쓴다.
    run_tool: 읽기 전용 MCP 도구를 실제로 부르는 함수 (routers/agent._follow_up_tool). 없으면 에이전트는 MCP 도구 없이 돈다.
    watch: 지켜보기를 읽고 쓰는 함수 묶음 (WatchHooks). 없으면 로그인하지 않았거나 DB가 없는 것과 같다: 아무것도 바꾸지 않고 안내만 한다.
    kakao: 지금 상태를 카카오톡으로 보내는 함수 묶음 (KakaoHooks). 없으면 보내지 않고 안내만 한다.
    on_screen: 화면에 지금 떠 있는 배들 {"vessel", "arrivals"} (routers/chat.ChatScreen). 에이전트가 "옆에 떠 있는 배"를 알아듣는 데만 쓴다."""
    message = (message or "").strip()
    if not message:
        raise ChatError("empty")
    if len(message) > MESSAGE_MAX:
        raise ChatError("too_long")
    mrn, message = extract_mrn(message)  # B/L 가리기보다 먼저 (MRN도 B/L 모양이라 [BL]로 잘못 가려진다)
    # 컨테이너 번호도 B/L 가리기보다 먼저 (영숫자 11자라 B/L 모양에 걸린다). 내 화물이면 B/L로 바꾸고, 아니면 [CNTR1]로 가린다
    message, unmatched_containers, stored_types = _swap_containers(message, user_id, bl_parse.exists_in_customs)
    # 기호·띄어쓰기로 흐트러진 B/L("test-bl-01")을 세관에 있는 것만 붙여 읽는다 (services/judge/bl_parse.py).
    # 가리기 전에 한다: 붙인 번호도 아래 mask_bls가 [BL1]로 가려서 LLM에는 원본이 가지 않는다. 고쳐 읽었다는 알림은 코드 문장이다
    message, repair_notes = bl_parse.repair_message(message, bl_parse.exists_in_customs)
    masked, refs = mask_bls(message)
    if unmatched_containers and not refs:
        # 찾을 B/L이 없고 컨테이너만 못 찾았다: LLM을 부르지 않고 코드 문장으로 답한다 (컨테이너 번호를 LLM에 주지 않는 규칙)
        return ChatResult(kind="message", reply=CONTAINER_NOT_FOUND if user_id else CONTAINER_NEED_LOGIN)
    # 기억 뽑기 재료는 가린 문장이다. B/L·MRN 원본은 넘기지 않는다 (CLAUDE.md, docs/specs/memory.md 쓰기 흐름 3)
    types_token = _STORED_TYPES.set(stored_types)
    early = None
    try:
        with memory.user_text(masked) as turn:
            # 기억 뽑기는 답 만들기와 같이 턴 시작에 출발한다. B/L이 든 문장도 같다: 먼저 도는 쪽은 화물 없이 이 사람에 대해 종류(거래처·선호·일정)만 맡고, 화물에 묶인 것은 조회 뒤 기억 뽑기가 맡는다.
            # 직전 답이 우리가 붙인 거래처 되묻기였으면 그 문맥을 같이 준다 ("포워더야"가 어느 거래처 답인지 알게)
            if user_id:
                early = memory.start_early(user_id, masked, memory.followup_hint(history))
            result = _route(masked, refs, mrn, session_id, context, run_agent, user_id, history or [], run_tool, watch, kakao, on_screen)
    finally:
        _STORED_TYPES.reset(types_token)
    # 로그인 사용자의 평범한 대화 턴도 기억 뽑기에 보낸다. 기억 뽑기는 화물 조회·후속 질문 뒤에만 돌아
    # "우리 포워더는 가온 김과장이야" 같은 말이 B/L 없는 턴에서 버려졌다. 같은 문장을 두 번 보내지 않도록,
    # 이 턴에 조회가 이미 맡겼으면(turn.fired) 건너뛴다. 무엇을 기억할지는 LLM이 정한다. 가린 문장만 넘긴다
    if user_id and not turn.fired and early is None:
        memory.remember_chat_later(user_id, masked)
    if not result.evidence_items and result.agent is not None:
        # 에이전트를 안 거친 화물 답(전 방식 등)도 화면 칩이 쓸 근거 목록은 싣는다. 표시(citations)는 없다
        result = replace(result, evidence_items=cite.build_evidence_list(result.agent.evidence))
    if repair_notes:
        result = replace(result, reply="\n".join([result.reply, *repair_notes]))
    # 먼저 맡긴 기억 뽑기의 결과를 짧게 기다려 답 끝에 붙인다: 저장하지 못한 것 알림, 거래처 종류·전화 되묻기 (코드가 쓴 글, LLM 아님).
    # 이전 턴에서 늦게 끝나 못 붙인 알림도 여기서 같이 붙는다. 기억 뽑기의 어떤 실패도 답을 막지 않는다
    extra = "\n".join(x for x in (*memory.take_notices(user_id), memory.join_early(user_id, early)) if x)
    if extra:
        result = replace(result, reply="\n\n".join(x for x in (result.reply, extra) if x))
    return result


def _route(masked: str, refs: dict[str, str], mrn: str | None, session_id: str, context: AgentRequest | None,
           run_agent, user_id: str | None, history: list[dict] | None = None,
           run_tool: Callable[[str, dict], dict] | None = None, watch: WatchHooks | None = None,
           kakao: KakaoHooks | None = None, on_screen: dict | None = None) -> ChatResult:
    """가린 문장을 처리한다 (handle의 뒷부분). 에이전트가 먼저 맡고, 안 되면 의도 분류 방식(_classic)으로 간다."""
    today = datetime.now(KST).date().isoformat()

    # 실험 A3 (항상 켜짐; 실험 A1/A3/A4, Vertex 3회 486턴 기준 person 66.7→100%, broker 62.5→100%, this_ship 90.5→100%):
    # 관세·세금·세율·"통관 될까" 말이 있고 B/L이 없으면 모델을 거치지 않고 관세사 고정 안내로 답한다 (BROKER_TOPIC 낱말 그대로).
    # 전에는 이 안내가 모델이 도구를 안 고른 길에서만 나와서, 화면에 화물이 있으면 ask_cargo로 샜다. 안내 글은 사용자 글을 옮기지 않아
    # 주입 검사보다 먼저 내도 안전하다. 바로 앞 답이 같은 안내면 fixed()처럼 짧은 말로 바꾼다. B/L이 든 문장은 그 화물 조회가 먼저라 건드리지 않는다
    if not refs and BROKER_TOPIC.search(masked):
        last_assistant = next((t.get("text") or "" for t in reversed(history or []) if t.get("role") == "assistant"), "")
        same = re.sub(r"\s+", "", last_assistant) == re.sub(r"\s+", "", BROKER_ONLY)
        return ChatResult(kind="message", reply=BROKER_SHORT if same else BROKER_ONLY)

    # 주입 모양 문장은 LLM에 보내지 않는다 (services/judge/guard.py, SDD 7절). 후속 질문 경로는 route_chat이 질문을
    # 다시 쓴 뒤에야 routers/agent의 guard를 지나서, 다시 쓰는 과정에서 공격문 모양이 바뀌면 빠져나갈 수 있다. 원문에서 먼저 본다
    if guard.looks_like_injection(masked):
        log_failure("chat", "blocked prompt injection pattern")
        return ChatResult(kind="message", reply=INJECTION_REPLY)

    # 범위 밖 주제(항공·육상, 창고 수령일, 일정 변경, 날씨, 품목 요건)는 LLM 없이 고정 문장으로 답한다 (docs/specs/referral-guide.md).
    # B/L이 있는 문장은 그 화물 조회가 먼저라 보지 않는다. 문장과 주제 낱말은 skills/referrals/rules.md out_of_scope
    hit = None if refs else referrals.out_of_scope_topic(masked)
    if hit:
        logging.getLogger(__name__).info("out_of_scope topic=%s", hit[0])  # 실패가 아니라 INFO. 주제만 남기고 문장은 남기지 않는다
        return ChatResult(kind="message", reply=hit[1])

    progress.step("understand")  # 화면에 실제 단계를 알린다 (docs/specs/chat-progress.md)
    if agent_enabled():
        try:
            return _agent(masked, refs, mrn, session_id, context, run_agent, user_id, history or [], run_tool, today, watch, kakao, on_screen)
        except llm.LLMError as e:
            # 에이전트가 첫 도구를 쓰기도 전에 실패했다 (키 없음, 도구를 붙이면 거절하는 모델·제공사 등).
            # 전 방식은 도구 없이 한 번 묻는 호출이라 이런 경우에도 된다 (실측: 도구를 붙이면 404인 제공사가 있었다)
            log_failure("chat_agent", e.kind)
    if not refs and context is None and BROKER_TOPIC.search(masked):
        # 세액·관세율·통관 가부는 화물이 없어도 관세사 고정 안내다. 에이전트 경로는 이 문구로 끝나지만(반복이면 짧게),
        # 에이전트를 못 쓸 때의 전 방식(_classic)은 사용 안내로 빠졌다 (재생 서버 실측 "관세 얼마 나와?")
        return ChatResult(kind="message", reply=BROKER_ONLY)
    return _classic(masked, refs, mrn, session_id, context, run_agent, user_id, today)


def _classic(masked: str, refs: dict[str, str], mrn: str | None, session_id: str, context: AgentRequest | None,
             run_agent, user_id: str | None, today: str) -> ChatResult:
    """의도 분류 방식 (전의 _route 뒷부분 그대로). LLM이 의도 하나와 칸을 고르고 코드가 실행한다.
    에이전트를 못 쓸 때의 대비 경로이고, CHAT_AGENT=off면 이 길만 탄다."""
    try:
        route = llm.route_chat(masked, list(refs), context is not None, today).output
    except llm.LLMError as e:  # EC-01: 규칙으로 대신
        log_failure("chat_route", e.kind)
        if refs:
            return _classic_cargo(list(refs.values()), None, None, session_id, context, run_agent, mrn, user_id)
        return ChatResult(kind="message", reply=LLM_DOWN)

    # 문장에 지금 화물과 다른 B/L이 있으면 의도와 상관없이 새 화물 조회다 (실측: 화면에 화물이 있으면
    # LLM이 "[BL1] 화물 조회해줘"를 follow_up으로 골라 이전 화물 답과 카드가 나왔다). LLM이 낸 의도를 코드가 덮어쓴다
    new_bls = [bl for bl in refs.values() if context is None or bl != context.bl_no]
    if new_bls and route.intent in ("follow_up", "other"):
        return _classic_cargo(new_bls, route.bl_type, sale_if_given(route.sale_due_date, masked), session_id, context, run_agent, mrn, user_id)

    if route.intent == "cargo":
        if len(set(refs.values())) > 1:
            # B/L이 여럿이면 LLM이 고른 하나가 아니라 문장에 나온 순서대로 모두 본다 (에이전트와 같은 기준)
            return _classic_cargo(list(refs.values()), route.bl_type, sale_if_given(route.sale_due_date, masked), session_id, context,
                                  run_agent, mrn, user_id)
        bl = refs.get(route.bl_ref or "") or (next(iter(refs.values())) if refs else None)
        if not bl:
            if context is None:
                return ChatResult(kind="message", reply=NEED_BL)  # EC-02
            bl = context.bl_no
        return _cargo(bl, route.bl_type, sale_if_given(route.sale_due_date, masked), session_id, context, run_agent, note=None, mrn=mrn, user_id=user_id)

    if route.intent == "follow_up":
        if context is None:
            return ChatResult(kind="message", reply=NO_CARGO)  # EC-03
        question = (route.question or masked)[:300]  # 후속 질문은 300자 (schemas/agent.py)
        req = context.model_copy(update={"session_id": session_id, "follow_up_question": question,
                                         "resolved_mmsi": None, "voyage_no": None, "forwarder_eta": None})
        resp = run_agent(req)
        # 원문 기준 V10 한 번 더. 판정 흐름의 V10은 route_chat이 다시 쓴 질문만 본다. 다시 쓰면서 공격 조각이
        # 빠지거나 바뀌면, 원문에 있던 표식을 답이 옮겨도 못 잡는다. 사용자가 실제로 쓴 문장과 한 번 더 대조한다
        if _copies_user_marker(resp, masked):
            log_failure("chat", "follow-up answer copied words from original message")
            resp = resp.model_copy(update={"answer": FOLLOW_UP_REFUSED})
        return ChatResult(kind="cargo", reply=resp.answer, agent=resp, request=context)

    if route.intent == "vessel_search":
        # place·place_label은 LLM 출력인데 답 문장에 그대로 들어간다. place는 영문 지명 모양만,
        # place_label은 사용자가 실제로 쓴 글자일 때만 쓴다 (주입 방어). 아니면 버린다
        place = route.place.strip() if route.place else None
        if place and (not _PLACE.match(place) or len(place.split()) > 4 or guard.looks_like_injection(place)):
            place = None  # 지명은 네 낱말까지 ("New South Wales"). 문장이 섞이면 버린다
        label = route.place_label
        if not (label and re.sub(r"\s+", "", label) in re.sub(r"\s+", "", masked)):
            label = None
        return search_vessels(place, route.days, label)

    return ChatResult(kind="message", reply=_safe_reply(route.reply, masked))


def _classic_cargo(bls: list[str], bl_type: str | None, sale_due_date: str | None, session_id: str,
                   context: AgentRequest | None, run_agent, mrn: str | None, user_id: str | None) -> ChatResult:
    """전 방식의 화물 조회. B/L이 하나면 _cargo 그대로, 2개 이상이면 에이전트와 같은 기준으로 최대 MAX_BLS_PER_TURN개를
    조회해 표(cargos)로 낸다 (점검: 전 방식은 첫 B/L만 조회하고 나머지는 말없이 버렸다).
    넘친 B/L은 MULTI_BL_NOTICE로 알린다. MRN은 B/L 하나에 속하는 값이라 여럿일 때는 쓰지 않는다 (look_up_many와 같다).
    전 방식은 에이전트를 못 쓸 때의 대비 경로라 LLM 비교 문장 없이 코드 문장(MULTI_TABLE_LEAD)만 쓴다."""
    bls = list(dict.fromkeys(bls))  # 같은 B/L을 두 번 적었으면 한 번만
    if len(bls) == 1:
        return _cargo(bls[0], bl_type, sale_due_date, session_id, context, run_agent, note=None, mrn=mrn, user_id=user_id)
    picked = bls[:MAX_BLS_PER_TURN]

    def one(bl: str) -> ChatResult | None:
        try:
            return _cargo(bl, bl_type, sale_due_date, session_id, context, run_agent, note=None, mrn=None, user_id=user_id)
        except Exception as e:  # noqa: BLE001 - 하나가 죽어도 나머지는 보인다 (SDD 3.4, look_up_many와 같다)
            log_failure("chat_cargo", f"classic multi {type(e).__name__}")
            return None

    # 스레드마다 contextvars 복사본으로 돌려 단계 소식·요청 ID·LLM 사용량 기록이 이 요청에 묶이게 한다 (look_up_many와 같다)
    with ThreadPoolExecutor(max_workers=len(picked)) as pool:
        futures = [pool.submit(contextvars.copy_context().run, one, bl) for bl in picked]
        outcomes = [f.result() for f in futures]
    found = [o for o in outcomes if o is not None]
    notices = ([MULTI_BL_NOTICE] if len(bls) > MAX_BLS_PER_TURN else []) \
        + ([MULTI_FAILED_NOTICE] if len(found) < len(picked) else [])
    if not found:
        return ChatResult(kind="message", reply=FAILED_LOOKUP)
    if len(found) == 1:
        return replace(found[0], reply="\n".join([found[0].reply, *notices]))
    need_lines, rows, chosen = _multi_table(found)
    lines = [MULTI_TABLE_LEAD.format(n=len(found)), *need_lines]
    lines.extend(notices)
    return replace(chosen, reply="\n".join(lines), map=None, cargos=rows)


# ── 채팅 에이전트 ─────────────────────────────────────
# LLM이 아래 도구를 골라 부르고 결과를 본 뒤 다음 도구를 또 고른다 (llm.chat_agent, 상한 llm.MAX_TOOL_ROUNDS).
# 도구 실행과 답 조립은 여기서 한다. 지키는 것은 전 방식과 같다:
#   B/L은 가린 토큰으로만 오가고 코드가 원래 번호로 바꾼다 · 등급과 여유 일수는 판정 흐름이 정한다 ·
#   LLM이 낸 칸(구분·날짜·지명)은 쓰기 전에 다시 본다 · 화면에 가는 문장은 검증된 것만


SHIP_WORD = re.compile(r"배|선박|호\b|호야|ship|vessel", re.IGNORECASE)


def _load_memo(user_id: str) -> tuple[list[dict], dict[str, dict]]:
    """(메모 항목들, 화물 지문 → {"label","vessel"}). 읽기만 한다. 화물 이름을 못 읽으면 항목만 돌려준다 (배 연결만 못 한다)."""
    with connect() as conn:
        items, _, _, _ = memory.load(conn, user_id)
        try:
            rows = conn.execute("SELECT cargo_key, label, vessel_name FROM user_cargo WHERE user_id = %s", [user_id]).fetchall()
            cargos = {r[0]: {"label": r[1], "vessel": r[2]} for r in rows}
        except Exception as e:  # noqa: BLE001 - 배 연결은 덤이다. 거래처 찾기는 계속한다
            log_failure("chat_recall", f"cargo {type(e).__name__}")
            cargos = {}
    return items, cargos


def select_memo(items: list[dict], cargos: dict[str, dict], topic: str, query: str | None, message: str = "",
                screen_vessel: str | None = None, screen_key: str | None = None) -> dict:
    """메모에서 질문에 맞는 것을 고른다 (코드). 돌려주는 모양:
      {"status": "ok", "items": [...]}              답할 항목이 정해졌다. LLM이 한두 문장을 쓴다
      {"status": "ambiguous", "companies": [...]}   거래처가 여럿이고 질문이 못 가른다. 코드가 어느 쪽인지 되묻는다
      {"status": "no_match", "companies": [...]}    질문의 회사·역할 낱말에 맞는 것이 없다
      {"status": "none"}                            찾을 것이 아예 없다
    우선순위: 화면의 화물·말한 배와 이어진 화물별 거래처 > 질문 낱말(회사·역할·직무)에 맞는 거래처 > 이 사람에 대한 거래처 전체."""
    wanted = {"contact"} if topic == "contact" else {"contact", "preference", "schedule", "worry", "todo"}
    pool = [i for i in items if i.get("kind") in wanted]
    contacts = [i for i in pool if i["kind"] == "contact"]
    if not pool:
        return {"status": "none"}
    text = _norm_name(f"{query or ''} {message}")
    cargo_keys = {k for k, c in cargos.items()
                  if any(len(n) >= 3 and (n in text or (screen_vessel and n == _norm_name(screen_vessel)))
                         for n in (_norm_name(c.get("vessel")), _norm_name(c.get("label"))))}
    if screen_key:
        cargo_keys.add(screen_key)
    if topic == "contact" and contacts:
        linked = [i for i in contacts if i.get("section") == memory.CARGO and i.get("cargo_key") in cargo_keys]
        about = [i for i in contacts if i.get("section") == memory.ABOUT] or contacts
        words = [w.lower() for w in re.split(r"[\s,./?!]+", query or "") if len(w) >= 2]
        hit = [i for i in about if any(w in " ".join(str(v) for v in (i.get("fields") or {}).values()).lower() for w in words)]
        if linked:
            chosen = linked
        elif hit:
            chosen = hit
        elif len(about) == 1 or not (query or "").strip():
            chosen = about  # 하나뿐이거나 말한 낱말이 없다: 있는 거래처를 그대로 보여 준다
        else:
            who = [{"company": str((i.get("fields") or {}).get("company") or ""), "role": (i.get("fields") or {}).get("role")} for i in about]
            # 배 이야기면 "이 배 담당이 어느 쪽인가" (거래처는 배에 묶여 있지 않다), 아니면 말한 낱말에 맞는 거래처가 없는 것이다
            return {"status": "ambiguous" if SHIP_WORD.search(f"{query or ''} {message}") else "no_match", "companies": who}
        return {"status": "ok", "items": [_memo_view(i, i in linked) for i in chosen[:MEMO_MAX_ITEMS]]}
    if topic == "contact":  # 거래처가 하나도 없다 (다른 종류만 있거나 메모가 비었다)
        return {"status": "none"}
    return {"status": "ok", "items": [_memo_view(i, False) for i in pool[:MEMO_MAX_ITEMS]]}


def agent_enabled() -> bool:
    """채팅 에이전트를 쓰는가. 기본은 켜짐. CHAT_AGENT=off면 의도 분류 방식만 쓴다 (.env.example, 시연 중 문제가 생기면 값 하나로 되돌린다)."""
    return os.environ.get("CHAT_AGENT", "on").strip().lower() not in ("0", "off", "false", "no")


SHIP_WORD = re.compile(r"(?<![가-힣])(?:배|선박)(?:를|을|은|는|이|가|도)?(?![가-힣])")  # "이 배", "배를" (배송 같은 낱말은 아니다)


# 쿨다운 기록 {(user_id, cargo_key): 보낸 시각(monotonic)}. 프로세스 메모리에만 있어서 서버가 다시 뜨면 비워진다.
# Railway에서 한 개로 돌리므로 이대로 충분하다. 여러 개로 늘리면 DB로 옮겨야 한다
_kakao_sent_at: dict[tuple[str, str], float] = {}
_kakao_lock = threading.Lock()


def _kakao_reserve(user_id: str, key: str) -> bool:
    """5분 안에 보낸 적이 없으면 지금 보내는 것으로 적고 True. 보낸 적이 있으면 False.
    보내기 전에 미리 적는다: 같은 요청이 겹쳐 와도 하나만 통과시키려는 것이다. 보내기가 실패하면 _kakao_release로 되돌린다."""
    now = time.monotonic()
    with _kakao_lock:
        last = _kakao_sent_at.get((user_id, key))
        if last is not None and now - last < KAKAO_COOLDOWN_SEC:
            return False
        _kakao_sent_at[(user_id, key)] = now
        return True


def _kakao_release(user_id: str, key: str) -> None:
    with _kakao_lock:
        _kakao_sent_at.pop((user_id, key), None)


def _agent(masked: str, refs: dict[str, str], mrn: str | None, session_id: str, context: AgentRequest | None,
           run_agent, user_id: str | None, history: list[dict], run_tool: Callable[[str, dict], dict] | None,
           today: str, watch: WatchHooks | None = None, kakao: KakaoHooks | None = None,
           on_screen: dict | None = None) -> ChatResult:
    """에이전트 한 턴 + 지켜보기 마무리. 본 처리는 _agent_turn이 하고, 여기서 코드가 쓴 지켜보기 문장·제안을 붙인다.
    본 처리가 문장 끝 여러 곳에서 돌아 나가서, 한 곳에서 붙이려고 감쌌다."""
    signals: dict = {}
    result = _agent_turn(masked, refs, mrn, session_id, context, run_agent, user_id, history, run_tool, today, watch, signals, kakao, on_screen)
    result = replace(result, reply=hide_bl_tokens(result.reply, signals.get("refs") or refs))
    # 모델이 Skill 파일 이름을 출처처럼 적은 꼬리표("[SKILL 2]", "[SKILL.md]", "[skills/...]")는 내부 표시라 지운다.
    # 근거 표시는 코드가 다는 [E#]뿐이다 (e2e, import-basics 답에서 관찰)
    result = replace(result, reply=SKILL_TAG.sub("", result.reply).strip())
    result = _with_citations(result, signals)  # 뒤에 붙는 코드 문장(지켜보기·카톡·제안)은 모두 글 끝에 더해지므로 표시 자리는 그대로 맞다
    done_kakao = signals.get("kakao") or {}
    if done_kakao.get("msg") and done_kakao["msg"] not in result.reply:
        result = replace(result, reply=f"{result.reply}\n\n{done_kakao['msg']}")  # 화물 답과 같이 말한 경우: 답 뒤에 코드 문장
    if done_kakao.get("msg"):  # 카카오톡 보내기를 한 문장이다. 지켜보기 제안은 붙이지 않는다
        return result
    done_watch = signals.get("watch") or {}
    if done_watch.get("msg") and done_watch["msg"] not in result.reply:
        result = replace(result, reply=f"{result.reply}\n\n{done_watch['msg']}")  # 화물 답과 같이 말한 경우: 답 뒤에 코드 문장
    if done_watch.get("set"):
        return replace(result, watch_set=done_watch["set"])
    if done_watch.get("vessel_set"):
        return replace(result, watch_vessel_set=done_watch["vessel_set"])
    if done_watch.get("msg"):  # 못 켰다. 이번 문장에서는 제안하지 않는다
        return result
    return _with_offer(result, signals, context, user_id, history, watch)


def _with_citations(result: ChatResult, signals: dict) -> ChatResult:
    """LLM이 쓴 문장에 붙인 [E#] 표시를 코드가 검사해 남기고, 이번 문장의 근거 목록을 결과에 싣는다.

    왜 여기서 하나: 답 검사(V7 등)는 표시를 걷어 낸 글로 돌았고(_agent_turn), 최종 reply는 도구·코드 문장과 섞여 여러 길로 나간다.
    LLM 문장이 reply 안에 그대로 있을 때만 표시 달린 원문으로 되돌려 parse_and_validate에 맡긴다. 문장이 손질돼 reply에 없으면 표시는 버린다.
    표시는 LLM에게 보여 준 근거(exposed)에만 허용한다. 코드가 쓴 문장·고정 문구는 표시가 없고 evidence_items만 싣는다 (화면이 글 끝 칩으로 보인다).
    """
    items = signals.get("evidence") or []
    plain, raw = signals.get("marked") or ("", "")
    reply, marks = result.reply, []
    exposed = [i for i in items if i["id"] in signals.get("exposed", ())]
    if exposed and plain and raw != plain and plain in reply:
        reply, marks = cite.parse_and_validate(reply.replace(plain, raw, 1), exposed)
    return replace(result, reply=reply, evidence_items=items, citations=marks)


def _with_offer(result: ChatResult, signals: dict, context: AgentRequest | None, user_id: str | None,
                history: list[dict], watch: WatchHooks | None) -> ChatResult:
    """화물 답 뒤에 "지켜볼까요?" 제안을 붙인다. 조건:
    - 화물 하나의 답이고 판정이 있다. 표 답(B/L 여러 개)·반출 끝난 화물·판정 없는 답은 말할 이유가 없다
    - 이미 지켜보는 화물이 아니다 (로그인 사용자만 확인한다)
    - 직전 답이 제안이었으면 또 하지 않는다. 같은 화물에 앞서 제안했으면 사용자가 걱정을 비친 문장(watch_cue)일 때만 다시 한다
    제안 문장은 코드가 쓴다 (watch_offer_text). LLM은 걱정 신호(watch_cue)만 준다."""
    if result.kind != "cargo" or result.cargos or result.agent is None or result.request is None:
        return result
    from backend.app.routers.agent import is_released  # noqa: PLC0415 - 맨 위에서 부르면 라우터와 서비스가 서로 불러오는 순환이 된다
    if is_released(result.agent):
        return result
    bl = result.request.bl_no
    recent = history[-HISTORY_TURNS:]
    texts = [(t.get("text") or "") for t in recent if t.get("role") == "assistant"]
    last_was_offer = bool(recent) and recent[-1].get("role") == "assistant" and _offered(recent[-1].get("text") or "")
    same_cargo = context is not None and context.bl_no == bl
    if last_was_offer or (same_cargo and any(_offered(t) for t in texts) and not signals.get("watch_cue")):
        return result
    logged_in = user_id is not None
    worry = None
    if logged_in:
        if watch is None:  # 로그인했는데 저장소가 없다. 지금 상태를 몰라 제안하지 않는다
            return result
        try:
            if watch.state(bl).get("watch"):
                return result
            worry = watch.worry(bl)
        except Exception as e:  # noqa: BLE001 - 제안은 부가 기능이다. 실패해도 화물 답은 그대로 나간다
            log_failure("watch_offer", type(e).__name__)
            return result
    offer = watch_offer_text(result.agent, logged_in, worry)
    if offer is None:
        return result
    return replace(result, reply=f"{result.reply}\n\n{offer}",
                   watch_offer={"bl_no": bl, "reason": offer, "logged_in": logged_in})


def _agent_turn(masked: str, refs: dict[str, str], mrn: str | None, session_id: str, context: AgentRequest | None,
                run_agent, user_id: str | None, history: list[dict], run_tool: Callable[[str, dict], dict] | None,
                today: str, watch: WatchHooks | None, signals: dict, kakao: KakaoHooks | None = None,
                on_screen: dict | None = None) -> ChatResult:
    """에이전트 한 턴 (_agent가 감싼다). signals에 watch(지켜보기 도구 결과)와 watch_cue(LLM의 걱정 신호)를 적어 돌려준다.

    에이전트 한 턴. LLM이 고른 도구를 실행하고, 끝나면 화면에 보낼 결과 하나로 묶는다.

    답 조립 (틀린 문장을 내보내지 않는 쪽으로):
    - 화물 조회·화물 질문·선박 검색이 돌았으면 그 답을 그대로 쓴다. 판정 흐름과 코드가 이미 검증한 문장이다.
      읽기 전용 도구도 같이 썼을 때만 LLM 문장을 검사해 뒤에 붙인다
    - 읽기 전용 도구만 썼으면 LLM 문장을 검사해 내보낸다. 걸리면 정리하지 못했다고 한다
    - 도구를 안 썼으면 두 층 중 하나이거나 안내다. 1층 실무 답(answer_kind=skill)은 Skill 원문 근거 조각(skill_quote)이
      원문에 그대로 있어야 내보낸다 (V14). 1층이 안 되면 2층 일반 설명(general)을
      검사(숫자·특정 화물·세액 금지 등) 통과 시 내보낸다 (고정 꼬리표는 없앴다). 한 문장 잡담 답(unrelated)도 검사를 통과하면 쓴다.
      그 밖의 안내는 LLM 문장 대신 고정 문구를 쓴다. 앞 답을 베꼈거나(V13) 화면에 화물이 있는데
      도구를 안 불렀으면 한 번 다시 묻는다
    LLM이 첫 도구 전에 실패하면 LLMError를 그대로 올린다 (_route가 전 방식으로 보낸다). 도구가 이미 돌았으면
    그 결과로 답한다: 전 방식으로 넘기면 같은 조회를 한 번 더 하게 된다.
    """
    message_bls = list(refs.values())  # 이번 문장에 든 B/L (대화 기록의 것은 아래에서 refs에 더해진다)
    message_refs = dict(refs)  # {토큰: B/L} 이번 문장 것만. 여러 B/L 조회 결과에 토큰을 붙일 때 쓴다 (원문은 LLM에 안 간다)
    # 복사본에 대화 기록의 B/L을 더한다. 원본을 고치면 에이전트가 실패해 전 방식으로 갈 때 기록의 B/L을
    # 이번 문장의 B/L로 착각해 엉뚱한 화물을 조회한다
    refs = dict(refs)
    turns = _masked_history(history, refs)
    signals["refs"] = refs  # 대화 기록의 번호표까지 든 표. _agent가 답에 남은 [BLn]을 가릴 때 쓴다 (reveal_tokens)
    screen = _masked_screen(on_screen)  # 화면에 떠 있는 배들. 비었으면 None이고 LLM 입력에 칸이 안 생긴다
    offered_prev = bool(turns) and turns[-1]["role"] == "assistant" and _offered(turns[-1]["text"])  # 바로 앞 답이 우리 제안이었나
    # 답 검사에서 "사용자가 쓴 글"로 칠 것: 이번 문장과 앞에서 사용자가 쓴 줄. 사용자가 앞 턴에 말한 날짜를 되짚는 답이
    # V7에 걸리지 않게 한다. assistant 줄은 넣지 않는다 (V10이 우리 답의 낱말을 사용자 글로 오해하지 않게)
    user_text = " ".join([masked, *(t["text"] for t in turns if t["role"] == "user")])
    started = datetime.now(timezone.utc)  # 이번 문장 시작. 지난 후속 답의 위치 카드를 미니 지도에 쓰지 않으려고 (_map_payload)
    mcp_tools = mcp_client.read_only_tools() if run_tool else []
    mcp_names = {t["function"]["name"] for t in mcp_tools}
    done: list[ChatResult] = []  # 화물 조회·화물 질문·선박 검색 결과. 화면 카드와 검증된 답을 들고 있다
    ran: list[dict] = []  # 실제로 실행한 도구와 결과 {"name","arguments","result"}. LLM이 도중에 실패해도 남는다
    seen: dict[str, dict] = {}  # 같은 도구·같은 인자는 다시 실행하지 않고 앞 결과를 돌려준다 (프롬프트 규칙을 코드로)
    # 사용자가 이번 문장이나 앞 줄에서 날짜를 말했는가. 포워더 도착일은 판정 근거(trusted_eta)가 되므로
    # LLM이 지어낸 날짜를 받지 않으려고 본다 (CLAUDE.md trusted_eta)
    gave_date = user_gave_date(user_text)
    date_notes: list[str] = []  # 판매일에 붙는 코드 문장 (지난 날짜, 읽지 못함). 판정·days_margin은 바꾸지 않고 사실만 알린다

    def sale_from(args: dict) -> str | None:
        """check_cargo 인자의 판매일을 조회에 쓸 값으로. 사용자가 날짜를 말하지 않았으면 LLM 값은 버린다.
        쓰는 날짜가 오늘(KST)보다 앞이면 지난 날짜라고, 날짜 모양이 있는데 읽지 못했으면 쓰지 않았다고 문장으로 알린다."""
        raw = args.get("sale_due_date")
        value = sale_if_given(raw, user_text)
        unreadable = bool(raw) and value is None and gave_date  # LLM이 낸 값이 실제 없는 날짜 (2026-13-45 등)
        for m in re.finditer(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", masked):  # 문장에 "13월 45일"처럼 없는 날짜가 있다
            try:
                date(2024, int(m.group(1)), int(m.group(2)))  # 윤년으로 확인: 2월 29일은 읽는다
            except ValueError:
                unreadable = unreadable or value is None
        if unreadable and SALE_UNREADABLE not in date_notes:
            date_notes.append(SALE_UNREADABLE)
        if value and value < today:
            d = date.fromisoformat(value)
            note = SALE_PAST.format(m=d.month, d=d.day)
            if note not in date_notes:
                date_notes.append(note)
        return value

    # 한 문장에 B/L이 2~3개일 때의 조회 결과: {"results": [ChatResult...], "over": 상한 초과, "failed": 일부 실패}
    multi_state: dict = {}

    def look_up_many(bls: list[str], bl_type: str | None, sale_due_date: str | None) -> list[dict]:
        """B/L 여러 개를 동시에 조회한다 (최대 MAX_BLS_PER_TURN개, 넘으면 앞에서부터 자르고 안내를 붙인다).
        구분·판매일은 모두에게 같게 적용한다. 항차·포워더 도착일·MRN은 B/L 하나에 속하는 값이라 여럿일 때는 쓰지 않는다.
        스레드마다 contextvars 복사본을 따로 만들어 돌린다: 단계 소식(progress)·요청 ID·LLM 사용량 기록이 일꾼 스레드에서도 이 요청에 묶인다.
        한 개가 실패해도 나머지는 계속한다. LLM에 돌려주는 값은 [BLn] 토큰이 붙은 요약뿐이다 (_cargo_summary, 원문 B/L 없음)."""
        picked = bls[:MAX_BLS_PER_TURN]

        def one(bl: str) -> ChatResult | None:
            try:
                return _cargo(bl, bl_type, sale_due_date, session_id, context, run_agent, note=None, mrn=None, user_id=user_id)
            except Exception as e:  # noqa: BLE001 - 하나가 죽어도 요청 전체를 죽이지 않는다 (SDD 3.4)
                log_failure("chat_agent_tool", f"check_cargo {type(e).__name__}")
                return None

        with ThreadPoolExecutor(max_workers=len(picked)) as pool:
            futures = [pool.submit(contextvars.copy_context().run, one, bl) for bl in picked]
            outcomes = [f.result() for f in futures]
        multi_state["over"] = len(bls) > MAX_BLS_PER_TURN
        multi_state["failed"] = any(o is None for o in outcomes)
        multi_state["results"] = [o for o in outcomes if o is not None]
        token_of = {bl: token for token, bl in message_refs.items()}
        summaries = [{"bl_ref": token_of.get(bl), **_cargo_summary(o.agent)} for bl, o in zip(picked, outcomes) if o is not None]
        done.extend(multi_state["results"])  # 쓰는 순서는 B/L이 문장에 나온 순서 그대로
        return summaries

    def glued_parts(result: ChatResult, bl: str) -> list[str]:
        """B/L 하나를 조회했는데 세관에 없고 길이가 두 B/L을 붙인 만큼 길면, 둘 이상으로 나눠 모두 세관에 있는 나눔을 돌려준다.
        없으면 빈 목록 (평소처럼 "조회 결과가 없습니다"). 나눈 번호는 문장 속 B/L 목록(message_bls·message_refs)에 넣어 뒤의 조회와
        LLM에 가는 [BLn] 토큰이 일관되게 한다. 원문 B/L은 LLM에 가지 않는다 (services/judge/bl_parse.py).
        routers.agent는 이 모듈이 올라올 때 서로 부르지 않게 쓰는 자리에서 가져온다."""
        from backend.app.routers import agent as agent_router  # noqa: PLC0415
        resp = result.agent
        if not (resp and resp.status == "insufficient" and resp.answer == agent_router.NO_CARGO and len(bl) >= bl_parse.GLUED_MIN):
            return []
        parts = bl_parse.split_not_found(bl, bl_parse.exists_in_customs)
        for part in parts:
            if part not in message_refs.values():
                n = len(refs) + 1
                while f"[BL{n}]" in refs:  # 대화 기록의 토큰과 겹치지 않는 다음 번호
                    n += 1
                message_refs[f"[BL{n}]"] = refs[f"[BL{n}]"] = part
        if parts:
            message_bls[:] = [b for b in message_bls if b != bl] + [p for p in parts if p not in message_bls]
            multi_state["glued"] = True
        return parts

    recall_state: dict = {}  # 이번 문장의 메모 꺼내 보기 결과 (select_memo가 돌려준 모양). 최종 답을 코드가 고른다

    def run_recall(args: dict) -> dict:
        """메모 꺼내 보기 (읽기 전용). 로그인 사용자의 메모만 읽는다. 결과 글은 사용자가 넣은 글이라 자료일 뿐이다 (프롬프트 Trust boundary).
        ok가 아니면 문장은 코드가 쓴다 (memo_reply_text)."""
        topic = args.get("topic") if args.get("topic") in MEMO_TOPICS else "any"
        query = args.get("query") if isinstance(args.get("query"), str) else None
        query = " ".join(query.split())[:120] if query else None
        if query and (re.search(r"\[(?:BL|MRN|CNTR)", query, re.IGNORECASE) or guard.looks_like_injection(query)):
            query = None
        if not user_id:
            recall_state["result"] = {"status": "anonymous"}
            return recall_state["result"]
        try:
            items, cargos = _load_memo(user_id)
        except Exception as e:  # noqa: BLE001 - 메모를 못 읽어도 요청은 살린다. 종류만 남긴다
            log_failure("chat_recall", type(e).__name__)
            return _tool_error("memo_failed", "The memo could not be read.")
        ship = (screen or {}).get("vessel", {}).get("ship_name") if screen else None
        key = cargo.cargo_key(context.bl_no) if context is not None and context.bl_no else None
        recall_state["result"] = select_memo(items, cargos, topic, query, masked, ship, key)
        return recall_state["result"]

    def recall_reply(text: str) -> str | None:
        """메모 꺼내 보기를 한 문장의 최종 답. ok면 LLM 문장이 검사(전화번호는 돌려준 항목에 그대로 있어야 함)를 통과할 때만 쓰고,
        아니면 코드가 쓴 목록이다. 항목이 없으면 None."""
        result = recall_state["result"]
        ship_ask = bool(SHIP_WORD.search(masked))
        if result.get("status") == "ok" and text and len(text) <= 400 and not guard.looks_like_injection(text) \
                and not re.search(r"\[(?:BL|MRN|CNTR)", text) and memo_phones_ok(text, result):
            return text
        if result.get("status") == "ok" and text:
            log_failure("chat_agent_reply", "recall_rejected")
        return memo_reply_text(result, ship_ask)

    watch_out: dict = signals.setdefault("watch", {})  # {"msg": 코드가 쓴 문장, "set": {"bl_no","on"}, "refused": 거절됨}

    def kakao_tail() -> str | None:
        """문장에 카톡·카카오 말이 있을 때만: 카카오톡 연결 상태를 사실대로 말하는 꼬리 문장. 말이 없거나 상태를 못 읽으면 None"""
        if not KAKAO_WORD.search(masked) or kakao is None or kakao.linked is None:
            return None
        try:
            return KAKAO_LINKED_TAIL if kakao.linked() else KAKAO_UNLINKED_TAIL
        except Exception as e:  # noqa: BLE001 - 부가 안내다. 못 읽으면 기본 문장으로 간다
            log_failure("chat_kakao", type(e).__name__)
            return None

    def run_watch(args: dict) -> dict:
        """지켜보기 켜기·끄기 도구. DB에 쓰는 동작이라 LLM 판단만으로는 하지 않는다:
        (a) 가린 문장에 지켜보기 낱말이 있거나 (b) 바로 앞 답이 우리 제안이고 이번 문장이 짧은 긍정일 때만 한다.
        (b)는 "응"이 켜기라는 뜻이라 LLM이 on=false를 보내도 켠다. 문장은 코드가 쓰고(watch_out["msg"]) LLM 글은 안 쓴다.
        대상은 이번 문장의 B/L 하나, 없으면 화면의 화물이다."""
        on = args.get("on")
        explicit = bool(WATCH_WORDS.search(masked)) and not wants_send_now(masked)  # 지금 보내 달라는 말은 지켜보기를 바꾸지 않는다
        yes = offered_prev and bool(AFFIRM.fullmatch(masked.strip()))
        if not isinstance(on, bool) or not (explicit or yes):
            watch_out["refused"] = True
            return _tool_error("not_requested", "The user did not ask to watch or stop watching. Do not call set_watch on your own.")
        on = on if explicit else True
        distinct = list(dict.fromkeys(message_bls))
        if len(distinct) >= 2:
            watch_out["msg"] = WATCH_ONE_AT_A_TIME
            return _tool_error("one_at_a_time", "Only one cargo can be watched per message.")
        if distinct and not any(r["name"] == "check_cargo" for r in ran) and (context is None or distinct[0] != context.bl_no):
            # 이번 문장에서 처음 말한 화물은 조회가 끝나야 저장된다 (services/watch/watch.set_watch not_saved). 조회부터 하게 한다
            return _tool_error("lookup_first", "Call check_cargo for this B/L first, then call set_watch.")
        bl = distinct[0] if distinct else (context.bl_no if context else None)
        if not bl:
            watch_out["msg"] = WATCH_NO_CARGO
            return _tool_error("no_cargo", WATCH_NO_CARGO)
        if user_id is None:
            watch_out["msg"] = WATCH_NEED_LOGIN  # 아무것도 바꾸지 않는다
            return _tool_error("login_required", "Not logged in. Nothing was changed.")
        if watch is None:
            watch_out["msg"] = WATCH_FAIL_REPLY["db"]
            return _tool_error("unavailable", "The watch store is not available.")
        try:  # 이미 원하는 상태면 다시 켜지 않고 그렇다고 말한다. 상태를 못 읽으면 그냥 바꿔 본다
            if bool(watch.state(bl).get("watch")) == on:
                tail = kakao_tail() if on else None
                watch_out["msg"] = ((f"{WATCH_ALREADY_HEAD} {tail}" if tail else WATCH_ALREADY_ON) + "\n" + WATCH_PAGE_LINE) if on else WATCH_ALREADY_OFF
                return {"ok": True, "watching": on, "unchanged": True}
        except Exception as e:  # noqa: BLE001
            log_failure("chat_watch", type(e).__name__)
        try:
            result = watch.tool(bl, on)
        except Exception as e:  # noqa: BLE001 - 저장소 문제가 요청 전체를 죽이지 않게
            log_failure("chat_watch", type(e).__name__)
            result = {"error": "db"}
        if "error" in result:
            watch_out["msg"] = WATCH_FAIL_REPLY.get(result["error"], WATCH_FAIL_REPLY["db"])
            if result["error"] == "not_saved" and any(_is_no_result(d) and d.request and d.request.bl_no == bl for d in done):
                # 같은 문장의 조회가 없음으로 끝나 저장될 화물이 없는 것이지 "저장되는 중"이 아니다
                watch_out["msg"] = WATCH_NOT_FOUND
            return _tool_error(str(result["error"]), "Could not change watching.")
        tail = kakao_tail() if result.get("on") else None
        watch_out.update(msg=((f"{WATCH_ON_PLAIN} {tail}" if tail else WATCH_ON_REPLY) + "\n" + WATCH_PAGE_LINE) if result.get("on") else WATCH_OFF_REPLY,
                         set={"bl_no": bl, "on": bool(result.get("on"))})
        return {"ok": True, "watching": bool(result.get("on"))}

    def vessel_error_text(kind: str) -> str:
        """배 지켜보기 오류 종류를 사용자 문장으로. 문장은 routers/watch.py _VESSEL_ERRORS와 같은 것을 쓴다 (복사하지 않는다).
        라우터는 이 모듈이 올라올 때 서로 부르지 않게 쓰는 자리에서 가져온다."""
        from backend.app.routers import watch as watch_router  # noqa: PLC0415
        entry = watch_router._VESSEL_ERRORS.get(kind)
        return entry[1] if entry else VESSEL_DEFAULT_ERROR

    def vessel_target(name_arg) -> dict | str:
        """지켜볼 배 한 척을 코드가 정한다 (LLM이 아니라). 돌려주는 값: 배 {name, flag, dest, eta, call_sign, mmsi} 또는 못 정한 이유 문장.
        순서: (1) 사용자가 쓴 배 이름 (2) 화면에서 고른 줄(selected) (3) 화면에 배가 정확히 한 척 (4) 되묻기.
        이름은 사용자가 이번 문장·앞 줄에 실제로 쓴 글자일 때만 쓴다 (LLM이 지어낸 이름으로 엉뚱한 배를 올리지 않게)."""
        rows = list((screen or {}).get("arrivals") or [])
        shown_vessel = (screen or {}).get("vessel")
        if isinstance(name_arg, str) and name_arg.strip():
            name = " ".join(name_arg.split())[:80]
            wanted = vessel_pick.normalize_name(name)
            typed = vessel_pick.normalize_name(user_text)
            if not wanted or guard.looks_like_injection(name) or wanted not in typed:
                return VESSEL_ASK_WHICH
            for row in rows:  # 화면에 같은 이름의 줄이 있으면 그 줄이 가장 믿을 만하다 (호출부호가 있다)
                if vessel_pick.normalize_name(row.get("ship_name")) == wanted:
                    return {"name": row["ship_name"], "flag": row.get("flag"), "dest": None, "eta": row.get("eta"),
                            "call_sign": row.get("call_sign"), "mmsi": None}
            if shown_vessel and vessel_pick.normalize_name(shown_vessel.get("ship_name")) == wanted and shown_vessel.get("mmsi"):
                return {"name": shown_vessel["ship_name"], "flag": shown_vessel.get("flag"), "dest": shown_vessel.get("destination"),
                        "eta": None, "call_sign": None, "mmsi": shown_vessel["mmsi"]}
            if run_tool is None or "get_vessel_candidates" not in mcp_names:
                return VESSEL_NOT_FOUND
            try:
                found = (run_tool("get_vessel_candidates", {"ship_name": name}) or {}).get("candidates") or []
            except Exception as e:  # noqa: BLE001 - 후보 조회가 죽어도 요청 전체를 죽이지 않는다
                log_failure("chat_agent_tool", f"watch_vessel candidates {type(e).__name__}")
                return VESSEL_NOT_FOUND
            same = [c for c in found if vessel_pick.normalize_name(c.get("name")) == wanted]
            pool = same or (found if len(found) == 1 else [])  # 이름이 같은 배, 없으면 후보가 딱 한 척일 때만
            if not pool:
                return VESSEL_MANY if len(found) > 1 else VESSEL_NOT_FOUND
            if len({c.get("mmsi") for c in pool}) != 1:
                return VESSEL_MANY  # 같은 이름이 여러 척이면 확실하지 않다. 코드가 고르지 않는다
            c = pool[0]
            return {"name": c.get("name") or name, "flag": c.get("flag"), "dest": c.get("dest"), "eta": None,
                    "call_sign": c.get("call_sign"), "mmsi": c.get("mmsi")}
        picked = [r for r in rows if r.get("selected")]
        if len(picked) == 1:
            row = picked[0]
        elif not picked and len(rows) == 1 and not shown_vessel:
            row = rows[0]
        elif not picked and not rows and shown_vessel:
            return {"name": shown_vessel["ship_name"], "flag": shown_vessel.get("flag"), "dest": shown_vessel.get("destination"),
                    "eta": None, "call_sign": None, "mmsi": shown_vessel.get("mmsi")}
        else:
            return VESSEL_ASK_WHICH
        return {"name": row["ship_name"], "flag": row.get("flag"), "dest": None, "eta": row.get("eta"),
                "call_sign": row.get("call_sign"), "mmsi": None}

    def run_watch_vessel(args: dict) -> dict:
        """배 한 척 지켜보기 켜기·끄기 도구. run_watch와 같은 안전 규칙이다: 가린 문장에 켜기 낱말이 있어야 하고
        (VESSEL_WATCH_WORDS, 지금 보내 달라는 말은 제외) 로그인해야 한다. 어느 배인지는 vessel_target이 코드로 정한다. 문장은 코드가 쓴다."""
        on, ship_name = args.get("on"), args.get("ship_name")
        if not isinstance(on, bool) or not VESSEL_WATCH_WORDS.search(masked) or wants_send_now(masked):
            watch_out["refused"] = True
            return _tool_error("not_requested", "The user did not ask to watch or stop watching a ship. Do not call watch_vessel on your own.")
        if user_id is None:
            watch_out["msg"] = VESSEL_NEED_LOGIN  # 아무것도 바꾸지 않는다
            return _tool_error("login_required", "Not logged in. Nothing was changed.")
        hooks = watch.vessel if watch is not None else None
        if hooks is None:
            watch_out["msg"] = VESSEL_UNAVAILABLE
            return _tool_error("unavailable", "The vessel watch store is not available.")
        target = vessel_target(ship_name)
        if isinstance(target, str):
            watch_out["msg"] = target
            return _tool_error("which_ship", target)
        try:
            mmsi = target["mmsi"]
            if not mmsi:  # 입항 예정 목록 줄은 MMSI가 없다. 호출부호로 찾는다 (이름이 같은 배 중 고르기는 vessel_pick 규칙)
                if not target.get("call_sign"):
                    watch_out["msg"] = VESSEL_ASK_WHICH if on else VESSEL_OFF_NO_MMSI
                    return _tool_error("which_ship", "The ship has no call sign or MMSI on screen.")
                found = hooks.resolve(target["call_sign"], target["name"])
                if "error" in found:
                    watch_out["msg"] = vessel_error_text(str(found["error"]))
                    return _tool_error(str(found["error"]), "Could not find this ship.")
                mmsi = found["mmsi"]
            result = (hooks.add(mmsi, target["name"], target.get("flag"), target.get("dest"), target.get("eta"), target.get("call_sign"))
                      if on else hooks.remove(mmsi))
        except Exception as e:  # noqa: BLE001 - 저장소 문제가 요청 전체를 죽이지 않게
            log_failure("chat_watch", f"vessel {type(e).__name__}")
            result = {"error": "db"}
        if "error" in result:
            watch_out["msg"] = vessel_error_text(str(result["error"]))
            return _tool_error(str(result["error"]), "Could not change watching this ship.")
        shown = target["name"]
        watch_out.update(msg=(VESSEL_ON_REPLY.format(name=shown) + "\n" + WATCH_PAGE_LINE) if on else VESSEL_OFF_REPLY.format(name=shown),
                         vessel_set={"mmsi": int(mmsi), "name": shown, "on": on})
        return {"ok": True, "watching": on}

    kakao_out: dict = signals.setdefault("kakao", {})  # {"msg": 코드가 쓴 문장, "done": 보냈다, "refused": 거절됨}

    def run_kakao(args: dict) -> dict:
        """지금 상태를 카카오톡으로 보내는 도구. 부작용이라 가린 문장에 "카톡으로 보내 줘"류가 있을 때만 한다.
        대상은 이번 문장의 B/L 하나, 없으면 화면의 화물이다. 보낼 글은 코드가 저장된 화물 줄로 쓰고(kakao_now_text) LLM은 글에 관여하지 않는다.
        같은 문장에서 두 번 불려도 한 번만 보낸다. 같은 사용자·화물은 5분에 한 번. 보내기는 재시도하지 않는다 (services/watch/kakao 규칙)."""
        if kakao_out.get("done"):
            return {"ok": True, "sent": True}
        if not wants_send_now(masked):
            kakao_out["refused"] = True
            return _tool_error("not_requested", "The user did not ask to send the status to KakaoTalk now. Do not call send_kakao on your own.")
        distinct = list(dict.fromkeys(message_bls))
        if len(distinct) >= 2:
            kakao_out["msg"] = KAKAO_ONE_AT_A_TIME
            return _tool_error("one_at_a_time", "Only one cargo can be sent per message.")
        if distinct and not any(r["name"] == "check_cargo" for r in ran) and (context is None or distinct[0] != context.bl_no):
            return _tool_error("lookup_first", "Call check_cargo for this B/L first, then call send_kakao.")
        bl = distinct[0] if distinct else (context.bl_no if context else None)
        if not bl:
            kakao_out["msg"] = KAKAO_NO_CARGO
            return _tool_error("no_cargo", KAKAO_NO_CARGO)
        if user_id is None:
            kakao_out["msg"] = KAKAO_NEED_LOGIN  # 아무것도 보내지 않는다
            return _tool_error("login_required", "Not logged in. Nothing was sent.")
        key = cargo.cargo_key(bl)
        if kakao is None or key is None:
            kakao_out["msg"] = KAKAO_FAILED
            return _tool_error("unavailable", "KakaoTalk sending is not available.")
        if not _kakao_reserve(user_id, key):
            kakao_out["msg"] = KAKAO_COOLDOWN_REPLY
            return _tool_error("cooldown", "Sent a moment ago.")
        try:
            row = kakao.row(bl)
            text = kakao_now_text(row, datetime.now(KST).date()) if row else None
            if text is None:  # 줄이 아직 없거나(조회 직후 저장 중) 판정이 없다. 보내지 않는다
                _kakao_release(user_id, key)
                kakao_out["msg"] = KAKAO_NOT_READY if row is None else KAKAO_NO_VERDICT
                return _tool_error("no_status", "There is no stored status to send yet.")
            result = kakao.send(text)
        except Exception as e:  # noqa: BLE001 - 저장소·카카오 문제가 요청 전체를 죽이지 않게. 종류만 남긴다
            log_failure("chat_kakao", type(e).__name__)
            result = {"error": "db"}
        if "error" in result:
            _kakao_release(user_id, key)  # 못 보냈으면 곧 다시 시도할 수 있게
            kind = str(result["error"])
            kakao_out["msg"] = KAKAO_NOT_LINKED if kind == "not_linked" else KAKAO_FAIL_REPLY.get(kind, KAKAO_FAILED)
            return _tool_error(kind, "Could not send to KakaoTalk.")
        kakao_out.update(msg=KAKAO_SENT, done=True)
        return {"ok": True, "sent": True}

    # 지금 보내기만 바라는 짧은 말("지금 카톡으로 보내 줘")도 LLM 없이 코드가 처리한다. 새 B/L이 없으면 화면 화물(없으면 B/L을 묻는다)
    if not message_bls and wants_send_now(masked) and len(masked.strip()) <= SEND_ONLY_MAX:
        run_kakao({})
        return ChatResult(kind="message", reply=kakao_out.get("msg") or KAKAO_FAILED)

    # 지켜보기만 바라는 짧은 말("응", "응 지켜봐 줘", "그만 지켜봐도 돼")은 LLM을 부르지 않고 코드가 바로 처리한다 (실측:
    # "응 지켜봐 줘"에 LLM이 화물 질문(ask_cargo)까지 불러 엉뚱한 화물 답이 지켜보기 문장 앞에 붙었다).
    # 조건: 새 B/L이 없고 화면에 화물이 있고, (앞 답이 제안이고 짧은 긍정) 또는 (WATCH_REQUEST 모양의 WATCH_ONLY_MAX자 이하 문장)
    short = masked.strip()
    # 입항 선박 목록이 화면에 있는데 "이 배 지켜봐 줘"처럼 배를 가리키면 화물 지켜보기로 가로채지 않는다: LLM이 watch_vessel을 고른다
    about_ship = bool(screen and screen.get("arrivals")) and bool(SHIP_WORD.search(short)) and "화물" not in short
    if not message_bls and context is not None and not about_ship and (
            (offered_prev and AFFIRM.fullmatch(short)) or (WATCH_REQUEST.search(short) and len(short) <= WATCH_ONLY_MAX)):
        run_watch({"on": not WATCH_STOP.search(short)})
        return ChatResult(kind="message", reply=watch_out.get("msg") or WATCH_HOW, watch_set=watch_out.get("set"),
                          watch_vessel_set=watch_out.get("vessel_set"))

    # 이번 문장의 근거 목록. 도구마다 근거 카드를 모아 E1, E2... id를 붙인다 (services/chat/citations.py).
    # exposed: LLM에게 보여 준 id. LLM이 문장을 쓰는 도구(여러 B/L 비교, 읽기 전용 조회)만 보여 준다. 화물 한 건의 답은 코드가 쓰는 문장이라
    # LLM 입력에는 근거를 안 넣는다 (UNI-PASS 값을 LLM에 더 넘기지 않으려고, CLAUDE.md). 그 근거는 화면 칩용으로 모으기만 한다
    turn_items: list[dict] = []
    exposed_ids: set[str] = set()
    signals["evidence"], signals["exposed"] = turn_items, exposed_ids

    def register(cards: list, expose: bool) -> str | None:
        """카드를 목록에 더한다. id는 이번 문장 전체에서 이어서 센다. expose면 LLM에 줄 줄 묶음 글을 돌려준다."""
        items = cite.build_evidence_list(cards)
        for item in items:
            item["id"] = f"E{len(turn_items) + 1}"
            turn_items.append(item)
            if expose:
                exposed_ids.add(item["id"])
        return cite.evidence_prompt_block(items) if expose and items else None

    def mcp_cards(name: str, r: dict) -> list[dict]:
        """읽기 전용 MCP 도구 결과의 값 칸을 근거 카드로. 모든 도구 응답에 source·fetched_at이 있다 (SDD 3.4). 목록·중첩 값은 후보만 풀어 쓴다."""
        out = []
        for k, v in r.items():
            if k not in ("source", "fetched_at", "cached_at") and v not in (None, "") and not isinstance(v, (dict, list, bool)):
                out.append({"source": r.get("source") or name, "field": k, "value": v, "fetched_at": r.get("fetched_at")})
        for n, c in enumerate((r.get("candidates") or [])[:ARRIVALS_SHOWN], 1):
            for k in ("name", "flag", "dest", "call_sign"):
                if isinstance(c, dict) and c.get(k) not in (None, ""):
                    out.append({"source": r.get("source") or name, "field": f"candidate{n}.{k}", "value": c[k], "fetched_at": r.get("fetched_at")})
        return out

    def with_evidence(name: str, result: dict) -> dict:
        """도구 결과에서 근거를 모으고, LLM이 문장을 쓰는 도구면 결과에 evidence 글(줄마다 [E#])을 붙여 돌려준다. 실패한 결과는 그대로."""
        if not isinstance(result, dict) or "error" in result or result.get("rerouted_to"):  # 돌려 보낸 호출은 ask_cargo가 이미 근거를 모았다 (A4)
            return result
        now = datetime.now(timezone.utc)
        block = None
        if name == "check_cargo" and "cargos" in result:
            # 여러 B/L: 줄마다 어느 화물 값인지 [BLn] 번호표를 칸 이름 앞에 붙인다 (원문 B/L은 쓰지 않는다)
            cards = [{"source": c.source, "field": f"{row.get('bl_ref') or ''} {c.field}".strip(), "value": c.value, "fetched_at": c.fetched_at}
                     for row, r in zip(result["cargos"], multi_state.get("results", [])) if r.agent is not None for c in r.agent.evidence]
            block = register(cards, True)
        elif name in ("check_cargo", "ask_cargo"):
            if done and done[-1].agent is not None:
                register(list(done[-1].agent.evidence), False)
        elif name == "search_arrivals":
            # 해수부 입항 예정 목록. 목록은 10분 캐시라 조회 시각은 이 요청 시각으로 적는다
            cards = [{"source": "mof", "field": f"{v['ship_name']} {k}", "value": v.get(k), "fetched_at": now}
                     for v in (done[-1].vessels[:ARRIVALS_SHOWN] if done else []) for k in ("expected_arrival", "previous_port")]
            register(cards, False)
        elif name in mcp_names:
            block = register(mcp_cards(name, result), True)
        return {**result, "evidence": block} if block else result

    rerouted: dict = {}  # 실험 A4: 화면 화물의 배를 묻는 위치 호출을 ask_cargo로 돌렸는가 {"own": True}

    def is_cargo_vessel_call(name: str, args: dict) -> bool:
        """위치·거리 도구 호출이 화면 화물의 배를 가리키는가 (A4). 화면 배(on_screen.vessel)와 MMSI나 이름이 같으면 참.
        거리 도구는 배 이름 칸이 없어서, 앞에서 화물 배의 위치 호출을 돌려 보냈거나 화면 배의 좌표를 그대로 넘겼을 때 참이다."""
        vessel = (screen or {}).get("vessel") or {}
        if not vessel:
            return False
        if name == "get_live_position":
            return args.get("mmsi") is not None and args.get("mmsi") == vessel.get("mmsi")
        if rerouted.get("own"):
            return True
        near = lambda a, b: isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) < 0.05  # noqa: E731
        return near(args.get("lat"), vessel.get("lat")) and near(args.get("lng", args.get("lon")), vessel.get("lng"))

    def run(name: str, args: dict) -> dict:
        """LLM이 고른 도구 하나를 실행한다. 같은 호출은 한 번만, 화물 도구는 한 문장에 한 번만, 예외는 도구 실패로 돌려준다.
        MCP 도구가 예외를 던지지 않는 것과 같은 원칙이다 (SDD 3.4): 도구 하나가 죽어도 요청 전체가 500이 되면 안 된다."""
        key = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}"
        if key in seen and name not in ("set_watch", "send_kakao", "watch_vessel"):  # 지켜보기는 조회가 끝나기를 기다렸다 다시 부를 수 있어 앞 결과를 쓰지 않는다 (같은 일은 두 번 해도 같다)
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
        result = with_evidence(name, result)  # 근거를 모으고, LLM이 문장을 쓰는 도구에는 evidence 글을 붙인다 (같은 호출의 앞 결과도 이 모양으로 돌아간다)
        seen[key] = result
        ran.append({"name": name, "arguments": args, "result": result})
        return result

    def _run_tool(name: str, args: dict) -> dict:
        """도구 하나의 실제 실행. 칸 검사는 전 방식(_classic)과 같은 기준이다."""
        if name == "check_cargo":
            token = args.get("bl_ref")
            if token is not None and not isinstance(token, str):  # 모델이 목록 등 다른 모양을 보내면 요청이 죽지 않게 도구 실패로 돌려준다
                return _tool_error("need_bl", NEED_BL)
            distinct = list(dict.fromkeys(message_bls))
            if len(distinct) >= 2:
                # 한 문장에 서로 다른 B/L이 2~3개: 모두 조회하고 함께 보여 준다. bl_ref는 무시한다: 모든 B/L이 대상이다
                bl_type = args.get("bl_type") if args.get("bl_type") in ("MASTER", "HOUSE") else None
                summaries = look_up_many(distinct, bl_type, sale_from(args))
                if not summaries:
                    return _tool_error("tool_failed", "This lookup failed.")
                return {"cargos": summaries}
            bl = refs.get(token) if token else (message_bls[0] if message_bls else (context.bl_no if context else None))
            if not bl:  # 목록에 없는 토큰이거나 조회할 화물이 없다 (EC-02). 번호를 지어내도 여기서 막힌다
                return _tool_error("need_bl", NEED_BL)
            bl_type = args.get("bl_type") if args.get("bl_type") in ("MASTER", "HOUSE") else None
            # 항차 번호는 사용자가 실제로 쓴 글자일 때만 쓴다. LLM이 만든 값으로 배를 가르면 안 된다
            voyage = str(args.get("voyage_no") or "").strip() or None
            if voyage and not _VOYAGE_OK.fullmatch(voyage):
                # 요청 계약(schemas/agent.py voyage_no)에 안 맞는 항차(한글이 섞임·20자 초과)는 넘기지 않는다.
                # 넘기면 AgentRequest가 ValidationError로 터진다. 항차 없이 조회하면 되묻기가 다시 묻는다
                voyage = None
            if voyage and re.sub(r"\s+", "", voyage) not in re.sub(r"\s+", "", masked):
                voyage = None
            eta = _valid_date(args.get("forwarder_eta")) if gave_date else None
            result = _cargo(bl, bl_type, sale_from(args), session_id, context, run_agent,
                            note=None, mrn=mrn, user_id=user_id, voyage_no=voyage, forwarder_eta=eta)
            parts = glued_parts(result, bl)
            if parts:  # 붙여 쓴 번호였다: 나눈 B/L들을 여러 건 조회 길로 돌린다
                summaries = look_up_many(parts, bl_type, sale_from(args))
                return {"cargos": summaries} if summaries else _tool_error("tool_failed", "This lookup failed.")
            if eta:  # LLM이 풀어낸 날짜라 사용자가 맞는지 볼 수 있게 답에 밝힌다 (근거 카드에도 있다, services/judge/evidence.py)
                result = replace(result, reply=f"{result.reply}\n(포워더가 알려 준 입항일 {eta}로 조회했어요.)")
            done.append(result)
            return _cargo_summary(result.agent)
        if name == "ask_cargo":
            if context is None:
                return _tool_error("no_cargo", NO_CARGO)  # EC-03
            question = str(args.get("question") or masked)[:300]  # 후속 질문은 300자 (schemas/agent.py)
            req = context.model_copy(update={"session_id": session_id, "follow_up_question": question,
                                             "resolved_mmsi": None, "voyage_no": None, "forwarder_eta": None})
            resp = run_agent(req)
            # 원문 기준 V10 한 번 더 (_classic과 같은 검사). 판정 흐름의 V10은 에이전트가 다시 쓴 질문만 본다.
            # 다시 쓰면서 공격 조각이 빠지면 원문의 표식을 답이 옮겨도 못 잡으므로, 사용자가 실제로 쓴 문장(masked)과 한 번 더 대조한다
            if _copies_user_marker(resp, masked):
                log_failure("chat", "follow-up answer copied words from original message")
                resp = resp.model_copy(update={"answer": FOLLOW_UP_REFUSED})
            done.append(ChatResult(kind="cargo", reply=resp.answer, agent=resp, request=context))
            return {"answer": resp.answer}
        if name == "search_arrivals":
            # place·place_label은 LLM 출력인데 답 문장에 그대로 들어간다. 전 방식과 같은 검사를 한다 (주입 방어)
            place = str(args.get("place") or "").strip() or None
            # place는 "어디에서 오는 배"다. 부산·한국 같은 도착지면 빈 표만 나오므로 LLM에 돌려보내 다른 길을 고르게 한다.
            # 단 문장에 식별자 모양 글자(TEST41 등)가 있을 때만이다: 그때는 배·화물 위치 질문을 잘못 고른 것이다 ("TEST41 선박 위치").
            # 식별자가 없으면 "이번 주 부산 들어오는 배"처럼 입항 목록 질문이라 search_vessels가 거르지 않고 전체를 보인다
            if (_is_destination(place) or _is_destination(args.get("place_label"))) and _ID_LIKE.search(masked):
                return _tool_error("place_is_destination", "place means where the ships come from (previous port), not Busan or "
                                   "Korea. Use null for all arrivals, or a foreign country or port. If the message is not asking "
                                   "which ships come from somewhere, do not call search_arrivals.")
            # 입항 목록 속 배 이름이 문장에 통째로 있으면 목록이 아니라 그 배를 찾는다 (E2E: "EVER GIVEN 위치"가 전체 목록으로 답해졌다)
            try:
                upper = masked.upper()
                names = sorted({(p.ship_name or "").strip().upper() for p in _arrivals(DAYS_MAX)}, key=len, reverse=True)
            except MofError:
                names, upper = [], ""
            hit = next((n for n in names if len(n) >= 3 and re.search(rf"(?<![A-Z0-9]){re.escape(n)}(?![A-Z0-9])", upper)), None)
            if hit:
                found = search_ship_name(hit)
                if found is not None:
                    done.append(found)
                    return {"reply": found.reply, "total": len(found.vessels)}
            # place가 없는 위치·어디 질문은 목록 질문이 아니다. 지명 없이 "배 위치"만 물으면 배 이름을 찾는 도구로 보낸다
            if not args.get("place") and re.search(r"위치|어디", masked) and not re.search(r"들어오|입항|오는\s*배|목록|들어와", masked):
                return _tool_error("not_a_list_question", "search_arrivals lists ships arriving at Busan; it cannot find where one ship is. "
                                   "To find a named ship use get_vessel_candidates, then get_live_position.")
            # 지명도 없고 배·입항을 묻는 말도 없는 문장("?" 같은 빈 질문)에 입항 목록 전체를 내지 않는다. 웹 검색을 뺀 뒤 생긴 일 (e2e, ADR 0020)
            if not args.get("place") and not re.search(r"배|선박|입항|들어오|들어와|오는|도착|목록|부산", masked):
                return _tool_error("not_a_list_question", "The user did not ask for ships arriving at Busan. Do not call search_arrivals. "
                                   "Answer briefly and ask what cargo (B/L) or ship they want to check.")
            if place and (not _PLACE.match(place) or len(place.split()) > 4 or guard.looks_like_injection(place)):
                place = None
            label = args.get("place_label")
            if not (isinstance(label, str) and label and re.sub(r"\s+", "", label) in re.sub(r"\s+", "", masked)):
                label = None
            # bool도 int라서 따로 막는다 (true가 "앞으로 True일"로 답에 들어갔다, 테스트에서 발견)
            days = args.get("days") if isinstance(args.get("days"), int) and not isinstance(args.get("days"), bool) else None
            result = search_vessels(place, days, label)
            span = asked_days(masked)
            if span and span > DAYS_MAX and result.kind == "vessels":  # 사용자가 더 긴 기간을 물었다: 줄여 보여 준 것을 말한다
                result = replace(result, reply=f"{result.reply}\n{ARRIVALS_LIMIT_NOTE.format(n=DAYS_MAX)}")
            done.append(result)
            shown = [{k: v[k] for k in ("ship_name", "call_sign", "nationality", "previous_port", "expected_arrival", "is_cargo")}
                     for v in result.vessels[:ARRIVALS_SHOWN]]
            return {"reply": result.reply, "total": len(result.vessels), "vessels": shown}
        if name == "set_watch":
            return run_watch(args)
        if name == "watch_vessel":
            return run_watch_vessel(args)
        if name == "send_kakao":
            return run_kakao(args)
        if name == "recall_memo":
            # 저장한 것을 묻지 않은 문장(무료 기간·검사 기간 같은 실무 질문)에 모델이 메모 꺼내 보기를 고르면 돌려보낸다.
            # 웹 검색을 뺀 뒤(ADR 0020) 모르는 실무 질문에 남은 도구를 고르는 일이 생겼다 (e2e). 답은 Skill 문서나 not_in_skills로 한다
            if not is_memo_question(masked):
                log_failure("chat_agent_tool", "recall_memo_not_memo_question")
                return _tool_error("not_a_memo_question", "The user did not ask about something they saved or told Marvia. "
                                   "Do not call recall_memo. Answer from the Skill documents, or with not_in_skills if they do not cover it.")
            return run_recall(args)
        if name in mcp_names:
            if context is not None and name in ("get_live_position", "estimate_distance") and is_cargo_vessel_call(name, args):
                # 실험 A4 (항상 켜짐): 화면 화물의 배("이 배")를 위치·거리 도구로 따로 찾지 않는다. 그 배의 위치는 화물 조회 결과(ask_cargo)가 이미 알고 있고
                # 코드가 검증한 문장으로 답한다. 도구를 부른 호출은 ask_cargo로 돌려 보낸다 (결과 이름 rerouted_to로 모델도 안다)
                rerouted["own"] = True
                answered = run("ask_cargo", {"question": masked[:300]})
                return {"rerouted_to": "ask_cargo", **answered} if "error" not in answered else answered
            progress.step(MCP_STAGES.get(name, ""))  # 모르는 도구 이름이면 단계를 보내지 않는다 (progress.step)
            return run_tool(name, args)
        log_failure("chat_agent_tool", f"unknown_tool {name}")
        return _tool_error("unknown_tool", f"no tool named {name}")

    tools = AGENT_TOOLS + mcp_tools
    skills = llm.skills_reference(llm.CHAT_AGENT_SKILLS)  # V14 근거 조각을 찾는 원문. 지시문은 넣지 않는다 (도메인 지식의 출처가 아니다)
    reference = llm.skills_reference(llm.CHAT_AGENT_SKILLS, llm.CHAT_AGENT_PROMPT) + " " + today
    grounded = reference + OTHER_REPLY  # 도구 없는 답의 V7·V9·V10 근거. OTHER_REPLY의 낱말은 써도 된다
    # 이 대화에서 앞서 보여 준 답. 같은 답을 되풀이하면 이번 질문을 처리하지 않은 것이다 (V13)
    earlier = [t["text"] for t in turns if t["role"] == "assistant"]

    # 2층(일반 설명)과 잡담 답의 근거 글. 고정 문구와 오늘 날짜뿐이다: Skill 문서와 지시문에 든 숫자는 근거가 아니다 (V7이 엄격하게 남는다)
    general_grounded = OTHER_REPLY
    unrelated_grounded = OTHER_REPLY + " " + today
    skills_only = llm.skills_reference(llm.CHAT_AGENT_SKILLS)

    def clarify_out() -> ChatResult:
        """식별자를 모르겠을 때의 답. 먼저 한글·영문 배 이름이 말에 있는지 보고 입항 예정 목록에서 이름으로 찾는다.
        이름이 없거나 목록을 못 받으면 코드 문장으로 되묻되, 바로 앞 답과 같은 문장은 내지 않는다."""
        last = earlier[-1] if turns and turns[-1]["role"] == "assistant" and earlier else None
        name = ship_name_guess(masked, [t["text"] for t in turns if t["role"] == "user"])
        found = search_ship_name(name, last) if name else None
        return found or ChatResult(kind="message", reply=clarify_reply(masked, last))

    def fixed(reply: str) -> str:
        """고정 안내를 내보내기 직전의 마지막 손질. 바로 앞 답이 같은 계열의 고정 안내면 더 짧은 말로 바꾼다 (같은 안내 연속 금지)."""
        last = re.sub(r"\s+", "", earlier[-1]) if turns and turns[-1]["role"] == "assistant" and earlier else ""
        if not last:
            return reply
        flat = lambda t: re.sub(r"\s+", "", t)  # noqa: E731
        if reply == BROKER_ONLY:
            return BROKER_SHORT if last == flat(BROKER_ONLY) else reply
        if reply in (NOT_IN_SKILLS, OTHER_REPLY, INJECTION_REPLY):
            if last in (flat(NOT_IN_SKILLS), flat(OTHER_REPLY), flat(INJECTION_REPLY), flat(SHORT_NOTICE_2)):
                return SHORT_NOTICE
            if last == flat(SHORT_NOTICE):
                return SHORT_NOTICE_2
        return reply

    def general_violations(text: str) -> list[validate.Violation]:
        """2층 답(answer_kind=general)을 내보내도 되는지. 빈 목록이면 통과. 근거 조각이 없는 답이라 다음을 모두 건다:
        특정 화물·배 질문이나 B/L 토큰이 아님, 세액·통관 가능 여부 낱말 없음, 주입 모양 아님,
        V7(숫자는 사용자가 쓴 것만), V9(영문은 고정 문구·일반 해운 약어만), V10(사용자 글에만 있는 낱말 옮기기 금지), V13(앞 답 베끼기)."""
        if CARGO_TALK.search(masked) or re.search(r"\[(?:BL|MRN)", text):
            return [validate.Violation("GENERAL", "This is about a specific cargo or ship. Do not answer it from general knowledge: "
                                                  "call the tool it needs, or set answer_kind to not_in_skills.")]
        if BROKER_TOPIC.search(text):
            return [validate.Violation("GENERAL", "Do not state duty, tariff, tax, or clearance matters. Tell the user to ask a customs broker.")]
        if guard.looks_like_injection(text):
            return [validate.Violation("V9", "The reply repeats instructions from the input. Answer only the user's question.")]
        return validate.check_chat_reply(text, general_grounded, user_text, earlier, None, None,
                                         extra_words=validate.GENERAL_WORDS, copy_allowed=skills_only + " " + validate.GENERAL_TERMS)

    def general_reply(out: llm.ChatAgentOutput | None, text: str) -> str | None:
        """2층 답이 검사를 통과하면 최종 문장. 아니면 None (고정 안내로 간다). 꼬리표는 붙이지 않는다 (이용약관으로 이동)."""
        if out is None or out.answer_kind != "general" or not text or BROKER_TOPIC.search(masked) or general_violations(text):
            return None
        return _strip_notice(text)

    def skill_or_general(text: str) -> str | None:
        """Skill 근거라고 낸 답을 내보내기 직전 한 번 더 본다. 근거 조각은 맞았는데 답의 핵심 낱말이
        Skill 문서에 2개 이상 없으면(validate.skill_unsupported) 모델 지식이 섞인 것이다. 버리지 않고 2층(일반 설명)으로 낮춰
        내보낸다 (꼬리표는 없앴다). 재현: "B/L도 없고 포워더 연락 안 돼"에 Skill에 없는 "화물 인도증"이 Skill 답으로 나갔다.
        2층 검사(general_violations, 세액 주제)에 걸리면 None (고정 안내로 간다)"""
        if not validate.skill_unsupported(text, skills_only, user_text):
            return text
        if BROKER_TOPIC.search(text) or general_violations(text):
            return None
        return _strip_notice(text)

    def unrelated_violations(text: str) -> list[validate.Violation]:
        """잡담 한 문장 답(answer_kind=unrelated)을 내보내도 되는지. 빈 목록이면 통과. 한 문장(UNRELATED_MAX_CHARS 이하, 한 줄)이고,
        주입 모양이 아니고, 숫자는 사용자가 쓴 것과 오늘 날짜뿐(V7)이고, 영문(V9)·옮긴 낱말(V10)·앞 답 베끼기(V13)에 안 걸려야 한다."""
        if len(text) > UNRELATED_MAX_CHARS or "\n" in text:
            return [validate.Violation("LEN", "Answer a chit-chat message in one short Korean sentence.")]
        return _reply_violations(text, unrelated_grounded, user_text, earlier)

    def no_tool_violations(out: llm.ChatAgentOutput, text: str, first: bool) -> list[validate.Violation]:
        """도구 없이 낸 답을 다시 물어야 하는 이유. 빈 목록이면 그대로 결론을 낸다 (아래 no_tool_reply)."""
        if out.answer_kind in ("help", "greeting"):  # 문장은 코드가 쓴다. 화면에 화물이 있어도 도구를 부를 일이 아니다
            return []
        if first and context is not None and CLEARANCE_TIMING.search(masked):
            # 통관 시기 질문: 화물이 화면에 있으면 그 화물의 실제 통관 단계로 답한다. 일반 설명으로 끝내지 않는다
            return [validate.Violation("TOOL", CLEARANCE_HINT)]
        if out.answer_kind == "skill":
            return _reply_violations(text, grounded, user_text, earlier, out.skill_quote, skills) if text else []
        if out.answer_kind == "general" and text:
            # 세액 주제는 다시 묻지 않는다 (마지막에 BROKER_ONLY). 그 밖의 위반은 한 번 고쳐 쓰게 한다
            return [] if BROKER_TOPIC.search(masked) else general_violations(text)
        if out.answer_kind == "clarify":  # 되묻기 문장은 코드가 쓴다. LLM 문장은 보지 않으므로 검사할 것이 없다
            return []
        if out.answer_kind == "tool" and first:  # 도구 없이 "도구를 썼다"고 냈다. 도구를 부르라고 한 번 다시 묻는다
            return [validate.Violation("TOOL", "You set answer_kind to tool but called no tool. Call the tool this message "
                                               "needs now, then answer. If no tool fits, use another answer_kind.")]
        # 안내(not_in_skills·unrelated)는 앞 답을 베꼈거나(V13, "중국에서 오는 배"에 포워더 설명을 되풀이), 화면에 화물이 있는데
        # 도구를 안 불렀을 때 다시 묻는다. 잡담 답(unrelated)이 검사를 통과했고 화물·배 이야기가 아니면 그대로 쓴다
        found = [v for v in _reply_violations(text, grounded, user_text, earlier) if v.rule == "V13"] if text else []
        chat_ok = out.answer_kind == "unrelated" and bool(text) and not unrelated_violations(text) and not CARGO_TALK.search(masked)
        if first and context is not None and not found and not chat_ok:
            found.append(validate.Violation("TOOL", CARGO_ON_SCREEN_HINT))
        return found

    def ok_lookups() -> list[dict]:
        """성공한 읽기 전용 MCP 도구 호출 (위치·후보·일정·거리). 화물·검색·지켜보기 도구는 아니다."""
        return [c for c in ran if c["name"] in mcp_names and "error" not in (c["result"] or {})]

    def lookup_violations(text: str) -> list[validate.Violation]:
        """읽기 전용 도구 결과를 요약한 문장을 다시 물어야 하는 이유. 빈 목록이면 그대로 쓰거나 다시 물을 이유가 없다.
        비어 있으면 빈 답이라 위반 하나로 센다. 결과가 하나도 성공하지 않았으면 보지 않는다."""
        if not ok_lookups():
            return []
        if not text:
            return [validate.Violation("EMPTY", "The reply is empty. Write two or three Korean sentences that answer the question "
                                                "from the tool results you already have. Do not call the same tool again.")]
        return _reply_violations(text, reference + " ".join(str(c["result"]) for c in ok_lookups()), user_text, earlier)

    # 첫 답 + 다시 묻기. 다시 물을 때도 도구를 준다: 도구가 아직 하나도 안 돌았으므로 같은 조회를 두 번 하지 않는다.
    # 베낀 답·화물 질문은 다시 물어 도구를 부르게 하는 것이 고치는 길이다
    # 다시 묻는 길은 둘이고 각각 한 번이다 (프롬프트·검사 비용 상한: 한 문장에 LLM 호출 최대 3번):
    #   fix: 검사에 걸린 답을 고쳐 쓰게 한다 (V7·V9·V10·V13·V14, 도구를 안 불렀다는 TOOL)
    #   nudge: 사용자가 전에 저장한 것을 묻는데 "자료에 없다"로 답했으면(not_in_skills, 또는 Skill 답이 검사에 끝내 걸림)
    #     recall_memo를 부르라고 한 번 다시 묻는다. 웹 검색 도구는 없앴다 (docs/adr/0020)
    fix_left = 1
    memo_ask = is_memo_question(masked) and not is_action_request(masked)  # 저장한 것을 묻는다: recall_memo를 부르게 한 번 다시 묻는다
    nudge_left = 1 if memo_ask and not BROKER_TOPIC.search(masked) and not is_action_request(masked) else 0
    lookup_fix_left = 1  # 읽기 전용 도구 결과 요약을 고쳐 쓰게 하는 기회 (한 문장에 LLM 호출 최대 3번 상한 안에서 fix·nudge와 겹치지 않는다: 도구가 돈 문장은 그 둘을 안 탄다)
    first = True
    out, text, violations, feedback = None, "", [], None
    while True:
        try:
            # 화면 자료가 있을 때만 인자를 더한다: 없는 요청은 호출이 예전과 똑같다 (옛 화면·평가 스크립트)
            extra = {"on_screen": screen} if screen else {}
            if exposed_ids:  # 다시 묻는 호출은 앞 도구 결과가 대화에 없다. 보여 준 근거를 입력 자료로 다시 준다 (자료일 뿐, 지시가 아니다)
                extra["evidence"] = cite.evidence_prompt_block([i for i in turn_items if i["id"] in exposed_ids])
            answer = llm.chat_agent(masked, list(refs), context is not None, today, turns, tools, run, feedback=feedback, **extra)
            out, raw_text = answer.output, (answer.output.reply or "").strip()
            # 아래의 모든 답 검사(V7 숫자 등)는 [E1] 표시를 걷어 낸 글로 돈다. 표시는 맨 끝 _with_citations가 따로 검사한다
            text = cite.strip_marks(raw_text)
            signals["marked"] = (text, raw_text)
        except llm.LLMError as e:
            if first and not ran:  # 아무 도구도 안 돌았다: 전 방식이 같은 일을 처음부터 한다
                raise
            # 도구가 돌았으면 그 결과로 끝낸다. 전 방식으로 넘기면 같은 조회를 한 번 더 한다
            log_failure("chat_agent", f"{e.kind} after tools" if ran else f"{e.kind} on retry")
            if ran:
                text = ""  # 도구 결과만으로 답한다
            break  # 다시 묻기가 실패했으면 앞 답과 그 위반으로 아래에서 고정 문구를 고른다
        if ran:
            if lookup_fix_left and not done and (violations := lookup_violations(text)):
                # 읽기 전용 도구만 돌았는데 문장이 비었거나 검사에 걸렸다. 전에는 여기서 바로 막다른 문구가 나갔다.
                # 고쳐 쓰게 한 번 다시 묻는다. 도구를 또 불러도 같은 인자는 앞 결과가 돌아온다 (run의 seen)
                lookup_fix_left -= 1
                log_failure("chat_agent_reply", ",".join(v.rule for v in violations) or "empty")
                feedback = "\n".join(f"{v.rule}: {v.detail}" for v in violations)
                first = False
                continue
            break  # 도구가 돌았다: 아래에서 도구 결과로 답을 조립한다
        violations = no_tool_violations(out, text, first)
        skill_failed = out.answer_kind == "skill" and bool(violations) and not fix_left
        if nudge_left and (out.answer_kind == "not_in_skills" or skill_failed):
            nudge_left -= 1
            log_failure("chat_agent_reply", "memo_nudge")
            feedback = MEMO_HINT
            first = False
            continue
        first = False
        if not violations or not fix_left:
            break
        fix_left -= 1
        log_failure("chat_agent_reply", ",".join(v.rule for v in violations))
        feedback = "\n".join(f"{v.rule}: {v.detail}" for v in violations)
    calls = [c for c in ran if c["name"] not in ("set_watch", "watch_vessel", "send_kakao")]  # 지켜보기·카카오 보내기 도구는 조회 도구가 아니다. 결과 문장은 watch_out에 있다
    signals["watch_cue"] = bool(out is not None and out.watch_cue)

    # 문장에 지금 화물과 다른 B/L이 있는데 에이전트가 조회하지 않았으면 코드가 조회한다 (전 방식의 규칙과 같다:
    # B/L을 넣었는데 다른 화물 답이 나오면 안 된다)
    new_bls = [bl for bl in message_bls if context is None or bl != context.bl_no]
    checked = {r.request.bl_no for r in done if r.kind == "cargo" and r.request}
    if new_bls and not checked.intersection(new_bls):
        if len(set(message_bls)) >= 2:
            look_up_many(list(dict.fromkeys(message_bls)), None, None)  # 여러 B/L도 하나만 보지 않는다
        else:
            one = _cargo(new_bls[0], None, None, session_id, context, run_agent, note=None, mrn=mrn, user_id=user_id)
            parts = glued_parts(one, new_bls[0])
            if parts:
                look_up_many(parts, None, None)
            else:
                done.append(one)

    if out is not None and out.answer_kind == "clarify" and not done:
        # 식별자가 B/L인지 배 이름인지 모른다 (배 이름 조회도 후보가 없었거나 부르지 않았다). LLM 문장 대신 코드가 되묻는다
        return clarify_out()

    if not done and not calls and (kakao_out.get("msg") or kakao_out.get("refused")) and not watch_out:
        # 카카오톡 보내기만 한 문장이다. 결과나 못 보낸 이유를 코드 문장으로 낸다 (거절됐으면 안내)
        return ChatResult(kind="message", reply=kakao_out.get("msg") or KAKAO_HOW)
    if not done and not calls and (watch_out.get("msg") or watch_out.get("refused")):
        # 지켜보기만 한 문장이다. 켠 결과, 못 켠 이유, 또는 낱말이 없어 거절한 안내를 코드 문장으로 낸다
        return ChatResult(kind="message", reply=watch_out.get("msg") or WATCH_HOW, watch_set=watch_out.get("set"),
                          watch_vessel_set=watch_out.get("vessel_set"))

    looked_up = [c for c in calls if c["name"] in mcp_names and "error" not in (c["result"] or {})]
    lookups = " ".join(str(c["result"]) for c in looked_up)
    if recall_state and not done and not looked_up and user_id and is_save_request(masked):
        # 저장 부탁인데 에이전트가 recall_memo도 불렀다 ("포워더는 X야. 기억해 줘"). 꺼내 보기 답("저장된 메모에서 찾지 못했어요")을 내면
        # 저장 결과 앞에 엉뚱한 말이 붙는다. 꺼내 보기 결과는 버리고 짧은 안내만 낸다. 저장 결과 문장은 기억 뽑기가 뒤에 붙인다 (handle).
        # 로그인 안 한 사용자는 저장이 안 되므로 이 길을 타지 않고 로그인 안내(memo_reply_text)가 나간다
        return ChatResult(kind="message", reply=MEMO_SAVE_LEAD)
    if recall_state and not done and not looked_up:
        # 메모 꺼내 보기를 한 문장이다. 답은 메모 항목에서만 나온다
        found_text = recall_reply(text)
        if found_text:
            return ChatResult(kind="message", reply=found_text)
    if done:
        found = multi_state.get("results", [])
        notices = ([MULTI_BL_NOTICE] if multi_state.get("over") else []) + ([MULTI_FAILED_NOTICE] if multi_state.get("failed") else []) \
            + ([bl_parse.NOTE_GLUED] if multi_state.get("glued") else [])
        if len(found) >= 2:
            # 한 문장에 B/L 2~3개. 답은 표(cargos)와 짧은 문장 하나다. 문장은 LLM이 비교 질문에 답한 것이고,
            # 단일 조회와 같은 검사(숫자·날짜는 조회 결과에 있는 것만 등)를 통과해야 한다. 안 되면 코드 문장만 쓰고 표가 답이다.
            # 원문 B/L은 문장·표 어디에도 새로 쓰지 않는다 (표의 bl_no는 사용자가 입력한 값 그대로, 별도 칸)
            grounded_multi = reference + " ".join(str(c["result"]) for c in calls if c["name"] == "check_cargo") + lookups \
                + " ".join(r.reply for r in found)
            said = text if (text and any(c["name"] == "check_cargo" for c in calls)
                            and not _reply_violations(text, grounded_multi, user_text, earlier)) else ""
            # LLM에는 [BL1] 같은 번호표만 갔다. 화면에 나가는 문장에선 번호표를 사용자가 쓴 B/L로 되돌린다.
            # 그대로 두면 "[BL1] 화물은…"이 화면에 보이고, 표 순서("첫 번째")로 바꾸면 어느 화물인지 헷갈린다. 화면에만 가는 문장이라 LLM에는 새지 않는다
            for token, bl in refs.items():
                said = said.replace(token, bl)
            need_lines, rows, chosen = _multi_table(found)  # 표 줄과 판정 못 낸 줄 안내 (전 방식과 같이 쓴다)
            # 조회 결과가 없는 줄은 코드가 "~는 조회 결과가 없어요" 줄을 따로 쓴다. LLM 문장도 같은 말("통관 시스템에서 찾지 못했어요")을
            # 하면 한 답에 두 번 나온다. 그 경우 LLM 문장은 버리고 코드 줄과 표가 답한다
            if said and any(ROW_SAY_NOT_FOUND.format(bl=r.request.bl_no) in need_lines for r in found) and _SAYS_NOT_FOUND.search(said):
                said = ""
            lines = [said or MULTI_TABLE_LEAD.format(n=len(found))]
            lines.extend(need_lines)
            lines.extend(notices)
            lines.extend(date_notes)
            unread = unread_ids(masked, message_bls)
            if unread:
                lines.append(UNREAD_NOTICE.format(names=", ".join(f"'{u}'" for u in unread)))
            return replace(chosen, reply="\n".join(lines), map=None, cargos=rows)
        replies = list(dict.fromkeys(_no_result_text(r, earlier[-1] if earlier else None) for r in done))  # 같은 답이 두 번 붙지 않게
        if looked_up and text and not _reply_violations(text, reference + lookups + " ".join(replies), user_text, earlier) \
                and not _repeats_reply(text, replies):
            replies.append(text)
        replies.extend(notices)  # B/L이 상한을 넘었거나 일부만 조회됐을 때 코드가 쓴 안내
        replies.extend(date_notes)
        # B/L과 함께 온 질문 중 코드가 못 답하는 것은 조회 답 뒤에 고정 문장으로 막는다. 조회는 그대로 돈다:
        # 앞에서 가로채면 B/L을 넣은 문장이 조회되지 않는다 (test_chat_guard_a3 test_message_with_bl_is_not_intercepted)
        if BROKER_TOPIC.search(masked):
            replies.append(fixed(BROKER_ONLY))
        if DATE_PROMISE_ASK.search(masked):
            replies.append(DATE_PROMISE_NOTE)
        return replace(done[-1], reply="\n\n".join(replies), map=_map_payload(calls, done, started))
    if looked_up and all(c["name"] == "get_vessel_candidates" and isinstance(c["result"], dict) and c["result"].get("candidates") == []
                         for c in looked_up):
        # 사용자가 쓴 이름으로 후보를 찾았지만 한 척도 없다. "찾지 못했다"만 말하지 않고 B/L 번호인지 배 이름인지 되묻는다
        return clarify_out()
    if looked_up:
        ok = bool(text) and not _reply_violations(text, reference + lookups, user_text, earlier)
        if ok:
            return ChatResult(kind="message", reply=text, map=_map_payload(calls, done, started))
        # 다시 물어도 문장을 못 썼다 (LLM 실패·빈 답·검사 걸림·앞 답 베끼기). 막다른 문구 대신 이미 받은 결과를 코드가 그대로 전한다
        log_failure("chat_agent_reply", "lookup_fallback")
        fallback = lookup_fallback(looked_up)
        if fallback is None:
            return ChatResult(kind="message", reply=LOOKUP_NOT_SUMMARIZED, map=_map_payload(calls, done, started))
        reply = f"{LOOKUP_FALLBACK_LEAD} {fallback}"
        if earlier and _flat_text(reply) == _flat_text(earlier[-1]):
            reply = f"{LOOKUP_FALLBACK_SAME} {fallback}"
        return ChatResult(kind="message", reply=reply, map=_map_payload(calls, done, started))
    # 메모 꺼내 보기·입항 목록을 잘못 골라 돌려보낸 호출(not_a_memo_question·not_a_list_question)만 있으면 도구를 안 쓴 것과 같다. 모델의 다음 답을 Skill 답 검사로 본다
    memo_misfire = bool(calls) and all(isinstance(c["result"], dict)
                                       and (c["result"].get("error") or {}).get("code") in ("not_a_memo_question", "not_a_list_question")
                                       for c in calls)
    if calls and not memo_misfire:
        # 도구를 골랐는데 모두 실패했다. LLM 문장 대신 코드가 무엇이 안 됐는지 말한다 (EC-02·EC-03 고정 안내 유지)
        codes = [c["result"]["error"]["code"] for c in calls if isinstance(c["result"], dict) and "error" in c["result"]]
        if "need_bl" in codes and _ID_LIKE.search(masked):
            # B/L 모양은 아닌데 식별자 같은 글자가 있다(TESTBL4 같은 오타). 조회할 번호를 달라고만 하지 않고 그 글자를 되묻는다
            return clarify_out()
        fixed_msgs = {"need_bl": NEED_BL, "no_cargo": NO_CARGO, "broker_topic": BROKER_ONLY}
        return ChatResult(kind="message", reply=fixed(next((fixed_msgs[c] for c in codes if c in fixed_msgs), FAILED_LOOKUP)))

    # 도구를 하나도 쓰지 않았다. LLM 문장을 내보내는 것은 검사를 통과한 답뿐이다: Skill 근거 조각까지 통과한 실무 답(skill),
    # 2층 일반 설명(general), 한 문장 잡담 답(unrelated). 나머지는 코드의 고정 문구다:
    # 문서에 없는 질문은 없다고(NOT_IN_SKILLS), 상관없는 말은 할 수 있는 일(OTHER_REPLY). 같은 안내가 연달아 나가지 않게 fixed()를 거친다
    if out is not None and out.answer_kind == "help":
        return ChatResult(kind="message", reply=USAGE_GUIDE)  # 사용법은 LLM이 쓰지 않는다 (없는 기능 방지)
    if out is not None and out.answer_kind == "greeting":
        return ChatResult(kind="message", reply=GREETING_REPLY)
    if out is None or not text:
        log_failure("chat_agent_reply", f"kind={out.answer_kind if out is not None else 'none'} empty")  # 고정 안내로 가는 길의 기록 (사용자 글 없음)
        # 빈 답. 세액 주제와 "자료에 없다"는 종류가 말해 주는 고정 안내를 쓰고, 그 밖의 빈 답은 할 수 있는 일 안내다
        if BROKER_TOPIC.search(masked):
            return ChatResult(kind="message", reply=fixed(BROKER_ONLY))
        return ChatResult(kind="message", reply=fixed(NOT_IN_SKILLS if out is not None and out.answer_kind == "not_in_skills" else OTHER_REPLY))
    if out.answer_kind == "skill":
        if violations:  # 근거 조각이 끝내 안 맞았다. 세액 주제였다면 "자료에 없다"보다 관세사 안내가 맞다 (재생 시험에서 발견)
            return ChatResult(kind="message", reply=fixed(BROKER_ONLY if BROKER_TOPIC.search(masked) else NOT_IN_SKILLS))
        checked = skill_or_general(text)
        return ChatResult(kind="message", reply=checked or fixed(NOT_IN_SKILLS))
    if BROKER_TOPIC.search(masked):  # 세액·관세율·통관 가능 여부: 마르비아는 답하지 않고 관세사에게 묻게 한다 (PRD 4절)
        return ChatResult(kind="message", reply=fixed(BROKER_ONLY))
    if out.answer_kind in ("unrelated", "clarify") and not is_memo_question(masked) \
            and echoes_person_name(masked, text, skills_only + OTHER_REPLY + validate.GENERAL_TERMS):
        # 실험 A1: 사람 이름을 답에 따라 썼다. 모델 문장을 버리고 고정 문장으로 누구를 말하는지 되묻는다.
        # 저장한 메모를 묻는 문장(거래처 이름 등)은 사람 이름이 아니라서 건드리지 않는다 (recall_memo 답 보호)
        log_failure("chat_agent_reply", "person_name_echo")
        return ChatResult(kind="message", reply=PERSON_ASK)
    general = general_reply(out, text)
    if general:
        return ChatResult(kind="message", reply=general)
    if out.answer_kind == "unrelated" and not unrelated_violations(text) and not CARGO_TALK.search(masked):
        return ChatResult(kind="message", reply=text)  # 한 문장 잡담 답. 검사를 통과한 것만 (날짜, "마르비아가 뭐야?")
    log_failure("chat_agent_reply", f"kind={out.answer_kind}")  # 고정 안내로 가는 길. 다음 실패를 가려내려는 기록 (종류만)
    return ChatResult(kind="message", reply=fixed(NOT_IN_SKILLS if out.answer_kind in ("not_in_skills", "general") else OTHER_REPLY))


def _cargo(bl: str, bl_type: str | None, sale_due_date: str | None, session_id: str, context: AgentRequest | None,
           run_agent, note: str | None, mrn: str | None = None, user_id: str | None = None,
           voyage_no: str | None = None, forwarder_eta: str | None = None) -> ChatResult:
    """B/L 조회. 같은 화물을 다시 물으면 지금 화물의 구분·판매일·MRN을 이어 쓴다.
    MRN이 있으면 세관에 아직 없는 화물도 배 상태까지 볼 수 있다 (docs/specs/mrn-fallback.md).
    로그인 사용자가 이미 조회한 화물이면 답 끝에 "지난 조회(10.01)에서는 ○○였어요." 한 줄을 붙인다.
    그 줄은 조회 전에 읽은 화물 표 값으로 코드가 쓴다. 응답 칸(C1)은 늘리지 않는다.
    voyage_no·forwarder_eta: 되묻기에 사용자가 문장으로 답한 값 (에이전트만 넘긴다). 전에는 화면의 칸으로만 받았다."""
    # 답에 붙일 수 있는 것은 코드가 쓴 "지난 조회" 한 줄뿐이다 (D1). lookup_notes가 다른 줄(메모장 가득 참 알림 등)을
    # 돌려줘도 사용자에게 보이지 않게 여기서 한 번 더 거른다. 가득 참은 설정 "내 기억" 화면만 보여 준다
    notes = [n for n in memory.lookup_notes(user_id, bl) if n.startswith(PREVIOUS_LINE_PREFIX)]
    same = context is not None and context.bl_no == bl
    # 사용자가 말한 구분 > 컨테이너 번호로 찾은 화물의 저장된 구분 > 지금 화물의 구분. 저장된 구분이 없으면 아래에서 HOUSE로 조회하고 알린다
    kind = bl_type or _stored_type(bl) or (context.bl_type if same else None)
    def request_as(bl_kind: str) -> AgentRequest:
        return AgentRequest(bl_no=bl, bl_type=bl_kind, session_id=session_id,
                            sale_due_date=sale_due_date or (context.sale_due_date if same else None),
                            mrn=mrn or (context.mrn if same else None),
                            voyage_no=voyage_no, forwarder_eta=forwarder_eta)

    req = request_as(kind or DEFAULT_BL_TYPE)
    resp = run_agent(req)
    reply = resp.answer
    if _is_no_result(ChatResult(kind="cargo", reply=reply, agent=resp, request=req)):
        reply = NO_RESULT_REPLY  # 판정 흐름(routers/agent.py)의 문구는 "~습니다"라 화면 말투(~요)로 맞춘다. 뜻은 같다
        if not kind:
            # 구분을 말하지 않았으면 하우스로 먼저 보고, 세관에 없다고 하면(오류·시간 초과가 아니라 "없음"일 때만)
            # 곧바로 마스터로 한 번 더 본다. 되묻지 않는다. 찾은 쪽 구분이 req에 실려 저장·후속 질문·지켜보기가 그대로 쓴다.
            # 둘 다 없으면 "구분을 말하지 않아…마스터로 다시" 안내 없이 없다고만 하고, 화면의 구분 다시 고르기(CandidatePicker)도 끄도록
            # missing_inputs를 bl_not_found로 바꾼다 (bl_type이 아니므로 화물 표에도 저장하지 않는다, cargo.found_cargo)
            master_req = request_as("MASTER")
            master_resp = run_agent(master_req)
            if not _is_no_result(ChatResult(kind="cargo", reply=master_resp.answer, agent=master_resp, request=master_req)):
                req, resp, reply = master_req, master_resp, master_resp.answer
            else:
                resp = resp.model_copy(update={"missing_inputs": [NOT_FOUND_BOTH]})
                reply = NO_RESULT_BOTH
    if notes:
        reply = "\n".join([reply, *notes])
    return ChatResult(kind="cargo", reply=reply, agent=resp, request=req)
