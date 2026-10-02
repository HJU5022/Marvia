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

6단계는 services/llm.judge()가 한다 (C-6, 09-27 연결). 결과를 어떻게 응답에 담나:
  - LLM이 끝내 실패하면(호출 실패, 세 번 모두 위반) status=partial. 등급은 판정 표 것을 내고 문장은 고정 문구. 회색 지대면 등급 없이 (09-30 결정, _llm_gave_up)
  - 등급은 코드가 판정 표로 정한다(decided_by=rule). LLM은 그 등급에 맞춰 설명·할 일·상충·통관 해설을 쓴다 (09-30 D7, services/verdict.py)
  - 회색 지대(anchor_wait·customs_hold가 unknown)만 LLM이 표 등급 이상에서 고른다. 표보다 올리면 decided_by=llm
  - LLM이 표가 틀렸다고 보면 table_disagree에 적는다. 응답에 쓰지 않고 기록만 한다 (Langfuse generation output, 로그)
  - 쓸 위치가 없으면 LLM을 부르지 않는다. 데이터 없음은 insufficient, 도구 고장은 partial (09-29 결정, _no_position)
  - 위치가 캐시에서 왔으면(실시간 조회 실패) 판정은 하되 status=partial (09-29 결정, 평가셋 F02)
근거 카드는 services/evidence.build()가 만든다 (C-8).
"""
import logging
import os
from datetime import datetime, timezone
from typing import Annotated

import pycountry
from fastapi import APIRouter, Depends

from backend.app import crypto
from backend.app.auth import current_user_id
from backend.app.db import connect, latest_response, log_query, recent_positions
from backend.app.observability.langfuse import session_scope
from backend.app.observability.logging import current_request_id, log_failure
from backend.app.schemas.agent import (
    AgentRequest, AgentResponse, BerthInfo, CustomsInfo, EtaInfo, Position, Reason, VesselCandidate,
)
from backend.app.schemas.customs import CustomsRecord, mask_bl
from backend.app.services import guard, identify, llm, progress, validate
from backend.app.services import verdict as verdict_table
from backend.app.services import signals as signals_service
from backend.app.services.evidence import KST, build as build_evidence, days_margin
from backend.app.services.rules import is_listed_stage, rule
from backend.app.services.customs import CustomsError, UnipassClient
# MCP 도구 4종은 /mcp를 거쳐 부른다 (10-02, services/mcp_client.py)
from backend.app.services.mcp_client import (
    estimate_distance, get_live_position, get_port_schedule, get_vessel_candidates,
)

router = APIRouter(prefix="/api", tags=["agent"])
logger = logging.getLogger(__name__)

NOT_JUDGED = "조회한 값을 정리했습니다. 판정은 아직 붙지 않았습니다."
NO_CARGO = "조회 결과가 없습니다. B/L 번호와 M/H 구분을 다시 확인해 주세요."
ASK_BACK = "같은 이름의 배가 여러 척입니다. 항차 번호나 포워더 ETA를 알려주시면 어느 배인지 가릅니다."
NO_VESSEL = "선박 위치 서비스에서 이 배를 찾지 못했습니다. 포워더 도착 통지서(A/N)의 입항 예정일을 알려주세요."
NO_VESSEL_AFTER_ETA = "선박 위치 서비스에서 이 배를 찾지 못해 판정하지 못했습니다. 입항 일정은 포워더에게 직접 확인해 주세요."
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
NOT_BUSAN = "부산항에 내리는 화물만 확인할 수 있습니다. 이 화물은 다른 항만으로 들어옵니다."
LLM_FAILED = "판정을 만들지 못했습니다. 조회한 값과 신호만 보여 드립니다."
# 판정 LLM이 끝내 실패했을 때 표 등급으로 확정하며 쓰는 문구 (09-30 결정, _llm_gave_up). 숫자를 넣지 않는다 (V7)
TABLE_FALLBACK = "판정 표 기준으로 '{label}'입니다. 설명 문장은 만들지 못했습니다. 아래 근거를 확인해 주세요."
VERDICT_LABEL = {"fine": "괜찮음", "watch": "지켜볼 것", "act": "지금 조치"}

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

# _identify가 "선박 검색 도구가 실패했다"를 알릴 때 쓰는 라우터 안의 표시. 응답의 vessel_match로는 나가지 않는다
TOOL_FAILED = "tool_failed"
FOLLOW_UP_FAILED = "질문에 답하지 못했습니다. 잠시 뒤 다시 물어봐 주세요."
# 질문이 역할 재설정·지시 무시 모양이면 LLM을 부르지 않고 이 문구로 답한다 (services/guard.py, SDD 7절 10-01)
FOLLOW_UP_BLOCKED = "이 화물의 조회 결과에 대한 질문에만 답할 수 있습니다. 예: 여유가 며칠인가요? 지금 통관 단계는 무엇인가요?"
# 후속 답에 거는 검증 규칙. answer 문장을 보는 것은 V1(오래된 위치를 현재 위치라 하지 않기),
# V7(근거에 없는 숫자 금지), V11(통관 진행 평가 금지)이다. 나머지는 판정·근거 칸을 보는데, 후속 질문은 그 칸을 바꾸지 않는다 (services/validate.py)
# 여기에 후속 답 전용 V9(근거에 없는 영문 낱말 금지, validate.check_follow_up_words)와 V10(질문 낱말 옮기기 금지)을 더 건다 (10-01)
FOLLOW_UP_RULES = {"V1", "V7", "V11"}  # V11: 후속 답에도 통관 진행 평가를 쓰지 않는다 (10-01)


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


@router.post("/agent", response_model=AgentResponse)
def run_agent(request: AgentRequest,
              user_id: Annotated[str | None, Depends(current_user_id)] = None) -> AgentResponse:
    """B/L과 판매 예정일을 받아 화물 상태를 정리해 돌려준다. 후속 질문이 오면 지난 결과를 보고 답한다.
    어느 쪽이든 결과를 조회 이력(query_log)에 남긴다.
    이 요청에서 부르는 LLM 트레이스에는 session_id가 붙는다 (SDD 5.11). 키가 없으면 아무 일도 안 한다.

    user_id: 출입증에서 꺼낸 사용자 ID (G3, auth.py). 로그인은 필수라 로그인 기능이 꺼진 채점 환경에서만 None. 판정 자체는 똑같고
    이력을 누구 것으로 남기고 후속 질문이 누구 결과를 꺼내는지만 달라진다.
    평가 실행기·데모처럼 코드에서 직접 부르면 None이다."""
    with session_scope(request.session_id, user_id):
        if request.follow_up_question:
            return _logged(request, _follow_up(request, user_id), user_id)
        return _logged(request, _assess(request), user_id)


def _assess(request: AgentRequest) -> AgentResponse:
    """조회와 판정 (SDD 4.1 1~7단계). 이력은 run_agent가 남긴다.
    progress.step()은 실제로 그 단계에 들어갈 때 화면에 알리는 한 줄이다. 듣는 쪽이 없으면 아무 일도 안 한다 (docs/specs/chat-progress.md)."""
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
    # 배를 못 정하면 판정하지 않는다. 위치·입항 정보 없이 판정하면 근거 없이 "괜찮다"가 나온다 (09-28 실제 B/L)
    if vessel_match == TOOL_FAILED:
        # 검색 도구 실패는 우리 쪽 문제라 사용자에게 되묻지 않는다 (SDD 4.1 4단계·8절)
        return _response(status="partial", answer=VESSEL_TOOL_FAILED)
    if vessel_match == "none":
        # 0척 → insufficient (SDD 4.1 3단계). 포워더 입항 예정일을 이미 받았으면 더 물을 게 없어 partial (V5)
        if request.forwarder_eta:
            return _response(status="partial", answer=NO_VESSEL_AFTER_ETA)
        return _response(status="insufficient", missing_inputs=["forwarder_eta"], answer=NO_VESSEL)
    if vessel_match == "uncertain":
        return _response(
            status="insufficient",
            vessel_match="uncertain",
            vessel_candidates=candidates,
            missing_inputs=[f for f in ("voyage_no", "forwarder_eta") if not getattr(request, f)],
            answer=ASK_BACK,
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
    progress.step("judge")
    feedback = None
    for attempt in range(1, JUDGE_ATTEMPTS + 1):
        try:
            judged = llm.judge(signal_set, customs, margin, feedback=feedback,
                               trusted_eta=trusted, sale_due_date=request.sale_due_date,
                               table_verdict=table, verdict_mode="raise_only" if gray else "fixed")
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
                violations = validate.check(response)
                # V9·V10 판정판 (10-01): 통관 단계명(외부 데이터)에 넣은 주입이 설명 칸에 섞이지 않게 한다 (validate.py)
                texts = [out.answer, *out.actions, *[c.why for c in out.conflicts]]
                if out.customs:
                    texts += [out.customs.plain_explanation, out.customs.next_stage or ""]
                external = " ".join([customs.stage_name or "", *[s.name for s in customs.stage_history]]) if customs else ""
                violations += validate.check_judge_text(texts, response, external,
                                                         llm.skills_reference(llm.JUDGE_SKILLS, llm.JUDGE_PROMPT))
                if not violations:
                    return response
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
    return _response(status="partial", answer=POSITION_TOOL_FAILED, **collected)


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
        ),
        berth=BerthInfo(facility=None, shed=customs.shed_name),
        evidence=build_evidence(customs, None, None, None, None, None),
    )


def _follow_up(request: AgentRequest, user_id: str | None = None) -> AgentResponse:
    """후속 질문 (C-9). 같은 세션·같은 B/L의 가장 최근 결과를 DB에서 꺼내 그 안에서만 답한다.

    세션별로 지난 결과를 저장해 두는 방식이다 (09-27 결정). 로그인했으면 세션 대신 사용자 ID로 찾는다 (G3).
    폰에서 조회하고 노트북에서 물어도 이어진다.
    DB가 없거나 지난 결과가 없으면 조회·판정을 한 번 더 해서 그 결과로 답한다 (채점 환경은 DB 없이 돌 수 있다).
    판정·근거는 지난 결과 그대로 두고 answer만 질문의 답으로 바꿔 돌려준다.
    """
    previous = _previous_response(request, user_id) or _assess(request)
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
    for attempt in range(1, JUDGE_ATTEMPTS + 1):
        try:
            out = llm.answer_follow_up(request.follow_up_question, previous, feedback=feedback).output
        except llm.LLMFormatError as e:
            log_failure("follow_up", f"{e.kind} attempt {attempt}")
            feedback = e.detail
            continue
        except llm.LLMError as e:
            log_failure("follow_up", _llm_error(e))
            return failed
        answered = previous.model_copy(update={"answer": out.answer, "trace_id": current_request_id()})
        # V11은 할 일·통관 칸도 보는데, 후속 답은 그 칸을 지난 결과에서 그대로 가져온다. 새로 쓴 answer만 보게 비우고 검사한다
        checked = answered.model_copy(update={"actions": [], "customs": None})
        violations = [v for v in validate.check(checked) if v.rule in FOLLOW_UP_RULES]
        # V9: 근거에 없는 영문 낱말 금지. 주입이 끼워 넣는 표식을 문장 모양과 상관없이 잡는다 (10-01, validate.py)
        violations += validate.check_follow_up_words(out.answer, previous, llm.skills_reference((), llm.FOLLOW_UP_PROMPT))
        # V10: 질문에만 있는 낱말을 답이 그대로 옮기면 위반. 한국어 표식 주입을 잡는다 (10-01, validate.py)
        violations += validate.check_follow_up_echo(out.answer, request.follow_up_question, previous,
                                                    llm.skills_reference(llm.FOLLOW_UP_SKILLS, llm.FOLLOW_UP_PROMPT))
        if not violations:
            return answered
        log_failure("validate_follow_up", f"{','.join(v.rule for v in violations)} attempt {attempt}")
        feedback = "\n".join(f"{v.rule}: {v.detail}" for v in violations)
    # 세 번 다 어기면 틀린 문장을 내보내지 않고 답하지 못했다고 한다. 지난 판정·근거는 그대로 둔다
    log_failure("follow_up", f"gave up after {JUDGE_ATTEMPTS} attempts")
    return failed


def _previous_response(request: AgentRequest, user_id: str | None = None) -> AgentResponse | None:
    """DB에 저장된 지난 결과. 없거나 DB에 못 붙으면 None (그러면 다시 조회한다)."""
    if not _db_configured("db_read"):
        return None
    try:
        with connect() as conn:
            saved = latest_response(conn, request.session_id, mask_bl(request.bl_no), user_id)
    except Exception as e:
        log_failure("db_read", type(e).__name__)
        return None
    return AgentResponse.model_validate(saved) if saved else None


def _fetch_customs(request: AgentRequest) -> tuple[CustomsRecord | None, AgentResponse | None]:
    """UNI-PASS 조회. 없는 B/L은 실패가 아니라 insufficient다 (SDD 4.1, 8절)."""
    try:
        record = UnipassClient().fetch(request.bl_no, request.bl_type)
    except CustomsError as e:
        log_failure("customs", e.code)
        return None, _response(status="failed", answer=f"통관 정보를 가져오지 못했습니다 ({e.code}).")
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
        # 사용자가 고른 배. 호출부호를 알면 해수부를 호출부호로 조회한다 (선명으로 훑으면 14초, 09-28 실측)
        return [], "confirmed", request.resolved_mmsi, mrn_call_sign

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
                # 후속 질문이 꺼내 쓸 결과 전체 (004 마이그레이션). B/L 원본은 AgentResponse에 없다
                response=_as_jsonb(response.model_dump(mode="json")),
            )
    except Exception as e:
        log_failure("db_write", type(e).__name__)
    return response
