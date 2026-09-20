"""슬롯 추출의 모델 시도 순서 (SDD 5절 1단계). 키 없이 돈다 (TEST_GUIDE)."""
from __future__ import annotations

import os

import pytest

from backend.app.services import llm


@pytest.fixture(autouse=True)
def _no_local_gguf(monkeypatch):
    """이 파일은 환경변수 기반 시도 순서만 본다. 로컬 GGUF 가 있는 PC 에서도 같은 결과가 나오게 끈다."""
    from backend.app.services import slot_model

    monkeypatch.setattr(slot_model, "available", lambda: False)


@pytest.fixture(autouse=True)
def _env():
    before = {k: os.environ.get(k) for k in ("MODEL_SMALL", "MODEL_LARGE")}
    os.environ["MODEL_LARGE"] = "vendor/large"
    os.environ.pop("MODEL_SMALL", None)
    yield
    for key, value in before.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_소형이_없으면_대형으로_두_번까지만():
    assert llm.attempt_models() == ["vendor/large", "vendor/large"]


def test_소형이_있으면_두_번_시도하고_대형으로_승격한다():
    os.environ["MODEL_SMALL"] = "vendor/small"
    assert llm.attempt_models() == ["vendor/small", "vendor/small", "vendor/large"]


def test_소형과_대형이_같으면_승격하지_않는다():
    os.environ["MODEL_SMALL"] = "vendor/large"
    assert llm.attempt_models() == ["vendor/large", "vendor/large"]


def test_일인칭_이름을_나_로_맞춘다():
    from backend.app.schemas.slots import Slots

    slots = Slots(
        preset="ship_maintenance",
        destination="진해 기지",
        participants=[
            dict(name="저", origin="창원시청", transport="car", role="site"),
            dict(name="최동료", origin="마산역", transport="transit", role="colleague"),
        ],
    )
    out = llm.normalize_names(slots)
    assert [p.name for p in out.participants] == ["나", "최동료"]


def test_픽업이_일인칭을_가리키면_같이_바꾼다():
    from backend.app.schemas.slots import Slots

    slots = Slots(
        preset="ship_maintenance",
        destination="진해 기지",
        participants=[
            dict(name="제가", origin="창원시청", transport="car", role="site"),
            dict(name="이업체", origin=None, transport="car", role="vendor", pickup="제가", pickup_at="김해시청 앞"),
        ],
    )
    out = llm.normalize_names(slots)
    assert [p.name for p in out.participants] == ["나", "이업체"]
    assert out.participants[1].pickup == "나"


def test_보통_이름은_건드리지_않는다():
    from backend.app.schemas.slots import Slots

    slots = Slots(
        preset="si_deploy",
        destination="여의도 고객사",
        participants=[dict(name="한동료", origin="강남역", transport="transit", role="colleague")],
    )
    assert llm.normalize_names(slots).participants[0].name == "한동료"


def test_로컬_GGUF_가_있으면_그것을_먼저_쓴다(monkeypatch):
    """SDD 8절: 소형은 로컬 GGUF 가 1순위다. 실패하면 대형으로 승격한다."""
    from backend.app.services import slot_model

    monkeypatch.setattr(slot_model, "available", lambda: True)
    monkeypatch.setattr(slot_model, "model_name", lambda: "local/kanana")
    assert llm.attempt_models() == ["local/kanana", "local/kanana", "vendor/large"]
