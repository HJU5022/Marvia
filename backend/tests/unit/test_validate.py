"""C-7 출력 검증 7규칙 테스트 (SDD 5.7). 규칙마다 통과 1건·위반 1건."""
from datetime import datetime, timezone

from backend.app.schemas.agent import AgentResponse
from backend.app.services.judge.validate import check

NOW = datetime(2026, 9, 28, 3, 0, tzinfo=timezone.utc)
EVIDENCE = [
    {"source": "mof", "field": "planned_arrival", "value": "2026-10-01 09:00", "fetched_at": NOW},
    {"source": "rule", "field": "days_margin", "value": "4", "fetched_at": NOW},
]


def _response(**over) -> AgentResponse:
    base = dict(status="ok", verdict="fine", vessel_match="confirmed", days_margin=4, decided_by="llm",
                vessel=None, position=None, eta=None, customs=None, berth=None, evidence=EVIDENCE,
                answer="10월 1일 입항 예정이고 판매일까지 4일 여유가 있습니다.", trace_id="t")
    return AgentResponse(**{**base, **over})


def _rules(response) -> list[str]:
    return [v.rule for v in check(response)]


def test_clean_response_passes():
    assert _rules(_response()) == []


def test_v1_stale_position_must_not_be_called_current():
    position = {"lat": 35.1, "lng": 129.0, "sog": 0, "cog": 0, "navistat": 0, "last_time": NOW, "freshness": "stale"}
    assert "V1" in _rules(_response(position=position, answer="현재 위치는 부산 앞바다입니다."))
    assert "V1" not in _rules(_response(position=position, answer="마지막으로 확인된 위치는 부산 앞바다입니다."))


def test_v2_warning_needs_known_rule_reasons():
    assert "V2" in _rules(_response(verdict="watch", reasons=[]))
    bad = [{"rule": "made_up_rule", "value": "x", "triggered": True}]
    assert "V2" in _rules(_response(verdict="act", reasons=bad))
    good = [{"rule": "eta_conflict", "value": "x", "triggered": True}]
    assert "V2" not in _rules(_response(verdict="watch", reasons=good))


def test_v3_eta_needs_evidence():
    eta = {"ais_eta": None, "mof_eta": NOW, "calc_eta": None, "trusted_eta": NOW, "distance_nm": None}
    assert "V3" in _rules(_response(eta=eta, evidence=[], answer="입항 예정입니다."))
    assert "V3" not in _rules(_response(eta=eta))


def test_v4_uncertain_vessel_has_no_verdict():
    assert "V4" in _rules(_response(vessel_match="uncertain", verdict="fine"))


def test_v5_insufficient_asks_something():
    assert "V5" in _rules(_response(status="insufficient", verdict=None, missing_inputs=[]))
    assert "V5" not in _rules(_response(status="insufficient", verdict=None, missing_inputs=["forwarder_eta"]))


def test_v6_chosen_source_must_be_in_evidence():
    conflict = {"signals": ["eta_conflict", "position_stale"], "chosen": "shipfinder", "why": "x"}
    assert "V6" in _rules(_response(conflicts=[conflict]))  # 근거 카드에 shipfinder가 없다
    assert "V6" not in _rules(_response(conflicts=[{**conflict, "chosen": "mof"}]))


def test_v7_numbers_in_answer_come_from_evidence():
    assert "V7" in _rules(_response(answer="10월 3일에 들어옵니다."))  # 3은 근거에 없다
    assert "V7" not in _rules(_response(answer="판매일을 2일 넘깁니다.", days_margin=-2,
                                          evidence=EVIDENCE + [{"source": "rule", "field": "days_margin", "value": "-2", "fetched_at": NOW}]))
