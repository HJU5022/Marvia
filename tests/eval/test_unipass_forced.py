"""모든 평가 실행이 UNI-PASS 재생을 강제하는지 본다 (계획 3b Task 7 검토 I-1). 키·DB·네트워크 없이 돈다."""

import importlib.util
import os
import runpy
import sys

import pytest

from marvia.config import Settings
from marvia.eval.dataset import ROOT
from marvia.identify.models import CargoFacts
from marvia.tools import unipass


class Stop(Exception):
    """compare_loops가 DB에 붙기 직전에 멈추려는 표지."""


@pytest.fixture
def live_with_a_fake_key(monkeypatch):
    """소유자가 .env에 live와 키를 넣은 상황을 흉내 낸다. 실제 HTTP 클라이언트를 만들면 바로 실패한다."""
    monkeypatch.setenv("MARVIA_UNIPASS_MODE", "live")
    monkeypatch.setenv("MARVIA_UNIPASS_KEY", "TESTKEY-NOT-REAL-0001")
    # [왜] 스크립트가 os.environ을 직접 바꾼다. monkeypatch로 먼저 적어야 끝날 때 원래대로 돌아간다
    monkeypatch.setenv("MARVIA_RAG_VIA", "mcp")
    monkeypatch.setattr(unipass.httpx, "Client", lambda *a, **k: pytest.fail("실제 HTTP를 열었다"))


def test_promptfoo_provider_forces_replay_on_import(live_with_a_fake_key):
    spec = importlib.util.spec_from_file_location(
        "provider_forced", ROOT / "eval" / "promptfoo" / "provider.py"
    )
    assert spec and spec.loader
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert os.environ["MARVIA_UNIPASS_MODE"] == "replay" and Settings().unipass_mode == "replay"
    assert isinstance(unipass.lookup_cargo("DEMO0001"), CargoFacts)  # 재생 데이터가 답한다


def test_compare_loops_forces_replay_before_it_touches_anything(live_with_a_fake_key, monkeypatch):
    seen: dict = {}

    def stop_at_connect(url: str):
        seen["mode"] = os.environ["MARVIA_UNIPASS_MODE"]
        raise Stop

    monkeypatch.setattr("marvia.db.connect", stop_at_connect)
    monkeypatch.setattr(sys, "argv", ["compare_loops.py", "unused.json"])
    with pytest.raises(Stop):
        runpy.run_path(str(ROOT / "scripts" / "compare_loops.py"), run_name="__main__")
    assert seen["mode"] == "replay"


def test_eval_runs_use_the_direct_rag_path_even_if_the_environment_says_mcp(monkeypatch, tmp_path):
    # [왜] 평가의 graph_added는 리랭커 앞 그래프 후보 수여야 한다. mcp 길은 리랭커 뒤 상위 n개만 보인다
    #      (계획 3b 최종 검토 I-1)
    monkeypatch.setenv("MARVIA_RAG_VIA", "mcp")
    monkeypatch.setenv("MARVIA_GRAPH", "off")
    seen: list[str] = []

    def stop_at_connect(url: str):
        seen.append(os.environ["MARVIA_RAG_VIA"] + "/" + Settings().rag_via)
        raise Stop

    monkeypatch.setattr("marvia.db.connect", stop_at_connect)
    for script, argv in (
        ("run_eval.py", ["run", "--out", str(tmp_path / "o"), "--commit", "t", "--graph", "off"]),
        ("compare_loops.py", ["unused.json"]),
    ):
        monkeypatch.setattr(sys, "argv", [script, *argv])
        with pytest.raises(Stop):
            runpy.run_path(str(ROOT / "scripts" / script), run_name="__main__")
    assert seen == ["direct/direct", "direct/direct"]
