"""판정 재시도 시간 예산 테스트 (routers/agent.py JUDGE_BUDGET_SEC). 키 없이 돈다.

실측에서 판정 LLM 호출 한 번이 7~40초였고, 검증 위반으로 세 번 다 돌면 121초·170초가 걸려 화면(90초)이 먼저 끊겼다.
"지금까지 쓴 시간 + 방금 호출 시간"이 예산을 넘을 것 같으면 다시 묻지 않고 판정 표 등급으로 partial을 내는지 본다.
시계는 가짜로 바꿔 끼워 실제로 기다리지 않는다. 가짜 UNI-PASS·도구는 test_routers.py의 fake를 같이 쓴다.
"""
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import agent as agent_router
from backend.app.services import llm
from backend.tests.integration.test_routers import JUDGED, POSITION, _candidate, _request, _signals, fake  # noqa: F401 (fixture)

BAD = {**JUDGED, "answer": "10월 3일에 들어옵니다."}  # 3은 근거에 없는 숫자라 V7 위반


class _Clock:
    """time.monotonic 대신. judge가 부를 때마다 정해 둔 초만큼 흐른다."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


@pytest.fixture
def slow_judge(monkeypatch):
    """호출마다 seconds초가 걸리고 answers를 차례로 내는 가짜 judge. 부른 횟수를 돌려준다."""
    def _use(seconds: float, answers: list[dict]) -> list:
        clock, calls = _Clock(), []
        monkeypatch.setattr(agent_router, "time", clock)

        def judge(signal_set, customs, margin, feedback=None, **kwargs):
            calls.append(feedback)
            clock.now += seconds
            answer = answers[min(len(calls), len(answers)) - 1]
            return llm.LLMAnswer(output=llm.JudgeOutput.model_validate(answer),
                                 llm=llm.LLMResult(content="", model="test/model"), prompt_version="test")
        monkeypatch.setattr(agent_router.llm, "judge", judge)
        return calls
    return _use


def _ask() -> dict:
    with TestClient(app) as client:
        return client.post("/api/agent", json=_request()).json()


def test_slow_call_is_not_retried(fake, monkeypatch, slow_judge, caplog):
    # 한 번에 40초면 한 번 더 물으면 80초라 예산(60초)을 넘는다. 다시 묻지 않고 표 등급으로 끝낸다
    fake(candidates=[_candidate(440999001)], position=POSITION)
    _signals(monkeypatch, {"eta_conflict": "triggered"})  # 표: watch (회색 지대 아님)
    calls = slow_judge(40, [BAD])

    with caplog.at_level("WARNING", logger="marvia.failure"):
        body = _ask()

    assert len(calls) == 1
    assert body["status"] == "partial" and body["verdict"] == "watch" and body["decided_by"] == "rule"
    assert body["answer"].startswith("판정 표 기준으로")
    failures = [(r.stage, r.error) for r in caplog.records if r.name == "marvia.failure"]
    assert ("judge", "time budget exceeded after 1 attempts") in failures


def test_budget_stops_before_third_call(fake, monkeypatch, slow_judge):
    # 25초씩: 두 번째는 50초 예상이라 묻고, 세 번째는 75초 예상이라 묻지 않는다
    fake(candidates=[_candidate(440999001)], position=POSITION)
    _signals(monkeypatch, {"eta_conflict": "triggered"})
    calls = slow_judge(25, [BAD])

    body = _ask()

    assert len(calls) == 2
    assert body["status"] == "partial" and body["verdict"] == "watch"


def test_fast_calls_keep_retrying_as_before(fake, monkeypatch, slow_judge):
    # 빠른 호출(10초)이면 지금처럼 위반 내용을 붙여 다시 묻고 고친 답을 쓴다
    fake(candidates=[_candidate(440999001)], position=POSITION)
    _signals(monkeypatch, {"eta_conflict": "triggered"})
    calls = slow_judge(10, [BAD, JUDGED])

    body = _ask()

    assert len(calls) == 2 and "V7" in calls[1]
    assert body["status"] == "ok" and body["answer"] == JUDGED["answer"]
