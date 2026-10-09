"""서류 대조 데모 10건 테스트 (임시). evals/fixtures/demo_papers.jsonl을 키 없이 실제 요청 경로로 돌린다.

scripts/demo/make_demo.build_with_papers가 쓴 재생 파일로 routers/agent.run_agent를 부른다 (test_demo.py와 같은 방식).
지금 서버 데모(build_all)는 라이브 10건이라 이 10건을 안 쓴다. 서류 대조 기능 확인용으로 여기서만 쓴다.
LLM 키가 없어 판정 문장은 녹화 답이나 폴백이 될 수 있다. 그래서 식별 단계 결과(status, vessel_match,
확정한 MMSI와 근거 한 줄)만 본다. 판정 등급은 보지 않는다.
재생 폴더는 tmp_path에 만든다. 레포의 evals/fixtures/replay/는 건드리지 않는다.
값은 전부 모의값이다 (TESTBL41~50, TEST TWIN, MMSI 440999xxx, 호출부호 TST, CLAUDE.md).
"""
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.clients import replay
from backend.app.clients.shipfinder import ShipFinderClient
from scripts.demo import make_demo

ROOT = Path(__file__).resolve().parents[3]
RECORDING = ROOT / "evals" / "fixtures" / "replay" / "llm" / "marvia-judge.json"
CASES = make_demo.load_papers()
# 키·DB·MCP 서버 없이 돈다. Dockerfile이 MCP_URL을 박아 두므로 같이 지운다 (test_demo.py와 같은 목록)
KEYS = ("LLM_MODEL", "OPENROUTER_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
        "DATABASE_URL", "SHIPFINDER_KEY", "UNIPASS_KEY", "DATA_GO_KR_KEY", "MCP_URL")


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    """재생 파일을 한 번만 만들고 10건이 같이 쓴다. 데모처럼 13건을 한 폴더에 쓴 상태로 돌린다."""
    out = tmp_path_factory.mktemp("replay")
    with pytest.MonkeyPatch.context() as mp:
        for key in KEYS:
            mp.delenv(key, raising=False)
        mp.setenv("REPLAY_MODE", "true")
        mp.setattr(replay, "REPLAY_DIR", out)
        ShipFinderClient.cache.clear()
        (out / "llm").mkdir()
        shutil.copy(RECORDING, out / "llm" / RECORDING.name)
        three, papers = make_demo.build_with_papers(datetime.now(timezone.utc), out)
        yield {g["case_id"]: g for g in three}, {g["case_id"]: g for g in papers}
    ShipFinderClient.cache.clear()


def _ask(g: dict):
    from backend.app.routers import agent
    from backend.app.schemas.agent import AgentRequest

    return agent.run_agent(AgentRequest(bl_no=g["bl_no"], bl_type="HOUSE", session_id=f"demo-{g['case_id']}",
                                        sale_due_date=g["sale_due_date"]))


def test_ten_cases_marked_as_mock():
    # 평가셋과 겹치지 않는 모의 번호만 쓴다
    assert [c["request"]["bl_no"] for c in CASES] == [f"TESTBL{n}" for n in range(41, 51)]
    assert all(c["category"] == "demo_papers" and c["labeler"] is None for c in CASES)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_papers_case(demo, case):
    _, papers = demo
    g = papers[case["id"]]
    response = _ask(g)
    assert response.vessel_match == case["expected_vessel_match"]
    if case["expected_vessel_match"] == "confirmed":
        # 확정한 배 1척과 서류 대조 근거 한 줄 (services/judge/identify.match_by_papers가 만드는 문장)
        assert response.status not in ("insufficient", "failed")
        assert [c.mmsi for c in response.vessel_candidates] == [case["expected_mmsi"]]
        day = datetime.strptime(g["entry_date"], "%Y%m%d").date().isoformat()
        reason = f"세관 입항일({day})·적재항({g['loading_port']})과 해수부 입항 신고가 일치"
        assert reason in response.vessel_candidates[0].match_reasons
    else:
        assert response.status == case["expected_status"]
        assert response.missing_inputs == case["expected_missing_inputs"]
        assert len(response.vessel_candidates) == 2  # 두 후보를 다 보여 주고 고르게 한다


def test_korean_mof_name_keeps_mof_eta(demo):
    # P48: 해수부 선명이 한글(국적선)이어도 호출부호로 이은 입항 예정을 버리지 않는다 (port_schedule._same_ship).
    # 전에는 선명으로 다시 걸러 해수부 입항 예정이 빠지고 partial로 끝났다
    _, papers = demo
    response = _ask(papers["P48"])
    assert response.status == "ok"
    assert response.eta.mof_eta is not None


def test_confirmed_response_fills_vessel(demo):
    # 확정한 배는 vessel 칸(C1 VesselInfo)에 담긴다 (전에는 확정 경로에서 늘 null, routers/agent._vessel_info)
    _, papers = demo
    vessel = _ask(papers["P48"]).vessel
    assert (vessel.mmsi, vessel.call_sign, vessel.name, vessel.flag) == (440999481, "TST481", "TEST TWIN 48", "KR")


def test_existing_three_unchanged(demo):
    # 10건을 같이 써도 기존 데모 3건의 결과는 그대로다 (해수부 _ALL.xml은 이어 붙는다, evals/replay_fixtures._write_all)
    three, _ = demo
    normal = _ask(three["N01"])
    assert (normal.status, normal.verdict, normal.days_margin) == ("ok", "fine", 4)
    assert _ask(three["B01"]).status == "insufficient"
    assert _ask(three["F04"]).status == "partial"
