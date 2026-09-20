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


def test_세션_id_를_첫_요청에서_만든다():
    out = run(AgentRequest(text="점검"), deps(slots()))
    assert out.session_id and len(out.session_id) >= 16


def test_세션_id_가_오면_그대로_쓴다():
    out = run(AgentRequest(session_id="keep-me", text="점검"), deps(slots()))
    assert out.session_id == "keep-me"


def _done_deps(**over) -> pipeline.Deps:
    """done 까지 가는 가짜 단계들. 외부 호출 없이 3~8단계를 흉내 낸다."""

    async def build_candidates(*_):
        return [
            {"name": "위병소", "kind": "gate", "address": "테스트", "lng": 128.67, "lat": 35.14},
            {"name": "진해역", "kind": "landmark", "address": "테스트", "lng": 128.69, "lat": 35.15},
        ]

    async def compute_routes(plans):
        return [
            {
                "key": plan["key"],
                "duration_sec": 1800,
                "polyline": [[128.68, 35.22], [128.67, 35.14]],
                "transfer_count": None,
            }
            for plan in plans
        ]

    base = dict(build_candidates=build_candidates, compute_routes=compute_routes)
    base.update(over)
    return deps(slots(datetime="목요일 08:00"), **base)


def test_계산이_끝나면_저장하고_세션_id_를_돌려준다():
    saved = {}

    async def save(**kwargs):
        saved.update(kwargs)
        return "db-session-1"

    out = run(AgentRequest(text="점검"), _done_deps(save=save))
    assert out.stage == "done"
    assert out.session_id == "db-session-1"  # DB 가 만든 id 를 쓴다
    assert saved["session_id"] is None  # 새 세션이라 None 으로 넘긴다
    assert saved["participants"][0]["origin_text"] == "창원시청"
    assert saved["participants"][0]["lng"] == 128.68


def test_저장에_실패해도_결과는_보여_준다():
    async def boom(**_):
        raise RuntimeError("DB 없음")

    out = run(AgentRequest(text="점검"), _done_deps(save=boom))
    assert out.stage == "done"
    assert out.result is not None


def test_남의_세션으로_재질문하면_막는다():
    async def load_session(_):
        return {"user_id": "other", "locked": False, "participants": []}

    with pytest.raises(pipeline.NotYourSession):
        run(AgentRequest(session_id="s1", text="점검"), _done_deps(load_session=load_session))


def test_잠긴_세션이면_막는다():
    async def load_session(_):
        return {"user_id": "u1", "locked": True, "participants": []}

    with pytest.raises(pipeline.SessionLocked):
        run(AgentRequest(session_id="s1", text="점검"), _done_deps(load_session=load_session), user_id="u1")


def test_재질문이면_이전_슬롯을_추출에_넘긴다():
    seen = {}

    async def load_session(_):
        return {
            "user_id": "u1",
            "locked": False,
            "preset": "ship_maintenance",
            "purpose": "레이더 정기점검",
            "destination_name": "진해 기지",
            "participants": [{"name": "김현장", "origin": "창원시청", "transport": "car", "role": "site"}],
            "constraints": [],
        }

    async def extract_slots(text, previous, preset):
        seen["previous"] = previous
        return slots(datetime="목요일 08:00")

    d = _done_deps(load_session=load_session, extract_slots=extract_slots)
    run(AgentRequest(session_id="s1", text="출입조치 했어요"), d, user_id="u1")
    assert seen["previous"] is not None
    assert seen["previous"].destination == "진해 기지"
