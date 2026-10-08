"""판정 표의 허용 범위 테스트 (D7, services/judge/verdict.py). 표 등급 자체는 test_baseline_rules.py가 본다."""
import pytest

from backend.app.services.judge import verdict


@pytest.mark.parametrize("llm_verdict, table, gray, ok", [
    ("watch", "watch", False, True),   # 확실하면 표와 같아야 한다
    ("act", "watch", False, False),    # 확실할 때는 올리는 것도 안 된다 (등급은 표가 책임진다)
    ("fine", "watch", False, False),
    ("watch", "fine", True, True),     # 회색 지대: 올리기 가능
    ("act", "watch", True, True),
    ("fine", "watch", True, False),    # 회색 지대라도 낮추기는 안 된다
    (None, "fine", True, False),       # 보류(null)는 받지 않는다. 보류는 코드가 LLM 전에 한다
])
def test_allowed(llm_verdict, table, gray, ok):
    assert verdict.allowed(llm_verdict, table, gray) is ok


class _S:
    def __init__(self, id, state):
        self.id, self.state = id, state


class _Set:
    def __init__(self, **states):
        self.signals = [_S(i, s) for i, s in states.items()]


def test_gray_only_for_act_signals():
    assert verdict.is_gray(_Set(anchor_wait="unknown"))
    assert verdict.is_gray(_Set(customs_hold="unknown"))
    # 판매일을 안 넣어 생긴 unknown과 다른 신호의 unknown은 회색 지대가 아니다
    assert not verdict.is_gray(_Set(sales_date_exceeded="unknown", eta_conflict="unknown"))
