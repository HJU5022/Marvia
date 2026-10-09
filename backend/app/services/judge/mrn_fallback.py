"""세관(UNI-PASS)에 아직 없는 화물은 MRN으로 배 상태까지 보여 준다 (docs/specs/mrn-fallback.md).

routers/agent.py의 조회가 UNI-PASS에서 B/L을 못 찾았고(insufficient) 요청에 MRN이 있을 때만 부른다.
- 해수부 입항 신고에서 MRN으로 배(선명·호출부호·입항 예정·접안 시설)를 찾는다
- 호출부호로 ShipFinder 후보 → AIS 위치 → 부산까지 남은 거리 (기존 MCP 도구)
- status=partial, verdict=None. 통관 정보가 없어서 판정하지 않는다. trusted_eta도 정하지 않는다
해수부에서도 못 찾으면 None (부르는 쪽은 원래 응답을 그대로 돌려준다, EC-02).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from backend.app.clients.mof import MofClient, MofError
from backend.app.observability.logging import current_request_id, log_failure
from backend.app.schemas.agent import (
    AgentRequest, AgentResponse, BerthInfo, EtaInfo, Evidence, Position, VesselInfo,
)
from backend.app.services.watch.vessel_detail import _freshness
# MCP 도구는 /mcp를 거쳐 부른다 (services/mcp_client.py)
from backend.app.services.mcp_client import estimate_distance, get_live_position, get_vessel_candidates

LOOKBACK_DAYS, LOOKAHEAD_DAYS = 3, 14  # 입항 신고를 찾는 기간. 통지서는 보통 입항 며칠 전에 온다

NO_CUSTOMS_YET = ("통관 정보는 아직 세관(UNI-PASS)에 없습니다. 보통 적하목록이 올라오는 입항 전후에 조회됩니다. "
                  "대신 MRN으로 해수부 입항 신고에서 배를 찾았습니다.")


def _iso(t) -> str | None:
    return t.isoformat() if isinstance(t, datetime) else (str(t) if t else None)


def assess(request: AgentRequest) -> AgentResponse | None:
    """MRN 대체 응답. 해수부에 없으면 None."""
    if not request.mrn:
        return None
    today = date.today()
    client = MofClient()
    try:
        plans = client.sailing_plans_all(today - timedelta(days=LOOKBACK_DAYS), today + timedelta(days=LOOKAHEAD_DAYS))
    except MofError as e:
        log_failure("mrn_fallback_mof", e.code)
        return None
    finally:
        client.close()
    plan = next((p for p in plans if p.mrn and p.mrn.upper() == request.mrn), None)
    if plan is None:
        return None

    now = datetime.now(timezone.utc)
    evidence = [Evidence(source="mof", field="mrn_plan", value=f"{plan.ship_name} / {plan.call_sign or '-'}", fetched_at=now)]
    if plan.expected_arrival:
        evidence.append(Evidence(source="mof", field="planned_arrival", value=_iso(plan.expected_arrival), fetched_at=now))
    if plan.facility:
        evidence.append(Evidence(source="mof", field="facility", value=plan.facility, fetched_at=now))

    vessel = position = None
    ais_eta = calc_eta = distance_nm = None
    found = get_vessel_candidates(ship_name=plan.ship_name or "", call_sign=plan.call_sign)
    cands = [] if "error" in found else (found.get("candidates") or [])
    if cands:
        c = cands[0]
        vessel = VesselInfo(mmsi=c["mmsi"], imo=c.get("imo"), name=c.get("name") or plan.ship_name,
                            call_sign=plan.call_sign, flag=c.get("flag") or plan.nationality, ship_type=c.get("ship_type"),
                            voyage_no=None)
        pos = get_live_position(c["mmsi"])
        if "error" not in pos:
            position = Position(lat=pos["lat"], lng=pos["lng"], sog=pos.get("sog") or 0.0, cog=pos.get("cog") or 0.0,
                                navistat=pos.get("navistat") or 0, last_time=pos.get("last_time") or now,
                                freshness=_freshness(pos.get("last_time")))
            ais_eta = pos.get("ais_eta")
            evidence.append(Evidence(source="shipfinder", field="position", value=f"{pos['lat']}, {pos['lng']}",
                                     fetched_at=pos.get("fetched_at") or now))
            dist = estimate_distance(pos["lat"], pos["lng"], pos.get("sog"))
            if "error" not in dist:
                distance_nm = dist["distance_nm"]
                if dist.get("calc_hours_at_sog") is not None:
                    calc_eta = now + timedelta(hours=dist["calc_hours_at_sog"])
                evidence.append(Evidence(source="searoute", field="distance_nm", value=str(distance_nm), fetched_at=now))
        else:
            log_failure("mrn_fallback_position", pos["error"].get("code"))  # EC-03: 해수부 정보만으로 계속
    else:
        log_failure("mrn_fallback_vessel", (found.get("error") or {}).get("code", "not_found"))

    when = plan.expected_arrival.astimezone(timezone(timedelta(hours=9))).strftime("%m월 %d일 %H:%M") if plan.expected_arrival else "확인되지 않음"
    answer = (f"{NO_CUSTOMS_YET} {plan.ship_name}호가 {when} 부산 입항 예정이고 접안 예정지는 {plan.facility or '확인되지 않음'}입니다. "
              "통관 정보가 들어오면 판정까지 다시 볼 수 있습니다.")
    return AgentResponse(
        status="partial", verdict=None, vessel_match="confirmed" if vessel else "none", vessel_candidates=[],
        missing_inputs=[], reasons=[], conflicts=[], actions=["입항 전후에 같은 B/L로 다시 조회하세요"],
        days_margin=None, decided_by=None, vessel=vessel, position=position,
        eta=EtaInfo(ais_eta=ais_eta, mof_eta=plan.expected_arrival, calc_eta=calc_eta, trusted_eta=None, distance_nm=distance_nm),
        customs=None, berth=BerthInfo(facility=plan.facility, shed=None), evidence=evidence, answer=answer,
        trace_id=current_request_id(),
    )
