"""POST /api/agent (작업 A6, SDD 4.1).

요청을 받아 서비스 계층을 순서대로 부르고 AgentResponse를 돌려준다.
여기서 판정하지 않고, 외부 API를 직접 부르지도 않고, LLM SDK를 import하지도 않는다 (CLAUDE.md).

처리 순서는 SDD 4.1을 따른다.
  1. 입력 검증 (스키마 AgentRequest가 B/L 형식까지 본다, A7)
  2. UNI-PASS 조회 (코드가 직접 부른다. B/L을 LLM에 넘기지 않는다)
  2-1. 지원 범위 확인 (양륙항이 부산이 아니면 unsupported로 끝낸다)
  2-2. 반출 확인 (이미 창고에서 나간 화물이면 배를 찾지 않고 규칙으로 fine, 09-28 결정)
  3. 선박 식별 (MRN 호출부호로 먼저, 안 되면 선명으로. 후보 1척이면 확정, 여럿이면 되묻기, 0척이면 여기서 멈추고 되묻기)
  4. 도구 호출 (위치·입항 일정·남은 거리)
  5. 1층 신호 판정 (코드)
  6. 2층 판정 (LLM, services/llm.judge)
  7. 출력 검증 V1~V8 (services/validate.py, V8은 여기). 위반이면 최대 3번까지 다시 묻고, 그래도 위반이면 판정 표 등급 + 고정 문구로 partial
     다시 물으면 시간 예산(JUDGE_BUDGET_SEC)을 넘길 것 같을 때도 거기서 멈추고 같은 partial을 낸다 (10-05)

6단계는 services/llm.judge()가 한다 (C-6, 09-27 연결). 결과를 어떻게 응답에 담나:
  - LLM이 끝내 실패하면(호출 실패, 세 번 모두 위반) status=partial. 등급은 판정 표 것을 내고 문장은 고정 문구. 회색 지대면 등급 없이 (09-30 결정, _llm_gave_up)
  - 등급은 코드가 판정 표로 정한다(decided_by=rule). LLM은 그 등급에 맞춰 설명·할 일·상충·통관 해설을 쓴다 (09-30 D7, services/verdict.py)
  - 회색 지대(anchor_wait·customs_hold가 unknown)만 LLM이 표 등급 이상에서 고른다. 표보다 올리면 decided_by=llm
  - LLM이 표가 틀렸다고 보면 table_disagree에 적는다. 응답에 쓰지 않고 기록만 한다 (Langfuse generation output, 로그)
  - 쓸 위치가 없으면 LLM을 부르지 않는다. 데이터 없음은 insufficient, 도구 고장은 partial (09-29 결정, _no_position)
  - 위치가 캐시에서 왔으면(실시간 조회 실패) 판정은 하되 status=partial (09-29 결정, 평가셋 F02)
근거 카드는 services/evidence.build()가 만든다 (C-8).

화물 비서 기억 (docs/specs/memory.md, 10-02): 로그인 사용자면 판정 전에 화물 표·메모장을 읽어 판정·후속 LLM에
데이터 블록으로 넣고(services/memory.load_context), 응답을 돌려준 뒤 뒤에서 화물 표 쓰기와 기억 뽑기를 한다
(memory.remember_later). 등급은 지금처럼 판정 표가 정한다. 사용자가 없으면(채점 환경·평가 실행기·데모) 아무것도 안 한다.
10-02 검증 반영: 회색 지대(raise_only) 판정에는 기억 블록을 주지 않고(F7), 출력 검사에서 기억은 사용자가 준 날짜·숫자만 V7 근거로 친다.
지난 조회 값과 메모 낱말은 근거가 아니다(F8, validate.user_supplied_text). V12는 블록을 실제로 줬을 때만 건다.
"""
import json
import logging
from contextvars import ContextVar
import os
import time
from datetime import datetime, timezone
from typing import Annotated

import pycountry
from fastapi import APIRouter, Depends, HTTPException

from backend.app import crypto
from backend.app.auth import current_user_id
from backend.app.db import connect, log_query, recent_positions, recent_responses
from backend.app.observability.langfuse import session_scope
from backend.app.observability.logging import current_request_id, log_failure
from backend.app.schemas.agent import (
    AgentRequest, AgentResponse, BerthInfo, CustomsInfo, EtaInfo, Evidence, Position, Reason, VesselCandidate,
    VesselInfo,
)
from backend.app.schemas.customs import CustomsRecord, mask_bl
from backend.app.services import guard, identify, llm, progress, quota, referrals, validate
from backend.app.services import memory as memory_service
from backend.app.services import verdict as verdict_table
from backend.app.services import signals as signals_service
from backend.app.services.evidence import KST, build as build_evidence, days_margin
from backend.app.services.rules import is_listed_stage, rule
from backend.app.clients import shipfinder as shipfinder_client
from backend.app.services.customs import CustomsError, UnipassClient
# MCP 도구 4종은 /mcp를 거쳐 부른다 (10-02, services/mcp_client.py)
from backend.app.services.mcp_client import (
    call_tool, estimate_distance, get_live_position, get_port_schedule, get_vessel_candidates, read_only_tools,
)

router = APIRouter(prefix="/api", tags=["agent"])
logger = logging.getLogger(__name__)

NOT_JUDGED = "조회한 값을 정리했습니다. 판정은 아직 붙지 않았습니다."
# 화면에 그대로 나가는 문구라 약어(M/H, ETA)를 풀어 쓴다 (10-02 화면 용어 점검)
NO_CARGO = "조회 결과가 없습니다. B/L 번호와 마스터·하우스 구분을 다시 확인해 주세요."
ASK_BACK = "같은 이름의 배가 여러 척입니다. 항차 번호나 포워더가 알려 준 입항 예정일을 알려주시면 어느 배인지 가릅니다."
# 항차·입항 예정일을 이미 받았는데도 못 가른 경우 (10-05 버그 찾기). 같은 ASK_BACK을 되풀이하면 "항차를 알려 달라"는 말에
# 항차를 알려 줬는데 또 항차를 달라는 꼴이 된다. 화면 후보 고르기(web/components/CandidatePicker.tsx)가 있어 그것을 안내한다
ASK_BACK_AFTER_EVIDENCE = ("알려 주신 항차나 입항 예정일로도 어느 배인지 가르지 못했습니다. "
                           "화면의 후보 중에서 고르시거나, 포워더에게 받은 입항 예정일을 알려 주세요.")
NO_VESSEL = "선박 위치 서비스에서 이 배를 찾지 못했습니다. 포워더 도착 통지서(A/N)의 입항 예정일을 알려주세요."
# 사용자가 고른 배(resolved_mmsi)가 이 화물의 후보에 없을 때 (10-06 점검). 전에는 어떤 MMSI든 그대로 확정해서,
# 화면을 거치지 않고 아무 번호나 보내면 남의 배로 판정했고 "배는 확인했지만" 같은 앞뒤 안 맞는 답이 나왔다
RESOLVED_NOT_CANDIDATE = "고르신 배가 이 화물의 후보 목록에 없어 확정하지 않았습니다. 화면의 후보 중에서 다시 골라 주세요."
RESOLVED_NO_CANDIDATES = "고르신 배를 이 화물의 후보에서 확인하지 못했습니다."
NO_VESSEL_AFTER_ETA ="선박 위치 서비스에서 이 배를 찾지 못해 판정하지 못했습니다. 입항 일정은 포워더에게 직접 확인해 주세요."
VESSEL_TOOL_FAILED = "선박 위치 서비스에 연결하지 못해 판정하지 못했습니다. 잠시 뒤 다시 조회해 주세요."
# 위치 없음 (09-29 결정, 09-27 "위치 없음 → 판정 보류" 문구: 조회되지 않는다고 그대로 말하고 포워더 입항 예정일을 묻는다)
POSITION_MISSING = "배는 확인했지만 지금 배 위치가 조회되지 않아 판정하지 않았습니다. 포워더 도착 통지서(A/N)의 입항 예정일을 알려주세요."
POSITION_MISSING_AFTER_ETA = "배는 확인했지만 지금 배 위치가 조회되지 않아 판정하지 않았습니다. 입항 일정은 포워더에게 직접 확인해 주세요."
# 도착일 모름 (09-29 결정 D6). 대략값은 코드 계산이라 "참고용"을 반드시 붙인다 (정운: "신뢰하지 마세요")
NO_ETA = ("판매 예정일은 받았지만 도착 예정일을 확인할 근거(해수부 입항 신고, AIS 도착 예정)가 아직 없어 판정하지 않았습니다. "
          "포워더 도착 통지서(A/N)의 입항 예정일을 알려주시면 판매 예정일까지 여유를 봐 드립니다.")
NO_ETA_WITH_ESTIMATE = ("판매 예정일은 받았지만 도착 예정일을 확인할 근거(해수부 입항 신고, AIS 도착 예정)가 아직 없어 판정하지 않았습니다. "
                        "현재 위치와 속도로 계산한 대략적인 부산 도착은 {month}월 {day}일쯤입니다. 참고용이며 속도나 기항지에 따라 달라질 수 있습니다. "
                        "포워더 도착 통지서(A/N)의 입항 예정일을 알려주시면 판매 예정일까지 여유를 봐 드립니다.")
POSITION_TOOL_FAILED = "선박 위치 조회에 실패해 판정하지 않았습니다. 해수부 입항 예정은 참고로만 보여 드립니다. 잠시 뒤 다시 조회해 주세요."
# ShipFinder 하루 호출 한도를 다 썼을 때 (status 38, clients/shipfinder.py quota_exhausted). 오늘은 다시 조회해도 안 되므로
# "잠시 뒤"가 아니라 내일이라고 알린다 (10-06 점검)
QUOTA_EXHAUSTED_TAIL = " 오늘 선박 위치 조회 한도를 다 써서, 내일 다시 조회해 주세요."
NOT_BUSAN = "부산항에 내리는 화물만 확인할 수 있습니다. 이 화물은 다른 항만으로 들어옵니다."
LLM_FAILED = "판정을 만들지 못했습니다. 조회한 값과 신호만 보여 드립니다."
# 판정 LLM이 끝내 실패했을 때 표 등급으로 확정하며 쓰는 문구 (09-30 결정, _llm_gave_up). 숫자를 넣지 않는다 (V7)
TABLE_FALLBACK = "판정 표 기준으로 '{label}'입니다. 설명 문장은 만들지 못했습니다. 아래 근거를 확인해 주세요."
VERDICT_LABEL = verdict_table.VERDICT_LABEL  # 원본은 services/verdict.py (화물 비서 "지난 조회" 줄과 같이 쓴다)

# 반출된 화물 (09-28 결정). 반출신고는 통관의 마지막 단계다 (skills/customs-stages/rules.md customs_stages, next가 null)
RELEASED_STAGE = "반출신고"
RELEASED = "이 화물은 이미 보세창고에서 반출됐습니다. 통관이 끝나 배 위치는 확인하지 않았습니다. 배송 일정은 운송사에 확인해 주세요."
RELEASED_EXPLANATION = "화물이 보세창고에서 나갔고 세관 절차가 모두 끝났습니다."
# 할 일은 customs-stages/rules.md 반출신고 todo("입고를 확인한다")를 따르고, 범위 밖인 배송 일정은 운송사로 넘긴다 (PRD 4절 창고 수령일 예측)
RELEASED_ACTIONS = ["배송 일정은 운송사에 확인하세요.", "물건이 도착하면 입고를 확인하세요."]

# 목록에 없는 통관 단계의 설명 문장 (10-01). customs-stages/rules.md에 뜻이 없어 LLM이 설명할 근거가 없다.
# LLM에 맡기면 이름만 보고 뜻을 지어내거나 "지연될 수 있다" 같은 평가를 덧붙였다 (평가 B10 "검사지정", 09-30·10-01 매번)
UNLISTED_STAGE_EXPLANATION = "{stage} 단계입니다. 목록에 없는 단계라 뜻을 확인할 수 없어 관세사 확인이 필요합니다."

JUDGE_ATTEMPTS = 3  # 판정 LLM 호출 최대 횟수: 처음 + 위반 내용 첨부 + 강화 (SDD 5.7)
# 판정 재시도의 시간 예산(초). 판정 표 같은 도메인 임계값이 아니라 응답 대기 상한이라 코드에 둔다 (10-05).
# 다음 시도는 "지금까지 쓴 시간 + 방금 호출에 걸린 시간"이 이 값 안에 들어올 때만 시작한다. 안 들어오면 더 묻지 않고
# 판정 표 등급 + 고정 문구로 partial을 낸다(_llm_gave_up, 등급은 원래 코드가 정한다).
# 근거: 화면은 90초에 요청을 포기한다(web/lib/api.ts AGENT_TIMEOUT_MS). 10-05 실측에서 판정 호출 한 번이 7~40초였고,
# 세 번 다 돌면 121초·170초가 나와 화면이 먼저 끊겼다. 판정 앞 단계(채팅 이해, 통관·식별·위치 조회)에 쓸 몫을 남긴다.
# 한계: 호출 하나의 상한은 llm.TIMEOUT_SEC(60초)이라, 예상보다 느린 마지막 호출은 이 예산을 넘을 수 있다
JUDGE_BUDGET_SEC = 60.0

# _identify가 "선박 검색 도구가 실패했다"를 알릴 때 쓰는 라우터 안의 표시. 응답의 vessel_match로는 나가지 않는다
TOOL_FAILED = "tool_failed"
FOLLOW_UP_FAILED = "질문에 답하지 못했습니다. 잠시 뒤 다시 물어봐 주세요."
# 질문이 역할 재설정·지시 무시 모양이면 LLM을 부르지 않고 이 문구로 답한다 (services/guard.py, SDD 7절 10-01)
FOLLOW_UP_BLOCKED = "이 화물의 조회 결과에 대한 질문에만 답할 수 있습니다. 예: 여유가 며칠인가요? 지금 통관 단계는 무엇인가요?"
# 후속 답에 거는 검증 규칙. answer 문장을 보는 것은 V1(오래된 위치를 현재 위치라 하지 않기),
# V7(근거에 없는 숫자 금지), V11(통관 진행 평가 금지)이다. 나머지는 판정·근거 칸을 보는데, 후속 질문은 그 칸을 바꾸지 않는다 (services/validate.py)
# 여기에 후속 답 전용 V9(근거에 없는 영문 낱말 금지, validate.check_follow_up_words)와 V10(질문 낱말 옮기기 금지)을 더 건다 (10-01)
FOLLOW_UP_RULES = {"V1", "V7", "V11", "V15"}  # V11: 후속 답에도 통관 진행 평가를 쓰지 않는다 (10-01). V15: 판매 예정일이 지났다고 쓰지 않는다 (10-06 점검)
# 후속 질문에서 LLM이 부른 도구 결과를 근거 카드로 붙일 때의 출처 (10-02). Evidence.source 값 중에서 고른다 (계약 C1, 바꾸지 않음)
TOOL_SOURCE = {"get_vessel_candidates": "shipfinder", "get_live_position": "shipfinder",
               "get_port_schedule": "mof", "estimate_distance": "searoute"}


def _response(**over) -> AgentResponse:
    """AgentResponse는 빈 자리도 명시해야 한다. 기본값을 채우고 준 값만 덮는다."""
    base = dict(
        status="partial",
        verdict=None,
        vessel_match="none",
        days_margin=None,
        decided_by=None,
        vessel=None,
        position=None,
        eta=None,
        customs=None,
        berth=None,
        evidence=[],
        answer=NOT_JUDGED,
        trace_id=current_request_id(),
    )
    return AgentResponse(**{**base, **over})


# 하루 토큰 한도를 다 쓴 사람에게 주는 오류 (services/quota.py). 화면(web/lib/api.ts)이 이 값을 보고 입력을 막는다
QUOTA_DETAIL = "daily_token_limit"


def quota_guard(session_id: str | None, user_id: str | None) -> None:
    """요청 시작 때 오늘 토큰 한도를 확인한다. 다 썼으면 429 (docs/specs/token-quota.md, 10-02).

    처리 도중에 한도를 넘은 요청은 끝까지 답한다. 확인은 요청이 들어올 때 한 번뿐이다(quota.checked_var).
    /api/agent, /api/chat, /api/chat/stream, /api/document가 부른다.
    """
    try:
        quota.ensure_allowed(session_id, user_id)
    except quota.QuotaExceeded:
        log_failure("quota", "daily_token_limit")
        raise HTTPException(status_code=429, detail=QUOTA_DETAIL) from None


@router.post("/agent", response_model=AgentResponse)
def run_agent(request: AgentRequest,
              user_id: Annotated[str | None, Depends(current_user_id)] = None) -> AgentResponse:
    """B/L과 판매 예정일을 받아 화물 상태를 정리해 돌려준다. 후속 질문이 오면 지난 결과를 보고 답한다.
    어느 쪽이든 결과를 조회 이력(query_log)에 남긴다.
    이 요청에서 부르는 LLM 트레이스에는 session_id가 붙는다 (SDD 5.11). 키가 없으면 아무 일도 안 한다.

    user_id: 출입증에서 꺼낸 사용자 ID (G3, auth.py). 로그인은 필수라 로그인 기능이 꺼진 채점 환경에서만 None. 판정 자체는 똑같고
    이력을 누구 것으로 남기고 후속 질문이 누구 결과를 꺼내는지만 달라진다.
    평가 실행기·데모처럼 코드에서 직접 부르면 None이다.

    로그인 사용자면 기억(화물 표·메모장)을 읽어 LLM에 넣고, 응답 뒤 뒤에서 기억을 고친다 (docs/specs/memory.md).
    기억 쓰기는 응답을 늦추지 않고, 실패해도 응답에는 영향이 없다 (EC-07)."""
    quota_guard(request.session_id, user_id)
    with session_scope(request.session_id, user_id):
        context = memory_service.load_context(user_id, request.bl_no)
        blocks = context.blocks if context else None
        if request.follow_up_question:
            response = _logged(request, _follow_up(request, user_id, blocks), user_id)
        else:
            response = _logged(request, _assess(request, blocks), user_id)
        memory_service.remember_later(user_id, request, response, released=is_released(response))
        return response


def is_released(response: AgentResponse) -> bool:
    """반출이 끝난 화물의 응답인가. 화물 표에서 끝난 화물(done)로 옮기는 기준이다 (docs/specs/memory.md, RELEASED_STAGE)."""
    return bool(response.customs and response.customs.stage_name == RELEASED_STAGE)


def _assess(request: AgentRequest, memory: str | None = None) -> AgentResponse:
    """조회와 판정 (SDD 4.1 1~7단계). 이력은 run_agent가 남긴다.
    progress.step()은 실제로 그 단계에 들어갈 때 화면에 알리는 한 줄이다. 듣는 쪽이 없으면 아무 일도 안 한다 (docs/specs/chat-progress.md).
    memory: 로그인 사용자의 기억 블록 (docs/specs/memory.md 읽기 흐름). 판정 LLM에만 넣는다.
    검증에서 근거로 치는 것은 사용자가 준 날짜·숫자뿐이다 (validate.user_supplied_text, 10-02 검증 F8, 결정 5)."""
    progress.step("customs")
    customs, failure = _fetch_customs(request)
    if failure is not None:
        # 세관에 아직 없는 B/L이고 MRN이 있으면 해수부 입항 신고로 배 상태까지는 보여 준다 (docs/specs/mrn-fallback.md).
        # 세관 장애(failed)는 대체하지 않는다 (EC-04)
        if failure.status == "insufficient" and request.mrn:
            from backend.app.services import mrn_fallback  # 이 경우에만 불러온다
            alternative = mrn_fallback.assess(request)
            if alternative is not None:
                return alternative
        return failure

    response = _after_customs(request, customs, memory)
    # UNI-PASS 처리 이력 원문은 화면 전용이다 (docs/specs/customs-detail.md, 10-02). 판정이 끝난 뒤에 붙여서
    # 판정·검증 단계에는 아예 없다. 이력 저장(_logged)과 후속 질문 LLM 입력에서는 다시 뺀다
    return response.model_copy(update={"customs_detail": customs.display_rows})


def _after_customs(request: AgentRequest, customs: CustomsRecord, memory: str | None = None) -> AgentResponse:
    """통관 정보를 받은 뒤의 판정 흐름 (SDD 4.1 2~7단계). _assess가 화면 전용 이력을 붙이려고 나눴다."""
    # 지원 범위는 부산항이다 (PRD 4절). 양륙항이 부산이 아니면 배를 찾지 않고 끝낸다 (평가셋 F05).
    # 양륙항 칸이 비어 있으면 범위 밖으로 단정하지 않고 진행한다. 모르는 것을 거절하는 쪽이 더 나쁘다
    # 부산 항구 코드는 skills/port-busan/rules.md busan_port_code (10-01)
    if customs.discharge_port and customs.discharge_port != rule("busan_port_code"):
        return _response(status="unsupported", answer=NOT_BUSAN)

    # 이미 반출된 화물은 배를 찾지 않는다 (09-28 결정). 화물이 창고를 떠났는데 배를 찾으면 같은 배의
    # 다음 항차 위치로 여유 일수를 계산해 엉뚱한 act가 나온다 (09-28 실제 B/L: 9/17 반출인데 act, 여유 -1일)
    if customs.stage_name == RELEASED_STAGE:
        return _released(customs)

    progress.step("identify")
    candidates, vessel_match, mmsi, call_sign = _identify(customs, request)
    # 사용자가 고른 배를 후보에서 확인하지 못했다 (10-06 점검). 다른 근거로 1척이 확정됐어도 사용자가 고른 배와 다르니
    # 바꿔 끼우지 않고 되묻는다. 도구 실패는 아래에서 그대로 partial로 끝낸다
    rejected = bool(request.resolved_mmsi) and mmsi != request.resolved_mmsi and vessel_match != TOOL_FAILED
    if rejected and vessel_match == "confirmed":
        vessel_match, mmsi, call_sign = "uncertain", None, None
    # 배를 못 정하면 판정하지 않는다. 위치·입항 정보 없이 판정하면 근거 없이 "괜찮다"가 나온다 (09-28 실제 B/L)
    if vessel_match == TOOL_FAILED:
        # 검색 도구 실패는 우리 쪽 문제라 사용자에게 되묻지 않는다 (SDD 4.1 4단계·8절)
        return _response(status="partial", answer=_tool_failed_text(VESSEL_TOOL_FAILED))
    if vessel_match == "none":
        # 0척 → insufficient (SDD 4.1 3단계). 포워더 입항 예정일을 이미 받았으면 더 물을 게 없어 partial (V5)
        prefix = f"{RESOLVED_NO_CANDIDATES} " if rejected else ""
        if request.forwarder_eta:
            return _response(status="partial", answer=prefix + NO_VESSEL_AFTER_ETA)
        return _response(status="insufficient", missing_inputs=["forwarder_eta"], answer=prefix + NO_VESSEL)
    if vessel_match == "uncertain":
        if rejected:
            answer = RESOLVED_NOT_CANDIDATE
        else:
            answer = ASK_BACK_AFTER_EVIDENCE if (request.voyage_no or request.forwarder_eta) else ASK_BACK
        return _response(
            status="insufficient",
            vessel_match="uncertain",
            vessel_candidates=candidates,
            missing_inputs=[f for f in ("voyage_no", "forwarder_eta") if not getattr(request, f)],
            answer=answer,
        )

    progress.step("position")
    position = get_live_position(mmsi) if mmsi else None
    schedule = get_port_schedule(call_sign=call_sign, ship_name=customs.ship_name)
    distance = _distance(position)
    # 도구가 실패해도 신호는 unknown으로 두고 계속 간다. 어느 도구가 실패했는지는 로그에 남긴다
    _log_tool_error("live_position", position)
    _log_tool_error("port_schedule", schedule)
    _log_tool_error("distance", distance)

    # 5. 1층 신호와 여유 일수는 코드가 계산한다 (SDD 4.1 5·6단계). LLM은 이 값을 바꾸지 않는다
    signal_set = signals_service.compute(position, schedule, distance, customs, request.sale_due_date,
                                         history=_position_history(mmsi), forwarder_eta=request.forwarder_eta)
    # 사용자가 되묻기에 답한 포워더 A/N 입항 예정일도 마지막 근거로 쓴다 (09-29 D6, signals.trusted_eta)
    trusted = signals_service.trusted_eta(position, schedule, request.forwarder_eta)
    # 쓸 위치가 없으면 여유 일수도 내지 않는다. 해수부 예정만으로 센 값을 판정 근거처럼 보이지 않게 (평가셋 B13·F04 days_margin=null)
    has_position = bool(position) and "error" not in position
    margin = days_margin(trusted, request.sale_due_date) if has_position else None

    # 판정이 붙든 안 붙든 같이 나가는 값
    collected = dict(
        vessel_match=vessel_match,
        vessel_candidates=candidates,
        vessel=_vessel_info(candidates, mmsi, call_sign, customs, request),
        position=_position(position, signal_set.freshness),
        days_margin=margin,
        eta=_eta(position, schedule, signal_set, trusted),
        berth=BerthInfo(facility=(schedule or {}).get("facility") if "error" not in (schedule or {}) else None,
                        shed=customs.shed_name),
        # 근거 카드. LLM이 실패해 판정이 없어도 조회한 값은 보여준다 (C-8, SDD 5.8)
        evidence=build_evidence(customs, position, schedule, distance, trusted, margin, signals=signal_set,
                                sale_due_date=request.sale_due_date, forwarder_eta=request.forwarder_eta),
    )

    # 위치 없음: LLM을 부르지 않고 코드가 보류한다 (09-29 결정, 09-27 "위치 없음 → 판정 보류"를 코드로).
    # 전에는 위치 없이 LLM에 넘겨 해수부 예정만 보고 watch를 냈다 (평가 B13·F04)
    if not has_position:
        return _no_position(position, request, collected)
    # 실시간 조회는 실패하고 마지막으로 받은 위치(캐시)로 판정한다. 판정은 하되 partial로 알린다
    # (평가셋 F02 정답 partial·watch, SDD 8절 "ShipFinder 타임아웃 → partial")
    from_cache = bool(position.get("cached_at"))

    # 판매일은 받았는데 믿을 도착일이 없어 여유 일수를 못 셌다 (해수부 신고 전 + AIS ETA 없음 등).
    # 판매일 대비 판단이 핵심이라 LLM 없이 보류하고, 대략값만 참고로 보여 준다 (09-29 결정 D6)
    if request.sale_due_date and margin is None:
        return _no_eta(signal_set, collected)

    # 6·7. 2층 판정 (LLM)과 출력 검증 (C-7, SDD 5.7)
    # 위반이면 위반 내용을 붙여 다시 묻는다. 두 번째 재시도는 "JSON만, 규칙 준수"를 덧붙인다.
    # 형식이 깨진 답(JSON 아님·필수 칸 누락)도 위반과 같이 다시 묻는다 (09-28 결정). 전에는 바로 partial로 끝나
    # 두 번째 답이 깨지면 세 번째 기회가 없었다 (09-28 평가 B09).
    # LLM이 끝내 실패하면(세 번 모두 위반·형식 오류, 또는 호출 실패) 판정 표 등급과 고정 문구로 partial (09-30 결정).
    # 등급은 코드가 정하므로 LLM이 못 만든 것은 설명 문장뿐이다. 전에는 등급까지 버리고 failed였다 (_llm_gave_up)
    # 등급은 판정 표가 먼저 정한다 (09-30 D7). 회색 지대면 LLM이 표 이상에서 고를 수 있다
    table = verdict_table.table_verdict(signal_set, margin)
    gray = verdict_table.is_gray(signal_set)
    # 회색 지대(raise_only)는 LLM이 등급을 올릴 수 있는 유일한 자리라 기억 블록을 주지 않는다 (10-02 검증 F7, 결정 5:
    # B/L 조건·메모가 등급에 영향을 주면 안 된다). 고정 등급(fixed)은 LLM이 등급을 못 바꾸므로 기억을 넣어 설명에 쓴다
    judge_memory = None if gray else memory
    # V7 근거로 칠 글: 사용자가 준 값만. 지난 조회 값(last_eta 등)은 뺀다 (F8)
    memory_numbers = validate.user_supplied_text(judge_memory)
    progress.step("judge")
    feedback = None
    started = call_started = time.monotonic()
    for attempt in range(1, JUDGE_ATTEMPTS + 1):
        # 시간 예산 (JUDGE_BUDGET_SEC). 방금 호출만큼 한 번 더 걸린다고 보고, 예산을 넘길 것 같으면 다시 묻지 않는다
        now = time.monotonic()
        if attempt > 1 and (now - started) + (now - call_started) > JUDGE_BUDGET_SEC:
            log_failure("judge", f"time budget exceeded after {attempt - 1} attempts")
            return _llm_gave_up(signal_set, margin, table, gray, customs, collected)
        call_started = now
        try:
            judged = llm.judge(signal_set, customs, margin, feedback=feedback,
                               trusted_eta=trusted, sale_due_date=request.sale_due_date,
                               table_verdict=table, verdict_mode="raise_only" if gray else "fixed", memory=judge_memory)
        except llm.LLMFormatError as e:
            log_failure("judge", f"{e.kind} attempt {attempt}")
            feedback = e.detail
        except llm.LLMError as e:
            log_failure("judge", _llm_error(e))
            return _llm_gave_up(signal_set, margin, table, gray, customs, collected)
        else:
            out = judged.output
            if out.table_disagree:
                # LLM의 반대 의견은 기록만 한다. 본문은 Langfuse generation output에 남아 있어 여기서는 표 등급만 적는다
                logger.info("table_disagree table=%s gray=%s", table, gray)
            # V8 (09-30 D7): 등급이 표와 같아야 한다. 회색 지대면 표 이상이어야 한다 (위험을 낮추지 못하게)
            if not verdict_table.allowed(out.verdict, table, gray):
                log_failure("validate", f"V8 attempt {attempt}")
                need = f"{table} or higher" if gray else table
                feedback = (f"V8: verdict must be {need} (the judgment table decided {table}). "
                            "Write reasons, actions, and answer for that verdict.")
            else:
                response = _judged(out, signal_set, request, customs, collected, table, from_cache=from_cache)
                violations = validate.check(response, extra=memory_numbers)
                # V9·V10 판정판 (10-01): 통관 단계명(외부 데이터)에 넣은 주입이 설명 칸에 섞이지 않게 한다 (validate.py)
                texts = [out.answer, *out.actions, *[c.why for c in out.conflicts]]
                if out.customs:
                    texts += [out.customs.plain_explanation, out.customs.next_stage or ""]
                external = " ".join([customs.stage_name or "", *[s.name for s in customs.stage_history]]) if customs else ""
                # 기억 블록의 낱말은 V9·V10 근거가 아니다 (F8): 메모에 심은 낱말이 낱말 검사를 통과시키면 안 된다
                violations += validate.check_judge_text(texts, response, external,
                                                         llm.skills_reference(llm.JUDGE_SKILLS, llm.JUDGE_PROMPT))
                # V12 (10-02): 메모장 내부 번호가 새어 나오지 않게 (docs/specs/memory.md EC-09).
                # 기억 블록을 실제로 LLM에 줬을 때만 건다. 평가·데모·비로그인·회색 지대 경로에는 번호가 있을 수 없다
                if judge_memory:
                    violations += validate.check_memory_ids(texts, _evidence_text(response))
                if not violations:
                    # 검증을 통과한 뒤에 확인처(다음 행선지)를 붙인다. LLM이 쓴 문장이 아니라 코드 문장이라
                    # V1~V12 검사 대상이 아니고, 전화번호·시각 숫자가 V7 근거 검사에 걸리지도 않는다 (services/referrals.py, 10-06)
                    return response.model_copy(update={"actions": referrals.with_signal_lines(response.actions, signal_set)})
                # 규칙 번호만 남긴다. detail에는 LLM이 쓴 문장이 들어 있다
                log_failure("validate", f"{','.join(v.rule for v in violations)} attempt {attempt}")
                feedback = "\n".join(f"{v.rule}: {v.detail}" for v in violations)
        if attempt == JUDGE_ATTEMPTS - 1:
            feedback += "\nReturn JSON only and follow every rule above."
    log_failure("judge", f"gave up after {JUDGE_ATTEMPTS} attempts")
    return _llm_gave_up(signal_set, margin, table, gray, customs, collected)


def _judged(out, signal_set, request: AgentRequest, customs: CustomsRecord, collected: dict, table: str,
            from_cache: bool = False) -> AgentResponse:
    """LLM 판정 1회분을 응답으로 옮긴다. 검증(validate.check)은 부르는 쪽이 한다.

    from_cache면 위치가 실시간이 아니라 캐시에서 왔다는 뜻이라, 판정이 나와도 status를 partial로 둔다.
    """
    # 등급은 부르는 쪽에서 허용 범위(verdict_table.allowed)를 이미 확인했다. 표보다 올렸을 때만 LLM이 정한 것이다
    verdict = out.verdict
    decided_by = "llm" if verdict_table.LEVEL[verdict] > verdict_table.LEVEL[table] else "rule"
    # V2: watch·act면 이유가 1개 이상. LLM이 비워 두면 표의 근거(켜진 신호, D4 여유 일수)를 쓴다
    reasons = out.reasons or (verdict_table.table_reasons(signal_set, collected.get("days_margin"))
                              if verdict != "fine" else [])

    status, missing = "ok", []
    if from_cache:
        status = "partial"  # 도구 실패를 캐시로 메웠다. 판정은 두되 실시간 확인이 아니었음을 알린다 (평가셋 F02)

    return _response(
        status=status,
        verdict=verdict,
        decided_by=decided_by,
        missing_inputs=missing,
        reasons=reasons,
        conflicts=out.conflicts,
        actions=out.actions,
        answer=out.answer,
        customs=_customs_info(customs, out.customs),
        **collected,
    )


def _llm_gave_up(signal_set, margin: int | None, table: str, gray: bool, customs: CustomsRecord,
                 collected: dict) -> AgentResponse:
    """판정 LLM이 끝내 실패했을 때의 응답 (09-30 결정). status는 늘 partial이다. 설명 문장을 못 만들었기 때문이다.

    - 표가 확실하면: 등급은 코드 판정 표가 책임지므로 그 등급을 낸다. LLM 문장은 위반했거나 틀린 등급에 맞춰
      쓰였을 수 있어 쓰지 않고 고정 문구를 쓴다. 통관 해설도 없어 비운다 (_customs_info가 None)
    - 회색 지대면: 표 등급은 "최소 이만큼"이라 실제보다 낮을 수 있다. 낮은 등급을 확정처럼 보이지 않게 등급 없이 둔다
    전에는 세 번 모두 위반이면 등급까지 버리고 failed였다. 이제 failed는 통관 정보를 못 가져왔을 때만 쓴다.
    """
    if gray:
        return _response(status="partial", answer=LLM_FAILED, **collected)
    return _response(
        status="partial",
        verdict=table,
        decided_by="rule",
        reasons=verdict_table.table_reasons(signal_set, margin) if table != "fine" else [],
        actions=referrals.signal_lines(signal_set),  # 설명은 못 만들었어도 신호별 확인처는 코드가 붙인다 (10-06)
        answer=TABLE_FALLBACK.format(label=VERDICT_LABEL[table]),
        customs=_customs_info(customs, None),
        **collected,
    )


def _no_position(position: dict | None, request: AgentRequest, collected: dict) -> AgentResponse:
    """쓸 위치가 없을 때 LLM 없이 보류 응답을 만든다 (09-29 결정). 조회한 값(해수부 예정·근거 카드)은 참고로 둔다.

    둘로 나눈다. 해결책이 달라서다.
      - 데이터 자체가 없음(도구는 성공, 관측값 없음 = not_found, 또는 MMSI가 없어 못 부름)
        → 사용자가 포워더에게 알아 올 수 있다. insufficient로 입항 예정일을 묻는다 (평가셋 B13)
      - 도구 고장(권한 없음, 시간 초과인데 캐시도 없음 등)
        → 우리 쪽 문제라 사용자에게 되묻지 않는다. partial (평가셋 F04, SDD 8절 ShipFinder 21)
    """
    error_code = ((position or {}).get("error") or {}).get("code")
    if position is None or error_code == "not_found":
        # 이미 포워더 입항 예정일을 받았으면 더 물을 게 없어 partial (V5: insufficient면 물을 것이 1개 이상)
        if request.forwarder_eta:
            return _response(status="partial", answer=POSITION_MISSING_AFTER_ETA, **collected)
        return _response(status="insufficient", missing_inputs=["forwarder_eta"], answer=POSITION_MISSING, **collected)
    return _response(status="partial", answer=_tool_failed_text(POSITION_TOOL_FAILED, error_code), **collected)


def _tool_failed_text(base: str, error_code: str | None = None) -> str:
    """도구 실패 문구. ShipFinder 하루 한도를 다 쓴 날이면 "잠시 뒤 다시"를 "내일 다시"로 바꾼다 (10-06 점검).
    도구 응답의 오류 코드가 quota_exhausted이거나, 같은 프로세스가 오늘 38을 받았으면 한도 소진으로 본다."""
    if error_code == "quota_exhausted" or shipfinder_client.quota_blocked():
        return base.replace(" 잠시 뒤 다시 조회해 주세요.", "") + QUOTA_EXHAUSTED_TAIL
    return base


def _no_eta(signal_set, collected: dict) -> AgentResponse:
    """판매일은 있는데 믿을 도착일이 없어 여유 일수를 못 셀 때 (09-29 결정 D6). LLM 없이 보류한다.

    남은 거리 ÷ 현재 속도로 코드가 계산한 대략 도착(calc_eta)이 있으면 "참고용"이라고 밝혀 같이 보여 준다.
    판정 근거로는 쓰지 않는다. 속도가 바뀌거나 다른 항구에 들르면 크게 달라지기 때문이다.
    사용자에게는 포워더 A/N 입항 예정일을 묻는다. 받으면 그 날짜로 여유 일수를 센다 (signals.trusted_eta)
    """
    answer = NO_ETA
    if signal_set.calc_eta:
        day = signal_set.calc_eta.astimezone(KST)
        answer = NO_ETA_WITH_ESTIMATE.format(month=day.month, day=day.day)
    return _response(status="insufficient", missing_inputs=["forwarder_eta"], answer=answer, **collected)


def _released(customs: CustomsRecord) -> AgentResponse:
    """반출이 끝난 화물의 응답. 판정은 규칙으로 fine이고 LLM은 부르지 않는다 (09-28 결정).

    반출 뒤에는 기다릴 입항도 통관도 없어서 "지금 신경 써야 하나?"의 답은 괜찮음이다.
    반출 뒤 배송 일정은 PRD 4절 "창고 수령일 예측"이라 판정하지 않고 운송사로 안내한다.
    통관 이력·보관 장소·근거 카드는 UNI-PASS 값으로 채우고, 배를 찾지 않았으니 배·위치·ETA 칸은 비운다.
    판매 예정일이 지났어도 fine이다. 늦어졌는지는 배송 쪽 일이라 이 서비스가 볼 수 없다.
    """
    return _response(
        status="ok",
        verdict="fine",
        decided_by="rule",
        actions=RELEASED_ACTIONS,
        answer=RELEASED,
        customs=CustomsInfo(
            stage_code=customs.stage_code or "",
            stage_name=customs.stage_name,
            plain_explanation=RELEASED_EXPLANATION,
            next_stage=None,
            needs_broker=signals_service.needs_broker(customs.stage_name),
            history=[s.model_dump(mode="json") for s in customs.stage_history],
            **customs.route_fields(),
            **customs.party_fields(),  # 포워더·선사·컨테이너·품명 (10-06)
        ),
        berth=BerthInfo(facility=None, shed=customs.shed_name),
        evidence=build_evidence(customs, None, None, None, None, None),
    )


def _evidence_text(response: AgentResponse) -> str:
    """근거 카드 값을 한 글로. V12가 원래 근거에 있는 같은 글자(예: 항차 이름 C12)를 번호 새어 나옴으로 보지 않게 한다."""
    return " ".join(f"{e.field} {e.value}" for e in response.evidence)


def _follow_up(request: AgentRequest, user_id: str | None = None, memory: str | None = None) -> AgentResponse:
    """후속 질문 (C-9). 같은 세션·같은 B/L의 가장 최근 결과를 DB에서 꺼내 그 안에서만 답한다.

    세션별로 지난 결과를 저장해 두는 방식이다 (09-27 결정). 로그인했으면 세션 대신 사용자 ID로 찾는다 (G3).
    폰에서 조회하고 노트북에서 물어도 이어진다.
    DB가 없거나 지난 결과가 없으면 조회·판정을 한 번 더 해서 그 결과로 답한다 (채점 환경은 DB 없이 돌 수 있다).
    판정·근거는 지난 결과 그대로 두고 answer만 질문의 답으로 바꿔 돌려준다.
    """
    previous = _previous_response(request, user_id) or _assess(request, memory)
    failed = previous.model_copy(update={"answer": FOLLOW_UP_FAILED, "trace_id": current_request_id()})

    # 프롬프트 주입 차단 (SDD 7절, 10-01). 측정에서 "지금부터 너는 ~" 질문이 프롬프트 방어만으로는 20회 중 4회 뚫려
    # 검증을 통과한 채 사용자에게 갔다. 모양이 걸리면 LLM을 부르지 않는다. 질문 원문은 로그에 남기지 않는다
    if guard.looks_like_injection(request.follow_up_question):
        log_failure("follow_up", "blocked prompt injection pattern")
        return previous.model_copy(update={"answer": FOLLOW_UP_BLOCKED, "trace_id": current_request_id()})

    progress.step("answer")
    # 후속 답도 검증한다 (09-29). 전에는 검증 없이 나가 근거 카드에 없는 숫자("9월 23일", 사용자가 말한 판매일)가 그대로 갔다 (평가 F06).
    # 판정·근거는 지난 결과 그대로라 답 문장을 보는 규칙(FOLLOW_UP_RULES)만 건다. 재시도 방식은 판정과 같다 (SDD 5.7)
    feedback = None
    tools = read_only_tools()  # LLM이 직접 고를 읽기 전용 MCP 도구 (10-02, D9 B안). 못 받으면 빈 목록 → 도구 없이 답한다
    for attempt in range(1, JUDGE_ATTEMPTS + 1):
        try:
            answer = llm.answer_follow_up(request.follow_up_question, previous, feedback=feedback,
                                          tools=tools, run_tool=_follow_up_tool, memory=memory)
            out = answer.output
        except llm.LLMFormatError as e:
            log_failure("follow_up", f"{e.kind} attempt {attempt}")
            feedback = e.detail
            continue
        except llm.LLMError as e:
            # 도구를 줬더니 모델·제공사가 요청을 거절하면(bad_request) 도구 없이 다시 묻는다 (10-02 실측: OpenRouter
            # gpt-4o-mini는 도구를 붙이면 계정 데이터 정책에 맞는 제공사가 없다며 404, 도구 없이는 정상). 후속 답 자체는 막지 않는다
            if tools and e.kind == "bad_request":
                log_failure("follow_up", "tools rejected, retry without tools")
                tools = []
                continue
            log_failure("follow_up", _llm_error(e))
            return failed
        # LLM이 부른 도구 결과를 근거 카드로 붙인다. 답에 쓴 새 숫자·낱말이 근거에 있어야 검증(V7·V9·V10)을 통과하고,
        # 화면에도 어디서 온 값인지 남는다 (가이드 Grounding: 도구가 준 근거·출처를 보존)
        grounded = previous.model_copy(update={"evidence": previous.evidence + _tool_evidence(answer.tool_calls)})
        # 컨테이너 번호표 [CNTR1]은 번호가 아니라 이름표다 (10-06). 검증에는 번호표를 뺀 글을 넣는다: 그대로 두면 V7이 번호표 속
        # 숫자 1을 근거에 없는 숫자로, V9가 CNTR을 근거에 없는 낱말로 잡는다. 사용자 화면에는 아래 return에서 원래 번호로 되돌린다
        text = llm.CONTAINER_TOKEN.sub("", out.answer)
        answered = grounded.model_copy(update={"answer": out.answer, "trace_id": current_request_id()})
        # V11은 할 일·통관 칸도 보는데, 후속 답은 그 칸을 지난 결과에서 그대로 가져온다. 새로 쓴 answer만 보게 비우고 검사한다
        checked = answered.model_copy(update={"answer": text, "actions": [], "customs": None})
        violations = [v for v in validate.check(checked, extra=validate.user_supplied_text(memory)) if v.rule in FOLLOW_UP_RULES]
        # V9: 근거에 없는 영문 낱말 금지. 주입이 끼워 넣는 표식을 문장 모양과 상관없이 잡는다 (10-01, validate.py)
        # 기억 블록의 낱말은 V9·V10 근거가 아니다 (10-02 검증 F8)
        violations += validate.check_follow_up_words(text, grounded,
                                                     llm.skills_reference((), llm.FOLLOW_UP_PROMPT))
        # V10: 질문에만 있는 낱말을 답이 그대로 옮기면 위반. 한국어 표식 주입을 잡는다 (10-01, validate.py)
        violations += validate.check_follow_up_echo(text, request.follow_up_question, grounded,
                                                    llm.skills_reference(llm.FOLLOW_UP_SKILLS, llm.FOLLOW_UP_PROMPT))
        # V12 (10-02): 메모장 내부 번호가 새어 나오지 않게 (docs/specs/memory.md EC-09). 기억 블록을 줬을 때만 건다
        if memory:
            violations += validate.check_memory_ids([text], _evidence_text(grounded))
        if not violations:
            # 검증을 통과한 뒤에 되돌린다. LLM에는 번호표만 갔고(llm.answer_follow_up), 화면의 답에는 사용자 화물의 실제 번호가 나간다.
            # 같은 container_tokens로 지난 결과에서 다시 만들어서 LLM이 본 번호표와 번호가 맞는다
            tokens = llm.container_tokens(previous.customs.container_no if previous.customs else None)
            return answered.model_copy(update={"answer": llm.restore_containers(out.answer, tokens)})
        log_failure("validate_follow_up", f"{','.join(v.rule for v in violations)} attempt {attempt}")
        feedback = "\n".join(f"{v.rule}: {v.detail}" for v in violations)
    # 세 번 다 어기면 틀린 문장을 내보내지 않고 답하지 못했다고 한다. 지난 판정·근거는 그대로 둔다
    log_failure("follow_up", f"gave up after {JUDGE_ATTEMPTS} attempts")
    return failed


def _without_dest(value):
    """도구 결과에서 AIS 목적지 원문(dest)을 뺀다. 아무 배나 쓸 수 있는 글자라 주입 문장이 들어올 수 있다.
    판정·후속 질문 LLM 입력에서 빼는 것과 같은 기준이다 (SDD 7절, llm.answer_follow_up, 10-01)."""
    if isinstance(value, dict):
        return {k: _without_dest(v) for k, v in value.items() if k != "dest"}
    if isinstance(value, list):
        return [_without_dest(v) for v in value]
    return value


def _follow_up_tool(name: str, arguments: dict) -> dict:
    """후속 질문에서 LLM이 고른 도구를 실제로 부른다 (10-02, D9 B안). 결과는 LLM에게 돌아간다.

    - 읽기 전용 목록(read_only_tools)에 없는 이름은 부르지 않는다. 모델이 없는 도구를 지어내도 막힌다 (D9 도구 권한 정책)
    - 부르는 길은 판정 흐름과 같다: /mcp를 거치고(mcp_client.call_tool) Langfuse에 mcp:<도구> 기록이 남는다
    - 실패는 판정 흐름처럼 로그에 남기고, 결과도 {error}로 돌려줘 LLM이 "조회 실패"라고 답하게 한다
    """
    if name not in {t["function"]["name"] for t in read_only_tools()}:
        log_failure("follow_up_tool", f"unknown_tool {name}")
        return {"error": {"code": "unknown_tool", "message": f"no read-only tool named {name}", "retryable": False}}
    result = _without_dest(call_tool(name, **arguments))
    _log_tool_error(f"follow_up_tool:{name}", result)
    return result


def _tool_evidence(calls: list[dict]) -> list[Evidence]:
    """LLM이 부른 도구의 성공 결과를 근거 카드로 바꾼다. 실패한 호출은 카드를 만들지 않는다.

    칸 이름은 "<도구>.<키>", 값은 글자로 둔다. 목록·묶음 값(후보 목록 등)은 JSON 글자로 넣는다. 목적지 원문은 이미 빠져 있다.
    조회 시각은 도구가 준 fetched_at (모든 도구 응답에 붙는다, CLAUDE.md "할 것").
    """
    cards = []
    for call in calls:
        result, name = call.get("result") or {}, call.get("name", "")
        if "error" in result or name not in TOOL_SOURCE:
            continue
        try:
            fetched_at = datetime.fromisoformat(str(result.get("fetched_at")).replace("Z", "+00:00"))
        except ValueError:
            fetched_at = datetime.now(timezone.utc)
        for key, value in result.items():
            if key in ("source", "fetched_at", "cached_at") or value in (None, "", [], {}):
                continue
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            cards.append(Evidence(source=TOOL_SOURCE[name], field=f"{name}.{key}", value=text, fetched_at=fetched_at))
    return cards


def _previous_response(request: AgentRequest, user_id: str | None = None) -> AgentResponse | None:
    """DB에 저장된 지난 결과. 없거나 DB에 못 붙으면 None (그러면 다시 조회한다).

    가린 번호가 같은 두 화물을 가른다 (docs/specs/memory.md EC-05). 로그인 사용자의 이력 줄에는 잠긴 원본 B/L이 있어서
    (007 마이그레이션), 가린 번호가 같은 최근 줄들을 열어 이번 B/L과 같은 줄만 쓴다(_same_cargo). 스키마는 바꾸지 않는다.
    로그인이 꺼진 환경은 원본을 저장하지 않는다. 대신 결과 JSON에 B/L 지문(열쇠 있는 HMAC, BL_FINGERPRINT_KEY)을 넣어 두고
    같은 지문의 줄만 쓴다 (10-06 점검: 가린 번호만으로 찾으면 가린 모양이 같은 두 화물이 섞였다). 열쇠가 없으면 지문도 없어 예전처럼 찾는다.

    입력이 바뀌었으면 지난 결과를 쓰지 않는다 (10-06 점검, _inputs_changed). 판매 예정일이나 포워더 입항 예정일을 새로 주고
    물었는데 옛 여유 일수·등급으로 답하면 틀린 답이다. None을 돌려주면 _follow_up이 새로 조회·판정한 결과로 답한다.
    """
    if not _db_configured("db_read"):
        return None
    try:
        with connect() as conn:
            saved = _same_cargo(recent_responses(conn, request.session_id, mask_bl(request.bl_no), user_id), request.bl_no)
    except Exception as e:
        log_failure("db_read", type(e).__name__)
        return None
    if not saved:
        return None
    previous = AgentResponse.model_validate(_open_containers(saved))
    if _inputs_changed(request, previous):
        logger.info("follow_up inputs changed, reassessing")
        return None
    return previous


# 사용자가 준 날짜 중 바뀌면 여유 일수·등급이 달라지는 것. 지난 결과의 근거 카드(services/evidence.py, source=rule)에 같은 이름으로 있다
_DATE_INPUTS = ("sale_due_date", "forwarder_eta")


def _inputs_changed(request: AgentRequest, previous: AgentResponse) -> bool:
    """이번 요청의 판매 예정일·포워더 입항 예정일이 지난 결과를 만들 때 쓴 값과 다른가 (10-06 점검).
    지난 값은 근거 카드에서 읽는다. 이번 요청에 값이 없으면 바뀐 것으로 보지 않는다(후속 질문은 보통 날짜를 다시 안 보낸다)."""
    used = {e.field: e.value for e in previous.evidence if e.source == "rule" and e.field in _DATE_INPUTS}
    for field in _DATE_INPUTS:
        value = getattr(request, field)
        if value is not None and used.get(field) != value.isoformat():
            return True
    return False


# 이력(query_log.response)에 컨테이너 번호를 잠가 두는 칸 이름. AgentResponse에는 없는 칸이라 읽을 때 꺼내고 지운다
SEALED_CONTAINER_KEY = "container_no_sealed"
# 이력에 B/L 지문을 두는 칸 이름 (10-06 점검). 원문이 아니라 BL_ENCRYPTION_KEY로 만든 HMAC이라 되돌릴 수 없다.
# 로그인 없이 남긴 줄도 가린 번호가 같은 다른 화물과 가를 수 있게 한다 (_cargo_rows). 읽을 때 지운다
BL_FINGERPRINT_KEY = "bl_fingerprint"


def _bl_fingerprint(bl_no: str) -> str | None:
    """B/L 지문. 열쇠가 없으면 None (그때는 지문 없이 저장하고, 찾을 때도 예전처럼 가린 번호로 찾는다).
    열쇠가 없는 채점 환경에서 요청마다 no_key 로그가 쌓이지 않게 먼저 열쇠를 본다."""
    if not os.environ.get(crypto.BL_KEY_ENV, "").strip():
        return None
    return crypto.fingerprint(bl_no, key_env=crypto.BL_KEY_ENV)


def _seal_containers(response: AgentResponse, bl_no: str | None = None) -> dict:
    """이력에 저장할 결과. 컨테이너 번호를 평문으로 남기지 않는다 (10-06 점검, #69).

    - customs.container_no 칸은 빼고, 같은 번호를 B/L과 같은 열쇠로 잠가 SEALED_CONTAINER_KEY에 둔다 (crypto.encrypt, BL_ENCRYPTION_KEY).
      빼기만 하면 후속 질문이 이력을 읽을 때 번호를 몰라 "컨테이너 번호 뭐야?"에 답하지 못한다 (10-06 정운 결정: 알아야 한다)
    - 다른 글자(후속 답 등)에 남은 번호는 [CNTR1] 번호표로 바꾼다. 풀린 번호로 같은 번호표가 다시 만들어진다 (llm.container_tokens)
    - 열쇠가 없으면(encrypt가 None) 잠근 칸 없이 저장한다. 그때는 번호를 잃는 쪽이 원문을 남기는 쪽보다 낫다
    """
    number = response.customs.container_no if response.customs else None
    data = llm.hide_containers(
        response.model_dump(mode="json", exclude={"customs_detail": True, "customs": {"container_no"}}),
        llm.container_tokens(number))
    sealed = crypto.encrypt(number) if number else None
    if sealed:
        data[SEALED_CONTAINER_KEY] = sealed
    fingerprint = _bl_fingerprint(bl_no) if bl_no else None
    if fingerprint:
        data[BL_FINGERPRINT_KEY] = fingerprint
    return data


def _open_containers(saved: dict) -> dict:
    """이력에서 꺼낸 결과에 잠가 둔 컨테이너 번호를 풀어 customs.container_no로 되돌린다. 못 풀면 칸 없이 둔다."""
    saved = dict(saved)
    saved.pop(BL_FINGERPRINT_KEY, None)
    sealed = saved.pop(SEALED_CONTAINER_KEY, None)
    number = crypto.decrypt(sealed) if sealed else None
    if number and isinstance(saved.get("customs"), dict):
        saved["customs"] = {**saved["customs"], "container_no": number}
    return saved


def _same_cargo(rows: list[tuple[dict, str | None]], bl_no: str) -> dict | None:
    """(결과, 잠긴 B/L) 줄들 중 이번 B/L과 같은 가장 최근 결과 (EC-05). 가르는 기준은 _cargo_rows."""
    matched = _cargo_rows(rows, bl_no)
    return matched[0] if matched else None


def _cargo_rows(rows: list[tuple[dict, str | None]], bl_no: str) -> list[dict]:
    """(결과, 잠긴 B/L) 줄들 중 이번 B/L의 결과만 최신순으로.

    줄마다 잠긴 원본(로그인 사용자, 007)을 열어 보고, 없으면 결과 JSON의 B/L 지문(BL_FINGERPRINT_KEY, 10-06)과 비교한다.
    한 줄도 확인할 수 없으면(열쇠가 없어 원본도 지문도 없던 줄들) 예전처럼 모두 쓴다. 다른 화물로 확인된 줄은 쓰지 않는다."""
    import hmac

    mine = _bl_fingerprint(bl_no)
    checked, matched, unknown = False, [], []
    for response, sealed in rows:
        original = crypto.decrypt(sealed) if sealed else None
        if original is not None:
            checked = True
            if original == bl_no:
                matched.append(response)
            continue
        stored = response.get(BL_FINGERPRINT_KEY) if isinstance(response, dict) else None
        if stored and mine:
            checked = True
            if hmac.compare_digest(str(stored), mine):
                matched.append(response)
            continue
        unknown.append(response)
    return matched if checked else unknown


def _fetch_customs(request: AgentRequest) -> tuple[CustomsRecord | None, AgentResponse | None]:
    """UNI-PASS 조회. 없는 B/L은 실패가 아니라 insufficient다 (SDD 4.1, 8절)."""
    try:
        record = UnipassClient().fetch(request.bl_no, request.bl_type)
    except CustomsError as e:
        log_failure("customs", e.code)
        # 오류 코드(timeout, bad_key)는 로그에만 남기고 화면 문장에는 넣지 않는다 (10-02 화면 용어 점검)
        return None, _response(status="failed", answer="통관 정보를 가져오지 못했습니다. 잠시 뒤 다시 조회해 주세요.")
    if record is None:
        return None, _response(status="insufficient", missing_inputs=["bl_type"], answer=NO_CARGO)
    return record, None


def _identify(customs: CustomsRecord, request: AgentRequest) -> tuple[list[VesselCandidate], str, int | None, str | None]:
    """후보 1척이면 확정, 여럿이면 LLM이 고르고, 확실하지 않으면 되묻기. 사용자가 고른 MMSI가 있으면 그것을 쓴다.

    여럿일 때는 llm.pick_vessel()을 부르고 confidence가 high일 때만 확정한다 (SDD 5.5, C-5).
    medium·low이거나 LLM이 실패하면 확정하지 않고 되묻는다.
    확정하지 않는 쪽이 남의 배를 내 배라고 답하는 것보다 낫다 (PRD 6.2).

    호출부호도 같이 돌려준다. C1 VesselCandidate에는 자리가 없지만 해수부 조회에 필요하다.

    MRN 먼저 (09-28): B/L의 MRN으로 해수부 입항 신고에서 호출부호를 찾고, 그 호출부호로 최근 신호를 보낸 배가
    1척이면 코드가 확정한다 (services/identify.py). 이름이 아니라 번호로 이어서 동명 선박·표기 차이가 없다.
    MRN으로 못 찾거나(입항 신고 전 등) 호출부호로 최근 배가 1척이 아니면 지금까지처럼 이름으로 찾는다.
    """
    mrn_call_sign = identify.call_sign_from_mrn(customs)
    if request.resolved_mmsi:
        # 사용자가 고른 배. 이 화물의 후보 중 하나일 때만 확정한다 (10-06 점검, _resolved_pick)
        picked = _resolved_pick(customs, request, mrn_call_sign)
        if picked == TOOL_FAILED:
            return [], TOOL_FAILED, None, None
        if picked is not None:
            chosen, picked_call_sign = picked
            # 호출부호를 알면 해수부를 호출부호로 조회한다 (선명으로 훑으면 14초, 09-28 실측)
            return [chosen], "confirmed", chosen.mmsi, mrn_call_sign or picked_call_sign
        # 후보에 없는 번호: 무시하고 보통 식별로 간다. 결과는 부르는 쪽(_after_customs)이 되묻기로 바꾼다
        log_failure("identify", "resolved_mmsi_not_candidate")
        request = request.model_copy(update={"resolved_mmsi": None})

    if mrn_call_sign:
        result = get_vessel_candidates(ship_name=customs.ship_name or "", call_sign=mrn_call_sign)
        _log_tool_error("vessel_candidates_mrn", result)
        if "error" not in result:
            found = _candidates(result.get("candidates", []), "MRN 입항 신고의 호출부호 일치")
            if len(found) == 1:
                return found, "confirmed", found[0].mmsi, mrn_call_sign
        # 실패·0척·여럿이면 아래 이름 검색으로 넘어간다

    if not customs.ship_name:
        return [], "none", None, None

    # 도구의 국적 필터(nationality)는 쓰지 않는다 (09-28 결정). 세관은 "KR"·"MH" 같은 코드를, ShipFinder는
    # "Korea, Republic of"·"Marshall Islands" 같은 영어 이름을 주는데 필터는 글자 포함으로 비교해서,
    # MH처럼 이름에 코드 글자가 없는 나라는 진짜 내 배를 말없이 뺄 수 있다. 국적이 다르면 아래에서 되묻는다
    result = get_vessel_candidates(ship_name=customs.ship_name)
    if "error" in result:
        _log_tool_error("vessel_candidates", result)
        return [], TOOL_FAILED, None, None
    rows = result.get("candidates", [])
    candidates = _candidates(rows)
    if not candidates:
        return [], "none", None, None
    if len(candidates) == 1:
        only = rows[0]
        # MRN 서류로 호출부호를 아는데 이름으로 찾은 1척의 호출부호가 다르면 이름만 같은 남의 배다.
        # 확정하지 않고 되묻는다 (09-28 결정, 평가 B07). 후보의 호출부호를 모르면 어긋난다는 근거가 없어 지금처럼 확정한다
        if mrn_call_sign and only.get("call_sign") and not _same_call_sign(mrn_call_sign, only["call_sign"]):
            return candidates, "uncertain", None, None
        # 세관 국적과 후보 국적이 다르면 역시 되묻는다 (09-28 결정, 평가 B14). 둘 중 하나라도 모르면 확정한다.
        # 비교가 틀려도(코드·이름 표기 차이) 진짜 배를 버리지 않고 한 번 더 묻는 쪽으로 실수한다
        if customs.ship_nat and only.get("flag") and not _same_nationality(customs.ship_nat, only["flag"]):
            return candidates, "uncertain", None, None
        return candidates, "confirmed", candidates[0].mmsi, only.get("call_sign")

    # 여럿인데 사용자가 준 근거(항차·포워더 입항 예정일)가 없으면 LLM을 부르지 않고 바로 되묻는다 (10-01, 평가 B01·B12).
    # 이름·목적지·위치는 어느 배가 내 화물을 실었는지의 근거가 아니다. 그런데 gpt-4o-mini는 근거 없이도 high로 골라
    # 남의 배를 확정했다(B01 매번, B12 3번 중 2~3번, 데모 TESTBL04). 확정은 근거가 있을 때만 한다 (PRD 6.2 되묻기가 낫다).
    # SDD 5.5("2척 이상이면 LLM")와 다르다. 문서는 팀이 나중에 몰아서 현행화한다
    if not (request.voyage_no or request.forwarder_eta):
        # 사용자에게 묻기 전에 서류끼리 먼저 맞춰 본다 (10-05 결정, services/identify.match_by_papers).
        # 세관 입항일·적재항과 후보별 해수부 입항 신고가 둘 다 맞는 배가 1척이면 확정한다. 이름·위치는 쓰지 않는다
        # 후보 목록(candidates)에 든 배만 맞춰 본다. 목록에서 빠진 줄을 확정하면 화면에 그 배가 없다
        listed = {c.mmsi for c in candidates}
        papers = identify.match_by_papers(customs, [r for r in rows if r.get("mmsi") in listed], mrn_call_sign=mrn_call_sign,
                                          same_call_sign=_same_call_sign,
                                          same_nationality=lambda a, b: not _clearly_other_nationality(a, b))
        if papers:
            mmsi, matched_call_sign, reason = papers
            # 확정한 배 1척만 돌려준다 (MRN 단계와 같다). 화면 VesselCard가 그 배와 근거를 보여 줘야 틀렸을 때 사용자가 안다
            chosen = [c for c in candidates if c.mmsi == mmsi]
            chosen[0].match_reasons = [*chosen[0].match_reasons, reason]
            return chosen, "confirmed", mmsi, matched_call_sign
        return candidates, "uncertain", None, None

    # 되묻기에 답한 항차·포워더 입항 예정일이 있으면 LLM이 그 근거로 고른다
    try:
        picked = llm.pick_vessel(candidates, customs, request.voyage_no, request.forwarder_eta).output
    except llm.LLMError as e:
        log_failure("pick_vessel", _llm_error(e))
        return candidates, "uncertain", None, None
    # 후보에 없는 MMSI는 확정하지 않는다. 후보 목적지 문자열 속 지시문에 속았거나 번호를 지어냈을 수 있다 (C-10)
    if picked.confidence == "high" and picked.choice in {c.mmsi for c in candidates}:
        call_sign = next((row.get("call_sign") for row in rows if row["mmsi"] == picked.choice), None)
        return candidates, "confirmed", picked.choice, call_sign
    return candidates, "uncertain", None, None


# 지켜보기 재판정이 다시 쓰는 배 (services/watch.py). 그 화물을 처음 조회할 때 이미 확정해 user_cargo.vessel_mmsi에 저장한 배라
# 후보 확인 검색(ShipFinder 1~2회)을 다시 하지 않는다. 워커는 화물당 ShipFinder 1회만 떼어 두기 때문이다 (worker/run.py, 10-06 점검).
# 사용자 요청 경로에서는 늘 None이다. 화면이 보낸 resolved_mmsi는 아래처럼 후보와 대조한다
trusted_vessel: ContextVar[int | None] = ContextVar("trusted_vessel", default=None)


def _resolved_pick(customs: CustomsRecord, request: AgentRequest,
                   mrn_call_sign: str | None) -> tuple[VesselCandidate, str | None] | str | None:
    """사용자가 고른 MMSI가 이 화물의 후보인지 확인한다 (10-06 점검).
    (후보, 호출부호), 후보가 아니면 None, 검색 도구가 모두 실패하면 TOOL_FAILED.

    1. 이 화물의 지난 되묻기 응답(조회 이력)에 실린 후보 목록. 외부 호출이 없어 먼저 본다
    2. 없으면 식별과 같은 검색을 다시 한다: MRN 호출부호 검색, 그다음 선명 검색. ShipFinder 호출이 1~2번 늘지만
       남의 배를 확정하는 것보다 낫다 (PRD 6.2). 지켜보기 재판정처럼 이력이 없는 세션도 이 길로 확인된다
    """
    target = request.resolved_mmsi
    if trusted_vessel.get() == target:
        # 지켜보기 재판정: 저장해 둔 확정 배. 후보 줄 대신 세관 선명으로 최소한의 후보를 만든다 (_vessel_info가 쓰는 칸만)
        return VesselCandidate(mmsi=target, imo=None, name=customs.ship_name or "", flag=None, dest=None,
                               last_time=datetime.now(timezone.utc), ship_type=None,
                               match_reasons=["지켜보기에 저장된 확정 배"]), None
    for saved in _saved_cargo_responses(request):
        for row in saved.get("vessel_candidates") or []:
            if isinstance(row, dict) and row.get("mmsi") == target:
                try:
                    return VesselCandidate.model_validate(row), None
                except ValueError:
                    continue

    searches = []
    if mrn_call_sign:
        searches.append(("vessel_candidates_mrn", dict(ship_name=customs.ship_name or "", call_sign=mrn_call_sign)))
    if customs.ship_name:
        searches.append(("vessel_candidates", dict(ship_name=customs.ship_name)))
    failed = 0
    for stage, args in searches:
        result = get_vessel_candidates(**args)
        if "error" in result:
            _log_tool_error(stage, result)
            failed += 1
            continue
        rows = result.get("candidates", [])
        for candidate in _candidates(rows, "사용자가 후보에서 고른 배"):
            if candidate.mmsi == target:
                return candidate, next((r.get("call_sign") for r in rows if r.get("mmsi") == target), None)
    return TOOL_FAILED if searches and failed == len(searches) else None


def _saved_cargo_responses(request: AgentRequest) -> list[dict]:
    """이 세션(로그인했으면 사용자)·이 화물의 최근 결과 JSON들. DB가 없거나 못 읽으면 빈 목록.
    사용자 ID는 지금 요청의 사용량 이름(quota.owner_var, session_scope가 정한다)에서 꺼낸다. _assess의 인자를 늘리지 않으려는 것이다."""
    if not _db_configured("db_read"):
        return []
    owner = quota.owner_var.get() or ""
    user_id = owner[len("user:"):] if owner.startswith("user:") else None
    try:
        with connect() as conn:
            rows = recent_responses(conn, request.session_id, mask_bl(request.bl_no), user_id)
    except Exception as e:
        log_failure("db_read", type(e).__name__)
        return []
    return [r for r in _cargo_rows(rows, request.bl_no) if isinstance(r, dict)]


def _log_tool_error(stage: str, result: dict | None) -> None:
    """MCP 도구가 {"error": ToolError}를 돌려줬으면 코드만 로그에 남긴다. message는 예외 문장이라 넣지 않는다."""
    if result and "error" in result:
        log_failure(stage, result["error"].get("code") or "unknown")


def _position_history(mmsi: int | None) -> list[dict]:
    """워커가 DB에 모은 이 배의 위치 이력. anchor_wait 정지 시간을 재는 데 쓴다 (09-29, 평가셋 B08).

    DB가 없거나 읽기가 실패해도 판정은 계속한다. 이력이 없으면 정지 시간 신호가 unknown이 될 뿐이다.
    """
    if not mmsi or not _db_configured("positions_read"):
        return []
    try:
        with connect() as conn:
            return recent_positions(conn, mmsi)
    except Exception as e:
        log_failure("positions_read", type(e).__name__)
        return []


def _llm_error(e: llm.LLMError) -> str:
    """LLM 실패를 종류(kind)와 HTTP 코드로 줄인다. 메시지에는 공급자 응답 문장이 들어 있을 수 있어 뺀다."""
    return f"{e.kind} {e.code}" if e.code else e.kind


def _db_configured(stage: str) -> bool:
    """DATABASE_URL이 없으면 not_configured를 남기고 False. DB를 일부러 끈 경우(평가 실행기·채점 환경)와
    실제 DB 고장(연결 실패 등, 아래 except에서 예외 이름으로 남음)을 로그에서 구분하려는 것이다."""
    if os.environ.get("DATABASE_URL"):
        return True
    log_failure(stage, "not_configured")
    return False


def _same_call_sign(a: str, b: str) -> bool:
    """호출부호 비교. 대소문자와 앞뒤 공백 차이는 같은 것으로 본다 (vessel_candidates 도구의 호출부호 필터와 같은 기준)."""
    return a.strip().upper() == b.strip().upper()


def _same_nationality(customs_nat: str, flag: str) -> bool:
    """세관 국적(두 글자 코드, 예: KR)과 ShipFinder 국적(코드 또는 영어 이름)이 같은 나라인가.

    세관 코드를 ISO 국가 이름으로 바꿔(pycountry) 정확히 같은지만 본다. 09-28 실제 응답의 ShipFinder 국적은
    ISO 이름("Korea, Republic of")과 같은 모양이었다. 글자 포함으로 비교하면 KR과 "Korea"가 안 맞고
    ("kr"이 붙어 있지 않다) NE(니제르)와 "Nigeria"는 맞아 버려서 쓰지 않는다.
    코드를 모르거나 이름이 다르게 오면 다르다고 보고, 부르는 쪽이 되묻는다 (진짜 배를 버리지 않는 쪽으로 실수).
    """
    a, b = customs_nat.strip(), flag.strip()
    if a.upper() == b.upper():
        return True  # 둘 다 코드로 온 경우 (평가셋 fixture 등)
    country = pycountry.countries.get(alpha_2=a.upper()) if len(a) == 2 else None
    if country is None:
        return False
    names = {getattr(country, attr, None) for attr in ("name", "official_name", "common_name")}
    return b.lower() in {n.lower() for n in names if n}


def _clearly_other_nationality(customs_nat: str, flag: str) -> bool:
    """세관 국적과 후보 국적이 확실히 다른 나라인가. 둘 다 나라를 알아볼 수 있을 때만 True (10-05 검토).

    _same_nationality는 모르면 "다르다"로 답한다. 단일 후보에서는 그게 되묻기로 이어져 안전하지만, 여러 후보 중
    배를 빼는 데 쓰면 같은 실수가 진짜 배를 지운다. 그래서 빼는 쪽에는 이 함수를 쓴다: 모르면 빼지 않는다.
    """
    def country(value: str):
        v = value.strip()
        if len(v) == 2:
            return pycountry.countries.get(alpha_2=v.upper())
        for c in pycountry.countries:
            if v.lower() in {n.lower() for n in (c.name, getattr(c, "official_name", None), getattr(c, "common_name", None)) if n}:
                return c
        return None
    a, b = country(customs_nat), country(flag)
    return bool(a and b) and a.alpha_2 != b.alpha_2


def _candidates(rows: list[dict], reason: str | None = None) -> list[VesselCandidate]:
    """도구 출력 후보를 C1 VesselCandidate로 옮긴다. 마지막 신호 시각이 없는 후보는 뺀다.
    reason이 없으면 선명 유사도를 근거로 적는다."""
    return [
        VesselCandidate(
            mmsi=row["mmsi"],
            imo=row.get("imo"),
            name=row["name"],
            flag=row.get("flag"),
            dest=row.get("dest"),
            last_time=row["last_time"],
            ship_type=row.get("ship_type"),
            match_reasons=[reason or f"선명 유사도 {row.get('similarity')}"],
        )
        for row in rows
        if row.get("last_time")
    ]


def _vessel_info(candidates: list[VesselCandidate], mmsi: int | None, call_sign: str | None,
                 customs: CustomsRecord, request: AgentRequest) -> VesselInfo | None:
    """확정한 배를 C1 VesselInfo로 만든다 (SDD 3.2, schemas/agent.py VesselInfo). 확정 못 했으면 None.

    10-05 전에는 확정 경로에서 이 칸을 한 번도 채우지 않아 늘 null이었다(mrn_fallback만 채웠다).
    값은 후보 목록에서 그 MMSI 줄을 쓰고, 사용자가 직접 고른 배(resolved_mmsi)라 후보 줄이 없으면 세관 선명만 쓴다.
    국적은 스키마 설명대로 UNI-PASS shipNat 우선, 없으면 ShipFinder. 항차는 UNI-PASS vydf, 없으면 사용자 입력.
    """
    if not mmsi:
        return None
    row = next((c for c in candidates if c.mmsi == mmsi), None)
    name = (row.name if row else None) or customs.ship_name
    if not name:
        return None
    return VesselInfo(
        mmsi=mmsi,
        imo=row.imo if row else None,
        name=name,
        call_sign=call_sign,
        flag=customs.ship_nat or (row.flag if row else None),
        ship_type=row.ship_type if row else None,
        voyage_no=customs.voyage or request.voyage_no,
    )


def _distance(position: dict | None) -> dict | None:
    if not position or "error" in position:
        return None
    return estimate_distance(position["lat"], position["lng"], position.get("sog"))


def _position(position: dict | None, freshness: str = "unknown") -> Position | None:
    """도구 출력을 C1 Position으로 옮긴다. freshness는 signals가 계산한 값을 받아 쓴다 (코드가 정한다)."""
    if not position or "error" in position:
        return None
    return Position(
        lat=position["lat"],
        lng=position["lng"],
        sog=position.get("sog") or 0.0,
        cog=position.get("cog") or 0.0,
        navistat=position.get("navistat") or 0,
        last_time=position.get("last_time") or datetime.now(timezone.utc),
        freshness=freshness,
    )


def _eta(position: dict | None, schedule: dict | None, signal_set, trusted) -> EtaInfo:
    """ETA 출처별 값을 나란히 담는다. 화면이 어느 값을 왜 믿었는지 보여 줄 수 있게 (C1 EtaInfo)."""
    position = position if position and "error" not in position else {}
    schedule = schedule if schedule and "error" not in schedule else {}
    return EtaInfo(
        ais_eta=position.get("ais_eta"),
        mof_eta=schedule.get("planned_arrival"),
        calc_eta=signal_set.calc_eta,
        trusted_eta=trusted,
        distance_nm=signal_set.distance_nm,
    )


def code_written_explanation(stage_name: str | None) -> bool:
    """통관 설명 문장을 LLM이 아니라 코드가 쓰는 단계인가: 반출신고(_released)와 목록에 없는 단계.
    평가 실행기(evals/judge.py)가 이 단계들은 LLM 해설 채점에서 뺀다. 코드가 쓴 고정 문장이라 LLM 품질이 아니다 (10-01)."""
    if not stage_name:
        return False
    return stage_name == RELEASED_STAGE or not is_listed_stage(stage_name)


def _customs_info(customs: CustomsRecord, explained) -> CustomsInfo | None:
    """단계 이름·코드·이력은 UNI-PASS 값, 관세사 필요 여부는 코드 판단(10-01), 해설 둘은 LLM 값으로 C1 CustomsInfo를 만든다.

    목록에 없는 단계는 해설 둘도 코드가 쓴다: 고정 문장 + 다음 단계 null (10-01, UNLISTED_STAGE_EXPLANATION).
    뜻을 모르는 단계라 LLM 해설이 필요 없어서, LLM이 해설을 못 냈어도 이 경우는 채운다.
    그 밖에 단계 이름이 없거나 LLM이 해설을 안 냈으면 None."""
    if not customs.stage_name:
        return None
    if not is_listed_stage(customs.stage_name):
        plain_explanation = UNLISTED_STAGE_EXPLANATION.format(stage=customs.stage_name)
        next_stage = None
    elif explained is None:
        return None
    else:
        plain_explanation, next_stage = explained.plain_explanation, explained.next_stage
    return CustomsInfo(
        stage_code=customs.stage_code or "",
        stage_name=customs.stage_name,
        plain_explanation=plain_explanation,
        next_stage=next_stage,
        needs_broker=signals_service.needs_broker(customs.stage_name),
        history=[s.model_dump(mode="json") for s in customs.stage_history],
        **customs.route_fields(),  # 어디서 어디로 (10-01)
        **customs.party_fields(),  # 포워더·선사·컨테이너·품명 (10-06)
    )


def _as_jsonb(data: dict):
    """psycopg가 dict를 jsonb로 넣게 감싼다. psycopg는 DB를 쓸 때만 import한다 (db/__init__.py와 같은 이유)."""
    from psycopg.types.json import Jsonb

    return Jsonb(data)


def _logged(request: AgentRequest, response: AgentResponse, user_id: str | None = None) -> AgentResponse:
    """조회 이력 한 줄을 남기고 응답을 그대로 돌려준다 (A12). 로그인했으면 user_id도 같이 남긴다 (G3, 006 마이그레이션).

    로그인했으면 B/L 원본을 잠가서(bl_encrypted) 같이 남긴다. 메모리의 다시 조회가 쓴다 (② 암호화, 007 마이그레이션).
    사용자가 없으면(로그인 꺼진 채점 환경) 원본을 남기지 않는다. 열쇠가 없으면 crypto.encrypt가 None을 돌려줘 빈 칸으로 남는다.

    이력 저장이 실패해도 응답은 나가야 한다. DB 없이도 서비스가 돌아야 하기 때문이다.
    """
    if not _db_configured("db_write"):
        return response
    try:
        with connect() as conn:
            log_query(
                conn,
                request.session_id,
                user_id=user_id,
                bl_encrypted=crypto.encrypt(request.bl_no) if user_id else None,
                request_id=current_request_id(),
                bl_masked=mask_bl(request.bl_no),
                status=response.status,
                verdict=response.verdict,
                vessel_match=response.vessel_match,
                decided_by=response.decided_by,
                trace_id=response.trace_id,
                # 후속 질문이 꺼내 쓸 결과 전체 (004 마이그레이션). B/L 원본은 AgentResponse에 없다.
                # UNI-PASS 처리 이력 원문(customs_detail)은 화면 전용이라 저장하지 않는다 (docs/specs/customs-detail.md)
                # 컨테이너 번호도 평문 이력에 남기지 않는다. B/L처럼 화물을 특정하는 번호다 (schemas/customs.py, 10-06 점검).
                # 내 화물 현황 표에 필요한 값은 user_cargo가 따로 가진다 (services/cargo.py)
                # 칸을 빼는 것만으로는 부족하다: 후속 답(answer)은 화면용으로 실제 번호를 되돌린 문장이라(_follow_up) 그대로 두면
                # 다음 후속 질문 때 이력에서 원문이 LLM에 간다. 그래서 저장 전에 남은 글자 속 번호도 [CNTR1] 번호표로 바꾼다 (10-06 병합).
                # 번호 자체는 잠가서 따로 둔다(_seal_containers). 후속 질문이 이력을 읽을 때 풀어야 LLM이 번호표로 알고 답할 수 있다 (10-06 정운 결정)
                response=_as_jsonb(_seal_containers(response, request.bl_no)),
            )
    except Exception as e:
        log_failure("db_write", type(e).__name__)
    return response
