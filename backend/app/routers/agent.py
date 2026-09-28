"""POST /api/agent (작업 A6, SDD 4.1).

요청을 받아 서비스 계층을 순서대로 부르고 AgentResponse를 돌려준다.
여기서 판정하지 않고, 외부 API를 직접 부르지도 않고, LLM SDK를 import하지도 않는다 (CLAUDE.md).

처리 순서는 SDD 4.1을 따른다.
  1. 입력 검증 (스키마 AgentRequest가 B/L 형식까지 본다, A7)
  2. UNI-PASS 조회 (코드가 직접 부른다. B/L을 LLM에 넘기지 않는다)
  2-1. 지원 범위 확인 (양륙항이 부산이 아니면 unsupported로 끝낸다)
  3. 선박 식별 (MRN 호출부호로 먼저, 안 되면 선명으로. 후보 1척이면 확정, 여럿이면 되묻기, 0척이면 여기서 멈추고 되묻기)
  4. 도구 호출 (위치·입항 일정·남은 거리)
  5. 1층 신호 판정 (코드)
  6. 2층 판정 (LLM, services/llm.judge)
  7. 출력 검증 7규칙 (services/validate.py). 위반이면 최대 3번까지 다시 묻고, 그래도 위반이면 failed

6단계는 services/llm.judge()가 한다 (C-6, 09-27 연결). 결과를 어떻게 응답에 담나:
  - LLM 호출이 실패하면 판정 없이 status=partial. 신호·위치·여유 일수는 그대로 준다 (09-23 결정)
  - 신호 7개가 전부 clear면 verdict=fine은 코드가 정한다(decided_by=rule). LLM 답은 문장만 쓴다 (SDD 4.1 7단계)
  - LLM이 판정을 보류(null)하면 status=insufficient, 포워더 입항 예정일을 묻는다 (skills/ais-reliability 되묻기 조건)
근거 카드는 services/evidence.build()가 만든다 (C-8).
"""
from datetime import datetime, timezone

from fastapi import APIRouter

from backend.app.db import connect, latest_response, log_query
from backend.app.observability.langfuse import session_scope
from backend.app.observability.logging import current_request_id
from backend.app.schemas.agent import (
    AgentRequest, AgentResponse, BerthInfo, CustomsInfo, EtaInfo, Position, VesselCandidate,
)
from backend.app.schemas.customs import CustomsRecord, mask_bl
from backend.app.services import identify, llm, validate
from backend.app.services import signals as signals_service
from backend.app.services.evidence import build as build_evidence, days_margin
from backend.app.services.customs import CustomsError, UnipassClient
from mcp_server.tools.distance import estimate_distance
from mcp_server.tools.live_position import get_live_position
from mcp_server.tools.port_schedule import get_port_schedule
from mcp_server.tools.vessel_candidates import get_vessel_candidates

router = APIRouter(prefix="/api", tags=["agent"])

NOT_JUDGED = "조회한 값을 정리했습니다. 판정은 아직 붙지 않았습니다."
NO_CARGO = "조회 결과가 없습니다. B/L 번호와 M/H 구분을 다시 확인해 주세요."
ASK_BACK = "같은 이름의 배가 여러 척입니다. 항차 번호나 포워더 ETA를 알려주시면 어느 배인지 가릅니다."
NO_VESSEL = "선박 위치 서비스에서 이 배를 찾지 못했습니다. 포워더 도착 통지서(A/N)의 입항 예정일을 알려주세요."
NO_VESSEL_AFTER_ETA = "선박 위치 서비스에서 이 배를 찾지 못해 판정하지 못했습니다. 입항 일정은 포워더에게 직접 확인해 주세요."
VESSEL_TOOL_FAILED = "선박 위치 서비스에 연결하지 못해 판정하지 못했습니다. 잠시 뒤 다시 조회해 주세요."
NOT_BUSAN = "부산항에 내리는 화물만 확인할 수 있습니다. 이 화물은 다른 항만으로 들어옵니다."
LLM_FAILED = "판정을 만들지 못했습니다. 조회한 값과 신호만 보여 드립니다."
VALIDATION_FAILED = "판정을 생성하지 못했습니다. 근거 카드를 확인하세요."  # SDD 5.7 3차 폴백 문구

JUDGE_ATTEMPTS = 3  # 판정 LLM 호출 최대 횟수: 처음 + 위반 내용 첨부 + 강화 (SDD 5.7)

# _identify가 "선박 검색 도구가 실패했다"를 알릴 때 쓰는 라우터 안의 표시. 응답의 vessel_match로는 나가지 않는다
TOOL_FAILED = "tool_failed"
FOLLOW_UP_FAILED = "질문에 답하지 못했습니다. 잠시 뒤 다시 물어봐 주세요."


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
def run_agent(request: AgentRequest) -> AgentResponse:
    """B/L과 판매 예정일을 받아 화물 상태를 정리해 돌려준다. 후속 질문이 오면 지난 결과를 보고 답한다.
    어느 쪽이든 결과를 조회 이력(query_log)에 남긴다.
    이 요청에서 부르는 LLM 트레이스에는 session_id가 붙는다 (SDD 5.11). 키가 없으면 아무 일도 안 한다."""
    with session_scope(request.session_id):
        if request.follow_up_question:
            return _logged(request, _follow_up(request))
        return _logged(request, _assess(request))


def _assess(request: AgentRequest) -> AgentResponse:
    """조회와 판정 (SDD 4.1 1~7단계). 이력은 run_agent가 남긴다."""
    customs, failure = _fetch_customs(request)
    if failure is not None:
        return failure

    # 지원 범위는 부산항이다 (PRD 4절). 양륙항이 부산이 아니면 배를 찾지 않고 끝낸다 (평가셋 F05).
    # 양륙항 칸이 비어 있으면 범위 밖으로 단정하지 않고 진행한다. 모르는 것을 거절하는 쪽이 더 나쁘다
    if customs.discharge_port and customs.discharge_port != signals_service.BUSAN_PORT_CODE:
        return _response(status="unsupported", answer=NOT_BUSAN)

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

    position = get_live_position(mmsi) if mmsi else None
    schedule = get_port_schedule(call_sign=call_sign, ship_name=customs.ship_name)
    distance = _distance(position)

    # 5. 1층 신호와 여유 일수는 코드가 계산한다 (SDD 4.1 5·6단계). LLM은 이 값을 바꾸지 않는다
    signal_set = signals_service.compute(position, schedule, distance, customs, request.sale_due_date)
    trusted = signals_service.trusted_eta(position, schedule)
    margin = days_margin(trusted, request.sale_due_date)

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
        evidence=build_evidence(customs, position, schedule, distance, trusted, margin, signals=signal_set),
    )

    # 6·7. 2층 판정 (LLM)과 출력 검증 (C-7, SDD 5.7)
    # 위반이면 위반 내용을 붙여 다시 묻는다. 두 번째 재시도는 "JSON만, 규칙 준수"를 덧붙인다.
    # 세 번 모두 위반이면 판정 없이 failed로 끝내고 근거 카드는 남긴다
    feedback = None
    for attempt in range(1, JUDGE_ATTEMPTS + 1):
        try:
            judged = llm.judge(signal_set, customs, margin, feedback=feedback)
        except llm.LLMError:
            return _response(status="partial", answer=LLM_FAILED, **collected)
        response = _judged(judged.output, signal_set, request, customs, collected)
        violations = validate.check(response)
        if not violations:
            return response
        feedback = "\n".join(f"{v.rule}: {v.detail}" for v in violations)
        if attempt == JUDGE_ATTEMPTS - 1:
            feedback += "\nReturn JSON only and follow every rule above."
    return _response(status="failed", answer=VALIDATION_FAILED, **collected)


def _judged(out, signal_set, request: AgentRequest, customs: CustomsRecord, collected: dict) -> AgentResponse:
    """LLM 판정 1회분을 응답으로 옮긴다. 검증(validate.check)은 부르는 쪽이 한다."""
    # 신호가 전부 clear면 판정은 규칙으로 fine. LLM 답에서는 문장·통관 해설만 쓴다 (SDD 4.1 7단계)
    if all(s.state == "clear" for s in signal_set.signals):
        verdict, decided_by = "fine", "rule"
    else:
        verdict, decided_by = out.verdict, "llm"

    # LLM이 판정을 보류하면 되묻는다 (skills/ais-reliability 되묻기 조건: 위치가 없으면 포워더 입항 예정일)
    # 이미 포워더 입항 예정일을 받았는데도 보류면 더 물을 게 없어 partial로 둔다 (V5: insufficient면 물을 것 1개 이상)
    status, missing = "ok", []
    if verdict is None:
        status, missing = ("partial", []) if request.forwarder_eta else ("insufficient", ["forwarder_eta"])

    return _response(
        status=status,
        verdict=verdict,
        decided_by=decided_by,
        missing_inputs=missing,
        reasons=out.reasons,
        conflicts=out.conflicts,
        actions=out.actions,
        answer=out.answer,
        customs=_customs_info(customs, out.customs),
        **collected,
    )


def _follow_up(request: AgentRequest) -> AgentResponse:
    """후속 질문 (C-9). 같은 세션·같은 B/L의 가장 최근 결과를 DB에서 꺼내 그 안에서만 답한다.

    세션별로 지난 결과를 저장해 두는 방식이다 (09-27 결정). 로그인이 붙으면 session_id 자리가 사용자 ID가 된다.
    DB가 없거나 지난 결과가 없으면 조회·판정을 한 번 더 해서 그 결과로 답한다 (채점 환경은 DB 없이 돌 수 있다).
    판정·근거는 지난 결과 그대로 두고 answer만 질문의 답으로 바꿔 돌려준다.
    """
    previous = _previous_response(request) or _assess(request)
    try:
        out = llm.answer_follow_up(request.follow_up_question, previous).output
    except llm.LLMError:
        return previous.model_copy(update={"answer": FOLLOW_UP_FAILED, "trace_id": current_request_id()})
    return previous.model_copy(update={"answer": out.answer, "trace_id": current_request_id()})


def _previous_response(request: AgentRequest) -> AgentResponse | None:
    """DB에 저장된 지난 결과. 없거나 DB에 못 붙으면 None (그러면 다시 조회한다)."""
    try:
        with connect() as conn:
            saved = latest_response(conn, request.session_id, mask_bl(request.bl_no))
    except Exception:
        return None
    return AgentResponse.model_validate(saved) if saved else None


def _fetch_customs(request: AgentRequest) -> tuple[CustomsRecord | None, AgentResponse | None]:
    """UNI-PASS 조회. 없는 B/L은 실패가 아니라 insufficient다 (SDD 4.1, 8절)."""
    try:
        record = UnipassClient().fetch(request.bl_no, request.bl_type)
    except CustomsError as e:
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
        if "error" not in result:
            found = _candidates(result.get("candidates", []), "MRN 입항 신고의 호출부호 일치")
            if len(found) == 1:
                return found, "confirmed", found[0].mmsi, mrn_call_sign
        # 실패·0척·여럿이면 아래 이름 검색으로 넘어간다

    if not customs.ship_name:
        return [], "none", None, None

    result = get_vessel_candidates(ship_name=customs.ship_name, nationality=customs.ship_nat)
    if "error" in result:
        return [], TOOL_FAILED, None, None
    rows = result.get("candidates", [])
    candidates = _candidates(rows)
    if not candidates:
        return [], "none", None, None
    if len(candidates) == 1:
        only = rows[0]
        return candidates, "confirmed", candidates[0].mmsi, only.get("call_sign")

    # 여럿이면 LLM이 고른다. 사용자가 되묻기에 답한 항차·포워더 입항 예정일도 같이 넘긴다
    try:
        picked = llm.pick_vessel(candidates, customs, request.voyage_no, request.forwarder_eta).output
    except llm.LLMError:
        return candidates, "uncertain", None, None
    # 후보에 없는 MMSI는 확정하지 않는다. 후보 목적지 문자열 속 지시문에 속았거나 번호를 지어냈을 수 있다 (C-10)
    if picked.confidence == "high" and picked.choice in {c.mmsi for c in candidates}:
        call_sign = next((row.get("call_sign") for row in rows if row["mmsi"] == picked.choice), None)
        return candidates, "confirmed", picked.choice, call_sign
    return candidates, "uncertain", None, None


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


def _customs_info(customs: CustomsRecord, explained) -> CustomsInfo | None:
    """단계 이름·코드·이력은 UNI-PASS 값(코드), 해설 셋은 LLM 값으로 C1 CustomsInfo를 만든다.
    단계 이름이 없거나 LLM이 해설을 안 냈으면 None."""
    if not customs.stage_name or explained is None:
        return None
    return CustomsInfo(
        stage_code=customs.stage_code or "",
        stage_name=customs.stage_name,
        plain_explanation=explained.plain_explanation,
        next_stage=explained.next_stage,
        needs_broker=explained.needs_broker,
        history=[s.model_dump(mode="json") for s in customs.stage_history],
    )


def _as_jsonb(data: dict):
    """psycopg가 dict를 jsonb로 넣게 감싼다. psycopg는 DB를 쓸 때만 import한다 (db/__init__.py와 같은 이유)."""
    from psycopg.types.json import Jsonb

    return Jsonb(data)


def _logged(request: AgentRequest, response: AgentResponse) -> AgentResponse:
    """조회 이력 한 줄을 남기고 응답을 그대로 돌려준다 (A12).

    이력 저장이 실패해도 응답은 나가야 한다. DB 없이도 서비스가 돌아야 하기 때문이다.
    """
    try:
        with connect() as conn:
            log_query(
                conn,
                request.session_id,
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
    except Exception:
        pass
    return response
