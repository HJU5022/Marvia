"""파이프라인. 0~8단계를 순서대로 부른다. 루프 없음. (SDD 5절 표가 기준)

이 파일이 하는 일은 "순서와 갈림길"뿐이다. 실제 계산은 domain/ 이, 바깥 호출은 같은 폴더의
vision·llm·geo·routes·judge·store 가 한다. 여기에 계산식이나 httpx 호출을 넣지 않는다 (BACKEND_GUIDE).

단계마다 Langfuse span 을 하나 남긴다. 어디서 끊겼는지 트레이스만 보고 알 수 있어야 한다 (필수 조건 4).

Deps 로 바깥 함수를 받는 이유:
  테스트가 키 없이 돌아야 한다 (TEST_GUIDE). 기본값은 진짜 서비스지만, 테스트는 가짜 함수를 넣어
  단계 순서와 갈림길만 검사한다.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from backend.app.domain import router as model_router
from backend.app.domain import rules as domain_rules
from backend.app.observability import langfuse
from backend.app.schemas.request import AgentRequest
from backend.app.schemas.result import AgentResponse, Candidate, GeocodedPin, ParticipantResult, Result
from backend.app.schemas.slots import Participant, Slots

# 확신도가 이보다 낮은 핀이 하나라도 있으면 사용자에게 확인을 받는다 (SDD 5절 2단계)
GEOCODE_CONFIRM_BELOW = 0.8


class NotYourPin(Exception):
    """남의 핀을 고치려 했다. 라우터가 403 으로 바꾼다 (SDD 5절 2-1, 7절 핀 소유권)."""


class NotYourSession(Exception):
    """남의 세션으로 재질문했다. 라우터가 403 으로 바꾼다 (SDD 5절 재질문)."""


class SessionLocked(Exception):
    """약속이 지나 잠긴 세션이다. 라우터가 409 로 바꾼다 (SDD 5절 재질문). LLM 을 부르기 전에 막는다."""


@dataclass
class Deps:
    """단계가 부르는 바깥 함수들. 이름과 순서는 SDD 5절 표와 같다."""

    extract_text: Callable[[str], Awaitable[str]] | None = None  # 0 vision
    extract_slots: Callable[..., Awaitable[Slots]] | None = None  # 1 llm
    geocode_all: Callable[..., Awaitable[list[GeocodedPin]]] | None = None  # 2 geo
    build_candidates: Callable[..., Awaitable[Any]] | None = None  # 3 geo
    compute_routes: Callable[..., Awaitable[Any]] | None = None  # 4 routes
    apply_rules: Callable[..., Any] | None = None  # 5 domain/rules
    rank: Callable[..., Awaitable[Any]] | None = None  # 6 judge (없으면 규칙 점수 순)
    departure: Callable[..., Any] | None = None  # 7 domain/rules
    save: Callable[..., Awaitable[str]] | None = None  # 8 store
    load_session: Callable[..., Awaitable[Any]] | None = None  # 재질문: 이전 세션 읽기
    previous_slots: Slots | None = None  # 재질문이면 이전 슬롯 (SDD 5절 재질문)
    extras: dict[str, Any] = field(default_factory=dict)


def _answer(
    session_id: str,
    stage: str,
    slots: Slots | None,
    trace_id: str,
    message: str,
    questions: list[str] | None = None,
    geocoded: list[GeocodedPin] | None = None,
    result: Result | None = None,
) -> AgentResponse:
    return AgentResponse(
        session_id=session_id,
        stage=stage,  # type: ignore[arg-type]
        slots=slots,
        result=result,
        questions=questions or [],
        message=message,
        trace_id=trace_id,
        geocoded=geocoded,
    )


async def run(req: AgentRequest, user_id: str, deps: Deps | None = None) -> AgentResponse:
    """요청 하나를 끝까지 처리한다. 돌아오는 stage 가 화면을 정한다 (SDD 2절)."""
    deps = deps or Deps()
    # 세션 id 는 첫 요청에서 만든다. 8단계 저장이 붙으면 이 값으로 행을 만들고, 그 전에도
    # 재질문(이전 슬롯 유지)과 Langfuse session_id 가 이어지도록 해야 한다 (SDD 5절 재질문, 22번)
    session_id = req.session_id or uuid.uuid4().hex
    # 테스트가 넣지 않은 단계는 진짜 서비스로 채운다
    for stage_name in (
        "extract_slots",
        "geocode_all",
        "build_candidates",
        "compute_routes",
        "rank",
        "save",
        "load_session",
    ):
        if getattr(deps, stage_name) is None:
            setattr(deps, stage_name, _default(stage_name))

    is_new_session = req.session_id is None

    with langfuse.trace("agent", user_id=user_id, session_id=session_id, preset=req.preset) as tr:
        text = req.text or ""

        # 재질문이면 이전 슬롯을 읽어 1단계 프롬프트에 넣는다 (SDD 5절 재질문)
        if not is_new_session and deps.previous_slots is None:
            with tr.span("load_session") as span:
                try:
                    deps.previous_slots = await _load_previous(deps, session_id, user_id)
                    span.output = {"found": deps.previous_slots is not None}
                except (NotYourSession, SessionLocked):
                    raise
                except Exception as e:  # noqa: BLE001  저장소가 없어도 계산은 이어 간다
                    span.error = str(e)

        # 0. 캡처 → 텍스트. 실패하면 문장으로 다시 받는다
        if req.image_base64:
            with tr.span("vision") as span:
                try:
                    text = await _call(deps.extract_text, req.image_base64)
                    span.output = {"chars": len(text)}
                except Exception as e:  # noqa: BLE001
                    span.error = str(e)
                    return _answer(
                        session_id,
                        "need_info",
                        None,
                        tr.id,
                        "캡처를 읽지 못했습니다. 문장으로 입력해 주세요.",
                        questions=["어떤 작업을, 언제, 누가 어디서 출발해 모이나요?"],
                    )

        # 1. 텍스트 → 슬롯
        with tr.span("extract", text=text[:200]) as span:
            try:
                slots = await _call(deps.extract_slots, text, deps.previous_slots, req.preset)
                span.output = slots.model_dump(exclude={"participants"})
            except Exception as e:  # noqa: BLE001
                span.error = str(e)
                return _answer(session_id, "failed", None, tr.id, "요청을 이해하지 못했습니다. 다시 입력해 주세요.")

        # 1-1. 범위 밖
        if slots.out_of_scope:
            return _answer(
                session_id,
                "out_of_scope",
                slots,
                tr.id,
                "출발 후 실시간 상황은 다루지 않습니다. 출발 전 집결 계획만 잡습니다.",
            )

        # 1-2. 필수 슬롯 누락
        if slots.missing:
            return _answer(
                session_id,
                "need_info",
                slots,
                tr.id,
                "계산하려면 몇 가지가 더 필요합니다.",
                questions=_questions_for(slots.missing),
            )

        # 1-3. 기간 판정 (오늘+N일을 넘으면 되묻는다). N 은 skills/converge/rules/ 의 값이다.
        # TODO: rules 파일이 생기면 domain/rules.py 의 기간 검사를 여기에 붙인다 (SDD 5절 1-3)

        # 2. 지오코딩
        with tr.span("geocode") as span:
            try:
                pins = await _call(deps.geocode_all, slots)
                span.output = {"pins": len(pins)}
            except Exception as e:  # noqa: BLE001
                span.error = str(e)
                return _answer(session_id, "failed", slots, tr.id, "위치를 찾지 못했습니다. 지명을 다시 알려 주세요.")

        # 2-1. 확신도가 낮으면 핀 확인. 사용자가 고친 좌표는 confirmed_participants 로 다시 온다
        unsure = [p for p in pins if p.kind == "participant" and p.confidence < GEOCODE_CONFIRM_BELOW]
        if unsure and not req.confirmed_participants:
            return _answer(
                session_id,
                "need_confirm",
                slots,
                tr.id,
                "출발 위치가 맞나요? 핀을 끌어서 고친 뒤 계산을 누르세요.",
                geocoded=pins,
            )
        if req.confirmed_participants:
            # 주선자는 owner_user_id 가 없는 핀만, 참석자는 자기 핀만 고칠 수 있다 (SDD 7절)
            _check_ownership(slots, req.confirmed_participants, user_id)
            pins = _apply_confirmed(pins, req.confirmed_participants)

        # 3. 집결 후보
        with tr.span("candidates") as span:
            try:
                raw_candidates = await _call(deps.build_candidates, slots, pins)
                span.output = {"count": len(raw_candidates)}
            except Exception as e:  # noqa: BLE001
                span.error = str(e)
                return _answer(session_id, "failed", slots, tr.id, "집결 후보를 찾지 못했습니다.", geocoded=pins)

        # 4. 참석자 × 후보 경로
        with tr.span("routes") as span:
            plans = _route_plans(slots, pins, raw_candidates)
            try:
                routes = await _call(deps.compute_routes, plans)
            except Exception as e:  # noqa: BLE001
                span.error = str(e)
                routes = []
            failed_names = sorted({r["key"][1] for r in routes if r.get("error")})
            span.output = {"요청": len(plans), "실패": len([r for r in routes if r.get("error")]), "실패자": failed_names}

        # 6. 판정. 소형 경로(SDD 5절 라우팅 small)면 대형 모델을 부르지 않는다
        rankings: list[dict[str, Any]] | None = None
        routed_to = model_router.route(slots)
        if routed_to == "large":
            with tr.span("judge") as span:
                try:
                    rankings = await _call(
                        deps.rank, slots, _judge_candidates(raw_candidates, slots), _judge_rows(routes, slots)
                    )
                    span.output = {"rankings": rankings}
                except Exception as e:  # noqa: BLE001
                    # 판정이 실패해도 멈추지 않는다. 규칙 점수 순서로 대신 채운다 (SDD 5절 6단계)
                    span.error = str(e)
                    rankings = None

        # 5·7. 규칙 적용과 출발 시각 역산
        with tr.span("rules") as span:
            meet_at = domain_rules.parse_meet_time(slots.datetime)
            if meet_at is None:
                return _answer(
                    session_id,
                    "need_info",
                    slots,
                    tr.id,
                    "몇 시에 시작하는지 알려 주세요.",
                    questions=["몇 시에 시작하나요?"],
                    geocoded=pins,
                )
            result = _build_result(slots, raw_candidates, routes, meet_at, rankings, routed_to)
            span.output = {"후보": len(result.candidates), "참석자행": len(result.per_participant)}

        if not result.per_participant:
            return _answer(session_id, "failed", slots, tr.id, "경로를 구하지 못했습니다. 잠시 후 다시 시도해 주세요.", geocoded=pins)

        # 8. 저장
        with tr.span("store") as span:
            try:
                session_id = await _persist(
                    deps,
                    session_id=session_id,
                    is_new=is_new_session,
                    user_id=user_id,
                    slots=slots,
                    result=result,
                    trace_id=tr.id,
                    pins=pins,
                )
                span.output = {"session_id": session_id}
            except Exception as e:  # noqa: BLE001  저장이 실패해도 계산 결과는 보여 준다
                span.error = str(e)

        first = min((c.rank for c in result.candidates if c.rank), default=None)
        top = next((c for c in result.candidates if c.rank == first), None)
        arrive_by = result.per_participant[0].arrive_by
        # 경로를 못 구한 사람은 표에서 빠진다. 말없이 빼면 "왜 저 사람만 없지"가 되므로 알린다
        done_names = {r.name for r in result.per_participant}
        missing_people = [p.name for p in slots.participants if p.name not in done_names]
        return _answer(
            session_id,
            "done",
            slots,
            tr.id,
            (f"{top.name}에서 {arrive_by} 까지 모이는 안을 1순위로 제안합니다." if top else "결과를 정리했습니다.")
            + (f" {', '.join(missing_people)} 님은 경로를 조회하지 못해 표에서 빠졌습니다." if missing_people else ""),
            geocoded=pins,
            result=result,
        )


def _default(name: str) -> Callable[..., Any] | None:
    """Deps 에 안 넣은 단계는 진짜 서비스를 쓴다. import 는 부를 때 한다.

    지연 import 인 이유: 테스트가 가짜 함수만 넣고 돌 때 openai·httpx 를 건드리지 않게 하려는 것이다.
    아직 파일이 없는 단계(3~8)는 None 이라 _call 이 그 자리에서 실패한다.
    """
    if name == "extract_slots":
        from backend.app.services import llm

        return llm.extract_slots
    if name == "geocode_all":
        from backend.app.services import geo

        return geo.geocode_all
    if name == "build_candidates":
        from backend.app.services import geo

        return geo.build_candidates
    if name == "compute_routes":
        from backend.app.services import routes

        return routes.compute_all
    if name == "rank":
        from backend.app.services import judge

        return judge.rank
    if name in ("save", "load_session"):
        # DB 설정이 없으면 import 자체가 실패한다. 그때는 저장 없이 계산만 한다
        try:
            from backend.app.services import session_store
        except Exception:  # noqa: BLE001
            return None
        return session_store.save if name == "save" else session_store.load_session
    return None


async def _call(fn: Callable[..., Any] | None, *args: Any) -> Any:
    """아직 없는 단계를 부르면 그 자리에서 실패한다. 조용히 건너뛰지 않는다."""
    if fn is None:
        raise NotImplementedError("이 단계는 아직 구현 전입니다")
    out = fn(*args)
    if hasattr(out, "__await__"):
        return await out
    return out


def _questions_for(missing: list[str]) -> list[str]:
    """누락된 슬롯 경로를 사람 말 질문으로 바꾼다 (SDD 2절 need_info).

    문구를 코드에 두는 이유: 이건 프롬프트가 아니라 화면 문구다. LLM을 부르지 않는다.
    """
    questions: list[str] = []
    for path in missing:
        if path.endswith(".origin"):
            questions.append("어디서 출발하시나요?")
        elif path.endswith(".transport"):
            questions.append("차로 오시나요, 대중교통으로 오시나요?")
        elif path == "datetime":
            questions.append("몇 시에 시작하나요?")
        elif path == "access.applied":
            questions.append("출입조치(또는 방문 신청)는 해 두셨나요?")
        else:
            questions.append(f"{path} 를 알려 주세요.")
    # 같은 질문이 사람 수만큼 반복되지 않게 한 번씩만
    return list(dict.fromkeys(questions))


def _check_ownership(slots: Slots, confirmed: list[Any], user_id: str) -> None:
    """고치려는 핀마다 소유자를 본다. 소유자가 있고 그 사람이 아니면 NotYourPin.

    주선자가 만든 핀은 owner_user_id 가 None 이라 누구의 것도 아니고, 주선자가 고친다.
    참석자가 공유 링크에서 자기라고 고른 뒤에는 그 사람만 고칠 수 있다.
    """
    owners = {p.name: p.owner_user_id for p in slots.participants}
    for c in confirmed:
        owner = owners.get(c.name)
        if owner is not None and owner != user_id:
            raise NotYourPin(c.name)


def _apply_confirmed(pins: list[GeocodedPin], confirmed: list[Any]) -> list[GeocodedPin]:
    """사용자가 핀을 끌어 고친 좌표로 바꾼다. 고친 핀은 확신도 1.0 (SDD 5절 2-1)."""
    fixed = {c.name: c for c in confirmed}
    out: list[GeocodedPin] = []
    for pin in pins:
        hit = fixed.get(pin.name) if pin.kind == "participant" else None
        out.append(
            GeocodedPin(name=pin.name, lng=hit.lng, lat=hit.lat, confidence=1.0, kind=pin.kind) if hit else pin
        )
    return out


def _pin_of(pins: list[GeocodedPin], name: str, kind: str) -> GeocodedPin | None:
    return next((p for p in pins if p.kind == kind and p.name == name), None)


def _route_plans(slots: Slots, pins: list[GeocodedPin], candidates: list[Any]) -> list[dict[str, Any]]:
    """참석자 × 후보로 경로 요청 목록을 만든다 (SDD 5절 4단계).

    태워지는 사람은 탑승 지점부터 계산하고(transport.md pickup_counts_from_board),
    태워 주는 사람 경로에는 그 지점을 경유지로 넣는다.
    """
    riders = {p.pickup: p for p in slots.participants if p.pickup and p.pickup_at}
    plans: list[dict[str, Any]] = []

    for index, cand in enumerate(candidates):
        dest = (cand["lng"], cand["lat"])
        for person in slots.participants:
            origin_pin = _pin_of(pins, person.name, "participant")
            waypoint = None

            if person.pickup and person.pickup_at:  # 태워지는 사람
                board = _pin_of(pins, person.pickup_at, "pickup")
                if board is None:
                    continue
                origin: tuple[float, float] = (board.lng, board.lat)
            else:
                if origin_pin is None:
                    continue
                origin = (origin_pin.lng, origin_pin.lat)
                rider = riders.get(person.name)  # 이 사람이 누군가를 태우는가
                if rider and rider.pickup_at:
                    board = _pin_of(pins, rider.pickup_at, "pickup")
                    if board is not None:
                        waypoint = (board.lng, board.lat)

            plans.append(
                {
                    "key": (index, person.name),
                    "transport": person.transport or "car",
                    "origin": origin,
                    "dest": dest,
                    "waypoint": waypoint,
                }
            )
    return plans


def _llm_meta() -> dict[str, Any]:
    """마지막 슬롯 추출에 쓴 모델·프롬프트 버전. 결과에 남겨 무엇으로 돌았는지 보이게 한다."""
    try:
        from backend.app.services import llm

        return llm.last_meta()
    except Exception:  # noqa: BLE001  기록용이라 실패해도 계산을 막지 않는다
        return {}


def _judge_candidates(raw_candidates: list[dict[str, Any]], slots: Slots) -> list[dict[str, Any]]:
    """판정 프롬프트에 넣을 후보 목록. access_ok 는 코드가 정한 값을 그대로 알려 준다."""
    applied = slots.access.applied if slots.access else None
    return [
        {**cand, "access_ok": domain_rules.access_ok(cand["kind"], applied)} for cand in raw_candidates
    ]


def _judge_rows(routes: list[dict[str, Any]], slots: Slots) -> list[dict[str, Any]]:
    """판정 프롬프트에 넣을 참석자별 소요. 실패한 조회는 빼고 준다."""
    transport_of = {p.name: (p.transport or "car") for p in slots.participants}
    rows: list[dict[str, Any]] = []
    for route in routes:
        if route.get("error"):
            continue
        index, name = route["key"]
        rows.append(
            {
                "candidate_idx": index,
                "name": name,
                "transport": transport_of.get(name, "car"),
                "raw_duration_min": round(route["duration_sec"] / 60),
                "transfer_count": route.get("transfer_count"),
            }
        )
    return rows


def _build_result(
    slots: Slots,
    raw_candidates: list[Any],
    routes: list[dict[str, Any]],
    meet_at: str,
    rankings: list[dict[str, Any]] | None = None,
    routed_to: str = "small",
) -> Result:
    """5·6·7단계를 합쳐 Result 를 만든다.

    순위는 두 갈래다 (SDD 5절 6단계).
      rankings 가 있으면  대형 모델이 낸 rank·reason·rejected_reason·switched_from 을 그대로 쓴다
      없으면              규칙 점수 순서(domain/rules.candidate_score)와 규칙 문구로 채운다
    숫자와 access_ok 는 어느 쪽이든 코드가 넣는다.
    """
    preset = slots.preset
    access_required = bool(slots.access and slots.access.required)
    applied = slots.access.applied if slots.access else None
    lead = domain_rules.lead_min(preset)
    buffer = domain_rules.buffer_min(preset)
    by_key = {r["key"]: r for r in routes if not r.get("error")}

    judged = {row["candidate_idx"]: row for row in (rankings or [])}

    # 도착이 어긋나면 절차를 포기하고 부두 밖에서 만난다 (access.md switch_if_delay_min)
    switched = domain_rules.switch_outside(slots.constraints)
    if switched:
        access_required = False  # 절차 시작점 우선을 끄고 랜드마크를 앞세운다
    if judged:
        scored = sorted(enumerate(raw_candidates), key=lambda pair: judged[pair[0]]["rank"])
    else:
        scored = sorted(
            enumerate(raw_candidates),
            key=lambda pair: domain_rules.candidate_score(pair[1]["kind"], access_required),
            reverse=True,
        )
    # 전환했다면 원래 1순위였을 자리를 switched_from 에 남긴다. 화면이 "어디서 옮겼는지" 보여 준다
    original_top = None
    if switched:
        original = sorted(
            raw_candidates,
            key=lambda c: domain_rules.candidate_score(c["kind"], True),
            reverse=True,
        )
        original_top = original[0]["name"] if original else None

    candidates: list[Candidate] = []
    rows: list[ParticipantResult] = []

    for rank, (index, cand) in enumerate(scored, start=1):
        ok = domain_rules.access_ok(cand["kind"], applied)
        verdict = judged.get(index)
        if verdict:
            reason = verdict["reason"]
            rejected = verdict["rejected_reason"] or (None if ok else "출입조치를 신청해야 들어갈 수 있습니다")
            switched_from = verdict["switched_from"]
        else:
            reason = _reason_for(cand["kind"], access_required, ok, switched and rank == 1)
            rejected = None if ok else "출입조치를 신청해야 들어갈 수 있습니다"
            switched_from = (
                original_top if (switched and rank == 1 and cand["name"] != original_top) else None
            )
        candidates.append(
            Candidate(
                name=cand["name"],
                kind=cand["kind"],
                address=cand["address"] or "주소 미상",
                lng=cand["lng"],
                lat=cand["lat"],
                rank=rank,
                access_ok=ok,
                switched_from=switched_from,
                reason=reason,
                rejected_reason=rejected,
            )
        )

        for person in slots.participants:
            route = by_key.get((index, person.name))
            if route is None:
                continue
            transport = person.transport or "car"
            raw_min = round(route["duration_sec"] / 60)
            extra = domain_rules.traffic_extra_min(raw_min, transport, route.get("transfer_count"))
            total = raw_min + extra + buffer
            calc = domain_rules.calc_departure(meet_at, route["duration_sec"], extra + buffer, lead)
            rows.append(
                ParticipantResult(
                    name=person.name,
                    candidate_rank=rank,
                    transport=transport,
                    duration_min=total,
                    raw_duration_min=raw_min,
                    buffer_min=extra + buffer,
                    departure_time=calc["depart_at"],
                    arrive_by=calc["arrive_by_adjusted"],
                    transfer_count=route.get("transfer_count"),
                    first_train=None,
                    last_train=None,
                    polyline=[(float(x), float(y)) for x, y in route["polyline"]],
                    via_rendezvous=False,
                    via_pickup=bool(person.pickup and person.pickup_at),
                )
            )

    return Result(
        candidates=candidates,
        provisional=slots.schedule_confirmed is False,
        per_participant=rows,
        rendezvous_departure=None,
        confidence=0.8,
        model_small=_llm_meta().get("model", "unknown"),
        model_large=(rankings[0].get("model") if rankings else None),
        prompt_version=_llm_meta().get("prompt_version", "converge/slot-extract"),
        routed_to="large" if rankings else "small",
    )


def _reason_for(kind: str, access_required: bool, ok: bool, switched: bool = False) -> str:
    """순위 이유 한 줄. 규칙 파일 항목을 인용한다 (SDD 4절 Candidate.reason).

    대형 모델이 붙기 전까지는 규칙 문구를 그대로 쓴다 (SDD 5절 6단계 "실패면 규칙 문구 그대로").
    """
    if not ok:
        return "access.md pier_requires_access_applied: 출입조치 전이라 부두 안은 쓸 수 없습니다"
    if switched:
        return "access.md switch_if_delay_min: 도착이 어긋나 출입 절차를 포기하고 부두 밖에서 만납니다"
    if access_required and kind in ("gate", "lobby", "hq"):
        return "access.md rendezvous_is_procedure_start: 출입 절차가 시작되는 자리에서 합류합니다"
    if kind == "landmark":
        return "access.md outside_landmark_kinds: 지리를 몰라도 찾기 쉬운 자리입니다"
    return "목적지에서 가장 가까운 자리입니다"


# ─────────────────────────────────────────────────────────────────────────────
# 세션 (SDD 5절 재질문, 8단계 store.save)
# ─────────────────────────────────────────────────────────────────────────────


def _slots_from_session(row: dict[str, Any]) -> Slots:
    """저장된 세션을 Slots 로 되돌린다. 재질문 때 1단계 프롬프트에 넣는다.

    저장은 표 컬럼으로 흩어져 있고 (테이블정의서 1절) 슬롯은 한 덩어리라 여기서 다시 모은다.
    검증을 거치지 않는 이유: 저장 당시에는 통과한 값이고, 지금은 프롬프트에 넣을 참고 자료이기 때문이다.
    """
    return Slots.model_construct(
        preset=row.get("preset"),
        datetime=None,  # 표에는 meet_at(시각)만 있고 사람이 쓴 표현은 남기지 않는다
        purpose=row.get("purpose"),
        destination=row.get("destination_name"),
        participants=[Participant.model_construct(**p) for p in row.get("participants") or []],
        rendezvous=None,
        access=row.get("access"),
        schedule_confirmed=row.get("schedule_confirmed"),
        constraints=row.get("constraints") or [],
        missing=[],
        out_of_scope=False,
    )


async def _load_previous(deps: Deps, session_id: str, user_id: str) -> Slots | None:
    """재질문이면 이전 세션을 읽는다. 없으면 None.

    먼저 잠금과 주인을 본다. 남의 세션이면 403, 약속이 지난 세션이면 409 다. 둘 다 LLM 을 부르기 전에
    막는다 (SDD 5절 재질문, 비용 방어).
    """
    if deps.load_session is None:
        return None
    row = await deps.load_session(session_id)
    if row is None:
        return None
    if row.get("user_id") and row["user_id"] != user_id:
        raise NotYourSession(session_id)
    if row.get("locked"):
        raise SessionLocked(session_id)
    return _slots_from_session(row)


async def _persist(
    deps: Deps,
    *,
    session_id: str,
    is_new: bool,
    user_id: str,
    slots: Slots,
    result: Result,
    trace_id: str,
    pins: list[GeocodedPin],
) -> str:
    """8단계. 세션과 결과를 저장하고 최종 session_id 를 돌려준다.

    DB 가 없으면 저장만 건너뛰고 계산 결과는 그대로 보여 준다. 화면이 멈추는 것보다 낫고,
    저장 실패는 Langfuse span 에 남는다. (설정이 들어오면 이 갈래는 사라진다)
    """
    if deps.save is None:
        return session_id
    participants = _participants_for_store(slots, pins)
    return await deps.save(
        session_id=None if is_new else session_id,
        user_id=user_id,
        slots=slots,
        participants=participants,
        result=result,
        trace_id=trace_id,
    )


def _participants_for_store(slots: Slots, pins: list[GeocodedPin]) -> list[dict[str, Any]]:
    """저장용 참석자 평문 구조 (테이블정의서 1절 participants_enc).

    좌표는 슬롯이 아니라 지오코딩 결과에 있으므로 여기서 이름으로 붙여 넣는다.
    """
    coords = {p.name: p for p in pins if p.kind == "participant"}
    out: list[dict[str, Any]] = []
    for person in slots.participants:
        pin = coords.get(person.name)
        out.append(
            {
                "name": person.name,
                "origin_text": person.origin,
                "lng": pin.lng if pin else None,
                "lat": pin.lat if pin else None,
                "transport": person.transport,
                "pickup": person.pickup,
                "pickup_at": person.pickup_at,
                "unfamiliar": person.unfamiliar,
                "role": person.role,
                "confirmed": bool(pin and pin.confidence >= 1.0),
                "owner_user_id": person.owner_user_id,
                "origin_set_by": "self" if person.owner_user_id else "organizer",
                "self_edited_at": None,
            }
        )
    return out
