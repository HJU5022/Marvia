"""키 없는 데모 테스트 (SDD 6.1). scripts/demo/make_demo.py의 날짜 옮기기와 services/llm.py의 녹화 답 재생을 본다.

마지막 테스트는 데모 3건을 실제 요청 경로(routers/agent.run_agent)로 끝까지 돌려서
키·DB 없이 정상 fine · 되묻기 insufficient · 실패 partial이 나오는지 확인한다.
재생 폴더는 tmp_path에 만든다. 레포의 evals/fixtures/replay/는 건드리지 않는다.
"""
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.app.clients import replay
from backend.app.clients.shipfinder import ShipFinderClient
from backend.app.services import llm
from backend.app.services.judge.evidence import KST
from scripts.demo import make_demo

ROOT = Path(__file__).resolve().parents[3]
RECORDING = ROOT / "evals" / "fixtures" / "replay" / "llm" / "marvia-judge.json"
NOW = datetime(2026, 10, 3, 21, 15, tzinfo=timezone.utc)  # 한국 시각 10-04 06:15. 날짜가 바뀌는 시간대도 여유 일수가 같아야 한다


def _record(case_id: str) -> dict:
    lines = (ROOT / "evals" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
    return next(r for r in map(json.loads, lines) if r["id"] == case_id)


def test_shift_keeps_position_age_and_margin():
    shifted = make_demo.shift_record(_record("N01"), NOW)
    position = shifted["fixtures"]["shipfinder"]["position"]
    # 평가셋에서 위치는 clock 30분 전 수신이다. 옮긴 뒤에도 "지금 30분 전"이어야 오래된 위치가 되지 않는다
    assert datetime.fromtimestamp(position["last_time"], timezone.utc) == NOW - timedelta(minutes=30)
    # 여유 일수 = 판매 예정일 - 해수부 입항 예정일(한국 날짜). 평가셋 N01은 4일
    eta = datetime.fromisoformat(shifted["fixtures"]["mof"]["arrival_reports"][0]["etryptDt"]).astimezone(KST).date()
    assert (date.fromisoformat(shifted["request"]["sale_due_date"]) - eta).days == 4


def test_f04_uses_its_own_vessel():
    # N01과 같은 배(MMSI)면 한 재생 폴더에 정상 위치와 권한 없음을 같이 둘 수 없다
    renamed = json.dumps(make_demo.rename_vessel(_record("F04"), make_demo.F04_RENAME))
    assert "440999001" not in renamed and "TEST CARGO A" not in renamed


def test_build_writes_three_cases(tmp_path):
    guide = make_demo.build(NOW, tmp_path)
    assert [g["bl_no"] for g in guide] == ["TESTBL26", "TESTBL04", "TESTBL01"]
    for bl in ("TESTBL01", "TESTBL04", "TESTBL26"):
        assert (tmp_path / "unipass" / f"{bl}.xml").is_file()
    ok = json.loads((tmp_path / "shipfinder" / "VesselPositionSingle" / "440999001.json").read_text())
    denied = json.loads((tmp_path / "shipfinder" / "VesselPositionSingle" / "440999004.json").read_text())
    assert ok["status"] == 0 and denied["status"] == 21


# ── 녹화 답 재생 (services/llm.py _replay_answer) ─────────────────

@pytest.fixture
def recorded(tmp_path, monkeypatch):
    """REPLAY_MODE, LLM_MODEL 없음, 재생 폴더에 녹화 답 파일만 둔다."""
    monkeypatch.setenv("REPLAY_MODE", "true")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setattr(replay, "REPLAY_DIR", tmp_path)
    (tmp_path / "llm").mkdir()
    shutil.copy(RECORDING, tmp_path / "llm" / RECORDING.name)
    return json.loads(RECORDING.read_text(encoding="utf-8"))


def _judge_input(recording: dict) -> str:
    signals = [{"id": key, "state": state} for key, state in recording["match"]["signals"].items()]
    return json.dumps({"signals": signals, "days_margin": recording["match"]["days_margin"]})


def test_replay_returns_recorded_answer(recorded):
    answer = llm._replay_answer(llm.JUDGE_PROMPT, _judge_input(recorded[0]), llm.JudgeOutput)
    assert answer.output.answer == recorded[0]["output"]["answer"]
    assert answer.prompt_version == "replay" and answer.llm.model.startswith("replay/")


def test_replay_refuses_other_input(recorded):
    # 판매일을 다르게 넣어 여유 일수가 달라지면 녹화 답("4일 일찍")은 틀린 말이 된다. 쓰지 않는다
    other = dict(recorded[0], match=dict(recorded[0]["match"], days_margin=8))
    with pytest.raises(llm.LLMError) as e:
        llm._replay_answer(llm.JUDGE_PROMPT, _judge_input(other), llm.JudgeOutput)
    assert e.value.kind == "not_configured"


def test_model_set_calls_real_llm(recorded, monkeypatch):
    # LLM_MODEL이 있으면 재생 모드에서도 녹화 답이 아니라 진짜 모델을 부른다
    monkeypatch.setenv("LLM_MODEL", "some/model")

    def fake_chat(*args, **kwargs):
        raise llm.LLMError("real call")

    monkeypatch.setattr(llm, "chat", fake_chat)
    with pytest.raises(llm.LLMError, match="real call"):
        llm._ask_json(llm.JUDGE_PROMPT, _judge_input(recorded[0]), "judge", llm.JUDGE_SCHEMA, llm.JudgeOutput, None)


# ── 데모 3건 끝까지 ──────────────────────────────────────────

def test_demo_cases_end_to_end(tmp_path, monkeypatch):
    from backend.app.routers import agent
    from backend.app.schemas.agent import AgentRequest

    for key in ("LLM_MODEL", "OPENROUTER_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
                "DATABASE_URL", "SHIPFINDER_KEY", "UNIPASS_KEY", "DATA_GO_KR_KEY",
                "MCP_URL"):  # Dockerfile이 MCP_URL을 박아 둔다. 남아 있으면 없는 서버에 HTTP로 붙다가 partial이 된다
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("REPLAY_MODE", "true")
    monkeypatch.setattr(replay, "REPLAY_DIR", tmp_path)
    ShipFinderClient.cache.clear()
    (tmp_path / "llm").mkdir()
    shutil.copy(RECORDING, tmp_path / "llm" / RECORDING.name)
    # 서버가 실제로 쓰는 "지금"으로 만든다. 데모도 만든 직후에 조회한다
    guide = {g["case_id"]: g for g in make_demo.build(datetime.now(timezone.utc), tmp_path)}

    def ask(case_id: str, with_sale_date: bool = True):
        g = guide[case_id]
        return agent.run_agent(AgentRequest(bl_no=g["bl_no"], bl_type="HOUSE", session_id=f"demo-{case_id}",
                                            sale_due_date=g["sale_due_date"] if with_sale_date else None))

    normal = ask("N01")
    assert (normal.status, normal.verdict, normal.days_margin) == ("ok", "fine", 4)
    assert ask("N01", with_sale_date=False).verdict == "fine"  # 판매일을 비워도 녹화 답이 있다
    assert ask("B01").status == "insufficient"
    assert ask("F04").status == "partial"


def test_no_recording_is_not_configured(recorded):
    # 녹화가 없는 프롬프트는 입력이 JSON이 아니어도(서류 OCR 글자) 키 없을 때와 같은 실패로 끝난다
    with pytest.raises(llm.LLMError) as e:
        llm._replay_answer("marvia-doc-extract", "B/L 사진 글자", llm.DocFieldsOutput)
    assert e.value.kind == "not_configured"
