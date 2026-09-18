"""소형·대형 선택이 SDD 5절 조건 그대로인지. 계산만이라 키 없이 돈다 (TEST_GUIDE)."""
from __future__ import annotations

from backend.app.domain.router import route
from backend.app.schemas.slots import Access, Rendezvous, Slots


def slots(**over) -> Slots:
    base = dict(
        preset="si_deploy",
        destination="여의도 고객사",
        participants=[
            dict(name="한동료", origin="강남역", transport="transit", role="colleague"),
            dict(name="서현장", origin="수원시청", transport="car", role="site"),
        ],
    )
    base.update(over)
    return Slots(**base)


def test_참석자_둘_이하_단순건은_소형으로_끝낸다():
    assert route(slots()) == "small"


def test_참석자가_셋이면_대형():
    three = slots().participants + [
        Slots(**dict(preset="si_deploy", participants=[dict(name="조업체", origin="부평역", transport="transit", role="vendor")])).participants[0]
    ]
    assert route(slots(participants=[p.model_dump() for p in three])) == "large"


def test_목적지가_없으면_대형():
    assert route(slots(destination=None)) == "large"


def test_제약이_하나라도_있으면_대형():
    assert route(slots(constraints=["arrival_delayed"])) == "large"


def test_집결지가_있으면_대형():
    assert route(slots(rendezvous=Rendezvous(name="문정동 본사", transport_after="car").model_dump())) == "large"


def test_출입조치를_아직_신청하지_않았으면_대형():
    assert route(slots(access=Access(required=True, applied=None, lead_min=15).model_dump())) == "large"
    assert route(slots(access=Access(required=True, applied=False, lead_min=15).model_dump())) == "large"


def test_출입조치를_이미_신청했으면_소형():
    assert route(slots(access=Access(required=True, applied=True, lead_min=15).model_dump())) == "small"
