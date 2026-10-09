"""판정 흐름의 AgentResponse 조립 함수: LLM 판정 옮기기, LLM 실패 폴백, 위치·도착일 없음 보류, 반출 완료, 후보·선박·위치·ETA 칸 (routers/agent.py에서 옮김, SDD 4.1, 5.7). 호출 순서는 라우터가 정한다."""

import json
from datetime import timezone, datetime
from backend.app.observability.logging import current_request_id
from backend.app.schemas.agent import (
    AgentResponse,
    CustomsInfo,
    AgentRequest,
    BerthInfo,
    VesselCandidate,
    VesselInfo,
    Position,
    EtaInfo,
    Evidence,
)
from backend.app.schemas.customs import CustomsRecord
from backend.app.services.chat import referrals
from backend.app.services.judge import verdict as verdict_table
from backend.app.services.judge import signals as signals_service
from backend.app.services.judge.evidence import KST, build as build_evidence
from backend.app.services.judge.rules import is_listed_stage
from backend.app.clients import shipfinder as shipfinder_client
from backend.app.services.judge.answers import (
    LLM_FAILED,
    NOT_JUDGED,
    NO_ETA,
    NO_ETA_WITH_ESTIMATE,
    POSITION_MISSING,
    POSITION_MISSING_AFTER_ETA,
    POSITION_TOOL_FAILED,
    QUOTA_EXHAUSTED_TAIL,
    RELEASED,
    RELEASED_ACTIONS,
    RELEASED_EXPLANATION,
    RELEASED_STAGE,
    TABLE_FALLBACK,
    TOOL_SOURCE,
    UNLISTED_STAGE_EXPLANATION,
    VERDICT_LABEL,
)

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

def is_released(response: AgentResponse) -> bool:
    """반출이 끝난 화물의 응답인가. 화물 표에서 끝난 화물(done)로 옮기는 기준이다 (docs/specs/memory.md, RELEASED_STAGE)."""
    return bool(response.customs and response.customs.stage_name == RELEASED_STAGE)

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
    """판정 LLM이 끝내 실패했을 때의 응답. status는 늘 partial이다. 설명 문장을 못 만들었기 때문이다.

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
        actions=referrals.signal_lines(signal_set),  # 설명은 못 만들었어도 신호별 확인처는 코드가 붙인다
        answer=TABLE_FALLBACK.format(label=VERDICT_LABEL[table]),
        customs=_customs_info(customs, None),
        **collected,
    )

def _no_position(position: dict | None, request: AgentRequest, collected: dict) -> AgentResponse:
    """쓸 위치가 없을 때 LLM 없이 보류 응답을 만든다. 조회한 값(해수부 예정·근거 카드)은 참고로 둔다.

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
    """도구 실패 문구. ShipFinder 하루 한도를 다 쓴 날이면 "잠시 뒤 다시"를 "내일 다시"로 바꾼다.
    도구 응답의 오류 코드가 quota_exhausted이거나, 같은 프로세스가 오늘 38을 받았으면 한도 소진으로 본다."""
    if error_code == "quota_exhausted" or shipfinder_client.quota_blocked():
        return base.replace(" 잠시 뒤 다시 조회해 주세요.", "") + QUOTA_EXHAUSTED_TAIL
    return base

def _no_eta(signal_set, collected: dict) -> AgentResponse:
    """판매일은 있는데 믿을 도착일이 없어 여유 일수를 못 셀 때. LLM 없이 보류한다.

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
    """반출이 끝난 화물의 응답. 판정은 규칙으로 fine이고 LLM은 부르지 않는다.

    반출 뒤에는 기다릴 입항도 통관도 없어서 "지금 신경 써야 하나?"의 답은 순항이다.
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
            **customs.party_fields(),  # 포워더·선사·컨테이너·품명
        ),
        berth=BerthInfo(facility=None, shed=customs.shed_name),
        evidence=build_evidence(customs, None, None, None, None, None),
    )

def _evidence_text(response: AgentResponse) -> str:
    """근거 카드 값을 한 글로. V12가 원래 근거에 있는 같은 글자(예: 항차 이름 C12)를 번호 새어 나옴으로 보지 않게 한다."""
    return " ".join(f"{e.field} {e.value}" for e in response.evidence)

def _without_dest(value):
    """도구 결과에서 AIS 목적지 원문(dest)을 뺀다. 아무 배나 쓸 수 있는 글자라 주입 문장이 들어올 수 있다.
    판정·후속 질문 LLM 입력에서 빼는 것과 같은 기준이다 (SDD 7절, llm.answer_follow_up)."""
    if isinstance(value, dict):
        return {k: _without_dest(v) for k, v in value.items() if k != "dest"}
    if isinstance(value, list):
        return [_without_dest(v) for v in value]
    return value

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

    예전에는 확정 경로에서 이 칸을 한 번도 채우지 않아 늘 null이었다(mrn_fallback만 채웠다).
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
    평가 실행기(evals/judge.py)가 이 단계들은 LLM 해설 채점에서 뺀다. 코드가 쓴 고정 문장이라 LLM 품질이 아니다."""
    if not stage_name:
        return False
    return stage_name == RELEASED_STAGE or not is_listed_stage(stage_name)

def _customs_info(customs: CustomsRecord, explained) -> CustomsInfo | None:
    """단계 이름·코드·이력은 UNI-PASS 값, 관세사 필요 여부는 코드 판단, 해설 둘은 LLM 값으로 C1 CustomsInfo를 만든다.

    목록에 없는 단계는 해설 둘도 코드가 쓴다: 고정 문장 + 다음 단계 null (UNLISTED_STAGE_EXPLANATION).
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
        **customs.route_fields(),  # 어디서 어디로
        **customs.party_fields(),  # 포워더·선사·컨테이너·품명
    )
