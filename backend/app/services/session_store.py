"""파이프라인과 store.py 사이. (SDD 5절 8단계, 재질문)

store.py 는 표 단위 함수(create_session, update_session, save_result)를 준다. 파이프라인은
"이번 요청을 저장해 줘" 하나만 알면 된다. 그 사이를 이 파일이 맡는다.

store.py 는 하정운 담당이라 고치지 않는다. 여기서 부르기만 한다.
"""
from __future__ import annotations

from typing import Any

from backend.app.schemas.result import Result
from backend.app.schemas.slots import Slots
from backend.app.services import store


async def load_session(session_id: str) -> dict[str, Any] | None:
    """재질문이 읽는 세션 한 건. 잠금 여부까지 붙여 준다."""
    row = await store.get_session(session_id)
    if row is None:
        return None
    return {**row, "locked": store.is_locked(row.get("meet_at"))}


async def save(
    *,
    session_id: str | None,
    user_id: str,
    slots: Slots,
    participants: list[dict[str, Any]],
    result: Result,
    trace_id: str,
) -> str:
    """세션과 결과를 저장하고 session_id 를 돌려준다.

    session_id 가 None 이면 새 세션을 만든다. DB 가 uuid 를 만들어 주므로 그 값이 진짜 id 다.
    이미 있는 세션이면 참석자 좌표와 상태만 갱신한다.

    meet_at 을 넣지 않는 이유: 슬롯의 datetime 은 "목요일 아침 8시" 같은 사람 말이고 날짜가 없다.
    날짜 해석이 들어오기 전까지는 임시 세션으로 두고 보관 기간 7일을 따른다 (테이블정의서 6절).
    """
    dest = _destination(result)
    if session_id is None:
        session_id = await store.create_session(
            user_id=user_id,
            preset=slots.preset or "si_deploy",
            participants=participants,
            purpose=slots.purpose,
            destination_name=slots.destination,
            destination_lng=dest[0],
            destination_lat=dest[1],
            rendezvous=slots.rendezvous.model_dump() if slots.rendezvous else None,
            access=slots.access.model_dump() if slots.access else None,
            schedule_confirmed=slots.schedule_confirmed,
            constraints=slots.constraints,
        )
    await store.update_session(session_id, participants=participants, status="computed")
    await store.save_result(
        session_id=session_id,
        candidates=[c.model_dump() for c in result.candidates],
        per_participant=[r.model_dump() for r in result.per_participant],
        routed_to=result.routed_to,
        model_small=result.model_small,
        model_large=result.model_large,
        prompt_version=result.prompt_version,
        rendezvous_departure=result.rendezvous_departure,
        provisional=result.provisional,
        trace_id=trace_id,
        confidence=result.confidence,
    )
    return session_id


def _destination(result: Result) -> tuple[float | None, float | None]:
    """목적지 좌표 자리. 지금은 1순위 후보 좌표를 쓴다 (목적지 핀과 후보가 같은 건물일 때가 많다)."""
    top = next((c for c in result.candidates if c.rank == 1), None)
    return (top.lng, top.lat) if top else (None, None)
