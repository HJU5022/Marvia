"""되묻기 반복 방지 테스트 (버그 찾기).

항차·포워더 입항 예정일을 답했는데도 배를 못 가르면, 처음과 같은 "항차를 알려 달라" 문장을 되풀이하지 않는다.
외부 API 없이 test_routers의 가짜 구성(fake)을 재사용한다.
"""
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers.agent import ASK_BACK, ASK_BACK_AFTER_EVIDENCE
from backend.tests.integration.test_routers import _candidate, _request, fake  # noqa: F401  (fake는 pytest 픽스처)

TWO = [_candidate(440999001), _candidate(440999002, call_sign="TST02")]


def _post(**over) -> dict:
    with TestClient(app) as client:
        return client.post("/api/agent", json=_request(**over)).json()


def test_first_ask_back_without_evidence_keeps_original_sentence(fake):
    fake(candidates=TWO)
    body = _post()
    assert body["answer"] == ASK_BACK


@pytest.mark.parametrize("over", [{"voyage_no": "V12345"}, {"forwarder_eta": "2026-09-30"}])
def test_llm_failure_after_evidence_gets_different_sentence(fake, over):
    fake(candidates=TWO, pick=None)  # pick_vessel이 LLMError
    body = _post(**over)
    assert body["vessel_match"] == "uncertain"
    assert body["answer"] == ASK_BACK_AFTER_EVIDENCE != ASK_BACK


def test_not_high_confidence_after_voyage_gets_different_sentence(fake):
    fake(candidates=TWO, pick={"choice": 440999002, "confidence": "medium", "reasons_per_candidate": []})
    body = _post(voyage_no="VOY001")
    assert body["answer"] == ASK_BACK_AFTER_EVIDENCE
    # 화면 후보 고르기에 쓰이도록 후보와 남은 입력 칸은 그대로 돌려준다
    assert len(body["vessel_candidates"]) == 2
    assert body["missing_inputs"] == ["forwarder_eta"]
