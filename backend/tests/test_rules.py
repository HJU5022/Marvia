"""규칙 적용 계산 (SDD 5절 5·7단계). 규칙값은 skills/converge/rules/ 에서 읽는다."""
from __future__ import annotations

from backend.app.domain import rules


def test_시각_표현을_HHMM_으로_바꾼다():
    assert rules.parse_meet_time("목요일 08:00") == "08:00"
    assert rules.parse_meet_time("목요일 아침 8시") == "08:00"
    assert rules.parse_meet_time("오후 2시") == "14:00"
    assert rules.parse_meet_time("내일 저녁 7시 30분") == "19:30"
    assert rules.parse_meet_time("언젠가") is None
    assert rules.parse_meet_time(None) is None


def test_절차_소요와_여유는_프리셋마다_다르다():
    assert rules.lead_min("ship_maintenance") == 20
    assert rules.lead_min("si_deploy") == 15
    assert rules.buffer_min("ship_maintenance") == 20
    assert rules.buffer_min("si_deploy") == 15


def test_자동차는_정체분_대중교통은_환승만_얹는다():
    assert rules.traffic_extra_min(40, "car", None) == 10  # 15% 는 6분이라 최소 10분
    assert rules.traffic_extra_min(120, "car", None) == 18
    assert rules.traffic_extra_min(40, "transit", 0) == 0
    assert rules.traffic_extra_min(40, "transit", 2) == 10


def test_부두는_출입조치를_신청한_경우에만_쓸_수_있다():
    assert rules.access_ok("pier", True) is True
    assert rules.access_ok("pier", None) is False
    assert rules.access_ok("gate", None) is True


def test_절차가_있으면_절차_시작점이_앞선다():
    assert rules.candidate_score("gate", True) > rules.candidate_score("landmark", True)
    assert rules.candidate_score("landmark", False) > rules.candidate_score("gate", False)


def test_도착이_어긋나면_부두_밖으로_전환한다():
    assert rules.switch_outside([]) is False
    assert rules.switch_outside(["port_changed"]) is False
    assert rules.switch_outside(["arrival_delayed"]) is True


def test_출발_시각은_도착_기한에서_거꾸로_뺀다():
    out = rules.calc_departure("08:00", 40 * 60, 20, 20)
    assert out == {"depart_at": "06:40", "arrive_by_adjusted": "07:40", "day_offset": 0}
