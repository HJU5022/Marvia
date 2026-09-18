"""스키마 위반이 실제로 잡히는지 (TEST_GUIDE, SDD 3·4절 검증 규칙).

키가 필요 없다. 외부 호출도 없다. 여기서 막지 못하면 잘못된 슬롯이 그대로 계산에 들어가고,
파인튜닝 데이터와 평가셋도 같이 어긋난다.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas.request import AgentRequest, ParticipantPatchRequest
from backend.app.schemas.result import AgentResponse, Candidate, ParticipantResult, Result
from backend.app.schemas.slots import Participant, Slots


def participant(**over) -> dict:
    base = dict(name="김현장", origin="창원시청", transport="car", role="site")
    base.update(over)
    return base


def slots(**over) -> dict:
    base = dict(preset="ship_maintenance", participants=[participant()])
    base.update(over)
    return base


# --- 슬롯 (SDD 3절) ---


def test_슬롯_기본형이_통과한다():
    s = Slots(**slots())
    assert s.participants[0].owner_user_id is None  # 서버가 채우기 전까지 주선자 소유


@pytest.mark.parametrize("bad", ["鎭海 기지", "ジンヘ 기지"])
def test_한자_가나가_섞이면_막는다(bad):
    with pytest.raises(ValidationError):
        Slots(**slots(destination=bad))


def test_참석자_이름에_한자가_섞여도_막는다():
    with pytest.raises(ValidationError):
        Participant(**participant(name="金현장"))


def test_이동수단이_없으면_missing_에_있어야_한다():
    with pytest.raises(ValidationError):
        Slots(**slots(participants=[participant(transport=None)]))

    ok = Slots(**slots(participants=[participant(transport=None)], missing=["participants[0].transport"]))
    assert ok.participants[0].transport is None


def test_pickup_과_pickup_at_은_짝이다():
    with pytest.raises(ValidationError):
        Participant(**participant(pickup="박업체"))
    with pytest.raises(ValidationError):
        Participant(**participant(pickup_at="김해시청 앞"))

    ok = Participant(**participant(pickup="박업체", pickup_at="김해시청 앞"))
    assert ok.pickup == "박업체"


def test_범위_밖이면_프리셋과_참석자가_비어야_한다():
    with pytest.raises(ValidationError):
        Slots(**slots(out_of_scope=True))  # preset·participants 가 남아 있다

    ok = Slots(preset=None, participants=[], out_of_scope=True)
    assert ok.out_of_scope


def test_범위_밖이_아니면_프리셋과_참석자가_있어야_한다():
    with pytest.raises(ValidationError):
        Slots(**slots(preset=None))
    with pytest.raises(ValidationError):
        Slots(**slots(participants=[]))


# --- 결과 (SDD 4절) ---


def candidate(**over) -> dict:
    base = dict(
        name="진해 기지 위병소",
        kind="gate",
        address="테스트 주소",
        lng=128.67,
        lat=35.144,
        rank=1,
        access_ok=True,
        reason="access.md rendezvous_is_procedure_start",
    )
    base.update(over)
    return base


def row(**over) -> dict:
    base = dict(
        name="김현장",
        candidate_rank=1,
        transport="car",
        duration_min=41,
        raw_duration_min=21,
        buffer_min=20,
        departure_time="06:59",
        arrive_by="07:40",
    )
    base.update(over)
    return base


def result(**over) -> dict:
    base = dict(
        candidates=[candidate()],
        provisional=False,
        per_participant=[row()],
        confidence=0.86,
        model_small="small",
        model_large="large",
        prompt_version="v1",
        routed_to="large",
    )
    base.update(over)
    return base


def test_결과_기본형이_통과한다():
    assert Result(**result()).candidates[0].rank == 1


def test_좌표가_국내_범위를_벗어나면_막는다():
    with pytest.raises(ValidationError):
        Candidate(**candidate(lng=2.35, lat=48.85))


def test_후보는_세_곳까지다():
    four = [candidate(name=f"후보{i}", rank=None) for i in range(4)]
    with pytest.raises(ValidationError):
        Result(**result(candidates=four))


def test_후보_순위가_겹치면_막는다():
    two = [candidate(), candidate(name="진해역", kind="landmark")]
    with pytest.raises(ValidationError):
        Result(**result(candidates=two))


def test_참석자_결과가_없는_후보를_가리키면_막는다():
    with pytest.raises(ValidationError):
        Result(**result(per_participant=[row(candidate_rank=2)]))


def test_시각은_HHMM_형식만_받는다():
    with pytest.raises(ValidationError):
        ParticipantResult(**row(departure_time="6:59"))
    with pytest.raises(ValidationError):
        ParticipantResult(**row(arrive_by="25:00"))


def test_여유를_더한_소요가_경로값보다_작을_수_없다():
    with pytest.raises(ValidationError):
        ParticipantResult(**row(duration_min=10, raw_duration_min=21))


# --- 응답과 요청 (SDD 2절) ---


def response(**over) -> dict:
    base = dict(session_id="s1", stage="need_confirm", slots=Slots(**slots()), message="확인해 주세요", trace_id="t1")
    base.update(over)
    return base


def test_done_인데_결과가_없으면_막는다():
    with pytest.raises(ValidationError):
        AgentResponse(**response(stage="done"))

    ok = AgentResponse(**response(stage="done", result=Result(**result())))
    assert ok.result is not None


def test_need_info_인데_되물을_것이_없으면_막는다():
    with pytest.raises(ValidationError):
        AgentResponse(**response(stage="need_info"))


def test_요청은_문장이나_캡처_중_하나가_필요하다():
    with pytest.raises(ValidationError):
        AgentRequest()

    assert AgentRequest(text="목요일 08:00 진해 기지 점검").text is not None
    assert AgentRequest(image_base64="abc").image_base64 == "abc"


def test_핀_수정_요청은_claim_기본값이_거짓이다():
    body = ParticipantPatchRequest(name="김현장", lng=128.68, lat=35.22)
    assert body.claim is False
