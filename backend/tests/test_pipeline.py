"""파이프라인 단계 순서와 갈림길 (SDD 5절 표).

바깥 호출은 전부 가짜 함수로 바꾼다. 키도, 네트워크도 필요 없다 (TEST_GUIDE).
여기서 보는 것은 "어떤 상황에서 어느 stage 로 빠지는가" 하나다.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.app.schemas.request import AgentRequest, ParticipantInput
from backend.app.schemas.result import GeocodedPin
from backend.app.schemas.slots import Slots
from backend.app.services import pipeline


def slots(**over) -> Slots:
    base = dict(
        preset="ship_maintenance",
        destination="진해 기지",
        participants=[dict(name="김현장", origin="창원시청", transport="car", role="site")],
    )
    base.update(over)
    return Slots(**base)


def pins(confidence: float = 0.95) -> list[GeocodedPin]:
    return [
        GeocodedPin(name="김현장", lng=128.68, lat=35.22, confidence=confidence, kind="participant"),
        GeocodedPin(name="진해 기지", lng=128.668, lat=35.143, confidence=0.9, kind="destination"),
    ]


def deps(slots_out: Slots, pins_out=None, **over) -> pipeline.Deps:
    async def extract_slots(*_):
        return slots_out

    async def geocode_all(*_):
        return pins_out if pins_out is not None else pins()

    base = dict(extract_slots=extract_slots, geocode_all=geocode_all)
    base.update(over)
    return pipeline.Deps(**base)


def run(req: AgentRequest, d: pipeline.Deps, user_id: str = "u1"):
    return asyncio.run(pipeline.run(req, user_id, d))


def test_범위_밖이면_out_of_scope_로_끝난다():
    out = run(AgentRequest(text="지금 막히는지 알려줘"), deps(Slots(out_of_scope=True)))
    assert out.stage == "out_of_scope"
    assert out.result is None
    assert out.trace_id  # Langfuse 가 꺼져 있어도 trace_id 는 있다


def test_누락이_있으면_need_info_로_되묻는다():
    s = slots(
        participants=[dict(name="김현장", origin="창원시청", transport=None, role="site")],
        missing=["participants[0].transport", "datetime"],
        datetime=None,
    )
    out = run(AgentRequest(text="목요일 점검"), deps(s))
    assert out.stage == "need_info"
    assert len(out.questions) == 2


def test_같은_종류의_누락은_질문을_한_번만_한다():
    s = slots(
        participants=[
            dict(name="김현장", origin="창원시청", transport=None, role="site"),
            dict(name="박업체", origin="부산 사상", transport=None, role="vendor"),
        ],
        missing=["participants[0].transport", "participants[1].transport"],
    )
    out = run(AgentRequest(text="점검"), deps(s))
    assert out.questions == ["차로 오시나요, 대중교통으로 오시나요?"]


def test_확신도가_낮으면_need_confirm_으로_멈추고_핀을_보낸다():
    out = run(AgentRequest(text="점검"), deps(slots(), pins(confidence=0.5)))
    assert out.stage == "need_confirm"
    assert out.geocoded is not None and len(out.geocoded) == 2


def test_확인한_좌표가_오면_그_좌표로_바꾸고_확신도를_올린다():
    req = AgentRequest(
        text="점검", confirmed_participants=[ParticipantInput(name="김현장", lng=128.7, lat=35.25)]
    )
    out = run(req, deps(slots(), pins(confidence=0.5)))
    assert out.stage != "need_confirm"
    pin = next(p for p in out.geocoded if p.name == "김현장")
    assert (pin.lng, pin.lat, pin.confidence) == (128.7, 35.25, 1.0)


def test_남의_핀을_고치려_하면_막는다():
    s = slots(
        participants=[dict(name="김현장", origin="창원시청", transport="car", role="site", owner_user_id="other")]
    )
    req = AgentRequest(text="점검", confirmed_participants=[ParticipantInput(name="김현장", lng=128.7, lat=35.25)])
    with pytest.raises(pipeline.NotYourPin):
        run(req, deps(s, pins(confidence=0.5)))


def test_내_핀은_고칠_수_있다():
    s = slots(
        participants=[dict(name="김현장", origin="창원시청", transport="car", role="site", owner_user_id="u1")]
    )
    req = AgentRequest(text="점검", confirmed_participants=[ParticipantInput(name="김현장", lng=128.7, lat=35.25)])
    assert run(req, deps(s, pins(confidence=0.5)), user_id="u1").stage != "need_confirm"


def test_슬롯_추출이_실패하면_failed():
    async def boom(*_):
        raise ValueError("스키마 위반")

    out = run(AgentRequest(text="점검"), pipeline.Deps(extract_slots=boom))
    assert out.stage == "failed"


def test_캡처를_읽지_못하면_문장으로_다시_받는다():
    async def boom(*_):
        raise RuntimeError("비전 모델 실패")

    out = run(AgentRequest(image_base64="abc"), pipeline.Deps(extract_text=boom))
    assert out.stage == "need_info"
    assert out.questions


def test_지오코딩이_실패하면_failed():
    async def boom(*_):
        raise RuntimeError("카카오 응답 없음")

    out = run(AgentRequest(text="점검"), deps(slots(), geocode_all=boom))
    assert out.stage == "failed"


def test_아직_구현하지_않은_단계는_조용히_넘어가지_않는다():
    # 3~8단계가 비어 있는 동안에는 failed 로 끝난다. 나중에 채우면 이 테스트를 done 으로 바꾼다
    out = run(AgentRequest(text="점검"), deps(slots()))
    assert out.stage == "failed"
    assert out.geocoded is not None
