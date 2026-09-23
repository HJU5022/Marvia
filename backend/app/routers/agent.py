"""POST /api/agent (작업 A6, SDD 4.1).

요청을 받아 서비스 계층을 순서대로 부르고 AgentResponse를 돌려준다.
여기서 판정하지 않고, 외부 API를 직접 부르지도 않고, LLM SDK를 import하지도 않는다 (CLAUDE.md).

처리 순서는 SDD 4.1을 따른다.
  1. 입력 검증 (스키마 AgentRequest가 B/L 형식까지 본다, A7)
  2. UNI-PASS 조회 (코드가 직접 부른다. B/L을 LLM에 넘기지 않는다)
  3. 선박 식별 (후보 1척이면 확정, 여럿이면 되묻기)
  4. 도구 호출 (위치·입항 일정·남은 거리)
  5. 1층 신호 판정 (코드)
  6. 2층 판정 (LLM)      <- C-6 services/llm.py가 들어올 자리
  7. 출력 검증 7규칙      <- C-7이 들어올 자리

지금은 6·7이 없어서 판정 없이 status=partial로 돌려준다. 수집까지는 실제로 동작하므로
프론트(E 묶음)가 화면을 붙일 수 있고, C가 끝나면 이 파일의 TODO 자리만 채우면 된다.
"""
from datetime import datetime, timezone

from fastapi import APIRouter

from backend.app.db import connect, log_query
from backend.app.observability.logging import current_request_id
from backend.app.schemas.agent import AgentRequest, AgentResponse, Position, VesselCandidate
from backend.app.schemas.customs import CustomsRecord, mask_bl
from backend.app.services import signals as signals_service
from backend.app.services.customs import CustomsError, UnipassClient
from mcp_server.tools.distance import estimate_distance
from mcp_server.tools.live_position import get_live_position
from mcp_server.tools.port_schedule import get_port_schedule
from mcp_server.tools.vessel_candidates import get_vessel_candidates

router = APIRouter(prefix="/api", tags=["agent"])

NOT_JUDGED = "조회한 값을 정리했습니다. 판정은 아직 붙지 않았습니다."
NO_CARGO = "조회 결과가 없습니다. B/L 번호와 M/H 구분을 다시 확인해 주세요."
ASK_BACK = "같은 이름의 배가 여러 척입니다. 항차 번호나 포워더 ETA를 알려주시면 어느 배인지 가릅니다."


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
    """B/L과 판매 예정일을 받아 화물 상태를 정리해 돌려준다."""
    customs, failure = _fetch_customs(request)
    if failure is not None:
        return _logged(request, failure)

    candidates, vessel_match, mmsi, call_sign = _identify(customs, request)
    if vessel_match == "uncertain":
        return _logged(
            request,
            _response(
                status="insufficient",
                vessel_match="uncertain",
                vessel_candidates=candidates,
                missing_inputs=[f for f in ("voyage_no", "forwarder_eta") if not getattr(request, f)],
                answer=ASK_BACK,
            ),
        )

    position = get_live_position(mmsi) if mmsi else None
    schedule = get_port_schedule(call_sign=call_sign, ship_name=customs.ship_name)
    distance = _distance(position)

    # 1층 신호는 코드가 판정한다. 결과는 C-6가 2층 판정에 쓴다 (지금은 응답에 담지 않는다)
    signals_service.compute(position, schedule, distance, customs, request.sale_due_date)

    # TODO(C-6): llm.judge()로 verdict·reasons·actions·answer를 받는다
    # TODO(C-7): validate.run()으로 7규칙을 걸고 위반이면 재시도한다
    # TODO(C-8): evidence.summarize()로 days_margin과 근거 카드를 채운다
    return _logged(
        request,
        _response(
            status="partial",
            vessel_match=vessel_match,
            vessel_candidates=candidates,
            position=_position(position),
        ),
    )


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
    """후보 1척이면 확정, 여럿이면 되묻기. 사용자가 고른 MMSI가 있으면 그것을 쓴다.

    여럿일 때 LLM이 고르는 단계(C-5)는 아직 없다. 그전까지는 확정하지 않고 되묻는다.
    확정하지 않는 쪽이 남의 배를 내 배라고 답하는 것보다 낫다 (PRD 6.2).

    호출부호도 같이 돌려준다. C1 VesselCandidate에는 자리가 없지만 해수부 조회에 필요하다.
    """
    if request.resolved_mmsi:
        return [], "confirmed", request.resolved_mmsi, None
    if not customs.ship_name:
        return [], "none", None, None

    result = get_vessel_candidates(ship_name=customs.ship_name, nationality=customs.ship_nat)
    rows = result.get("candidates", []) if "error" not in result else []
    candidates = [
        VesselCandidate(
            mmsi=row["mmsi"],
            imo=row.get("imo"),
            name=row["name"],
            flag=row.get("flag"),
            dest=row.get("dest"),
            last_time=row["last_time"],
            ship_type=row.get("ship_type"),
            match_reasons=[f"선명 유사도 {row.get('similarity')}"],
        )
        for row in rows
        if row.get("last_time")
    ]
    if not candidates:
        return [], "none", None, None
    if len(candidates) == 1:
        only = rows[0]
        return candidates, "confirmed", candidates[0].mmsi, only.get("call_sign")
    return candidates, "uncertain", None, None


def _distance(position: dict | None) -> dict | None:
    if not position or "error" in position:
        return None
    return estimate_distance(position["lat"], position["lng"], position.get("sog"))


def _position(position: dict | None) -> Position | None:
    """도구 출력을 C1 Position으로 옮긴다. freshness는 signals가 정하므로 여기선 unknown."""
    if not position or "error" in position:
        return None
    return Position(
        lat=position["lat"],
        lng=position["lng"],
        sog=position.get("sog") or 0.0,
        cog=position.get("cog") or 0.0,
        navistat=position.get("navistat") or 0,
        last_time=position.get("last_time") or datetime.now(timezone.utc),
        freshness="unknown",
    )


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
            )
    except Exception:
        pass
    return response
