"""services/llm.py 모델 라우팅 테스트 (docs/specs/model-routing.md). 키 없이 돈다.

확인하는 것: 쉬운 판정(신호가 모두 clear거나 하나만 켜짐)만 LLM_ROUTE_SMALL_MODEL로 가고,
회색 지대·unknown·신호 둘 이상·검증 재시도는 서비스 모델(LLM_MODEL)에 남는다. 설정이 없으면 라우팅하지 않는다.
"""
from datetime import datetime, timezone

import pytest

from backend.app.schemas.signals import Signal, SignalSet
from backend.app.services import llm

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)
IDS = ["position_stale", "eta_conflict", "anchor_wait", "dest_changed", "navstat_mismatch", "customs_hold",
       "sales_date_exceeded"]


def _set(**states) -> SignalSet:
    """states에 없는 신호는 clear. 값은 가공값."""
    signals = [Signal(id=i, state=states.get(i, "clear"), value="가공", threshold="rules.md", source="test") for i in IDS]
    return SignalSet(signals=signals, freshness="fresh", distance_nm=10.0, calc_eta=NOW, eta_gap_hours=1.0,
                     computed_at=NOW)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "big/model")
    monkeypatch.setenv("LLM_ROUTE_SMALL_MODEL", "small/model")


@pytest.mark.parametrize("states, mode, feedback, expected", [
    ({}, "fixed", None, "easy"),                                              # 모두 clear
    ({"dest_changed": "triggered"}, "fixed", None, "easy"),                   # 하나만 켜짐
    ({"dest_changed": "triggered", "eta_conflict": "triggered"}, "fixed", None, "hard"),  # 둘 이상
    ({"position_stale": "unknown"}, "fixed", None, "hard"),                   # unknown
    ({}, "raise_only", None, "hard"),                                         # 회색 지대
    ({}, "fixed", "V3 violated", "hard"),                                     # 검증 재시도
])
def test_difficulty(states, mode, feedback, expected):
    assert llm.judge_difficulty(_set(**states), mode, feedback) == expected


def test_easy_goes_to_small_model():
    assert llm.route_judge_model(_set(), "fixed", None) == "small/model"


def test_hard_stays_on_service_model():
    assert llm.route_judge_model(_set(anchor_wait="unknown"), "raise_only", None) is None


def test_no_routing_without_small_model(monkeypatch):
    monkeypatch.delenv("LLM_ROUTE_SMALL_MODEL")
    assert llm.route_judge_model(_set(), "fixed", None) is None


def test_no_routing_in_replay_without_llm_model(monkeypatch):
    # LLM_MODEL이 비면 녹화 답 재생이다. 모델을 정해 넘기면 재생을 건너뛰므로 고르지 않는다
    monkeypatch.delenv("LLM_MODEL")
    assert llm.route_judge_model(_set(), "fixed", None) is None


def test_judge_passes_routed_model(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "_judge_input", lambda *a, **k: "{}")
    monkeypatch.setattr(llm, "_ask_json", lambda *a, **k: seen.setdefault("model", a[5]))
    llm.judge(_set(), None, 5, verdict_mode="fixed")
    assert seen["model"] == "small/model"


def test_explicit_model_wins(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "_judge_input", lambda *a, **k: "{}")
    monkeypatch.setattr(llm, "_ask_json", lambda *a, **k: seen.setdefault("model", a[5]))
    llm.judge(_set(), None, 5, model="chosen/model", verdict_mode="fixed")
    assert seen["model"] == "chosen/model"
