"""지시문 조각과 작성자·에이전트 입력 시험 (계획 8c T6, CC9, CC1)."""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from marvia.graph.main import build_main_graph
from marvia.graph.schemas import Draft
from marvia.prompts import render
from marvia.tools import shipfinder

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)
SYSTEM: list[str] = []


class Spy(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, *args, **kwargs):
        content = next(m.content for m in messages if m.type == "system")
        SYSTEM.append(content if isinstance(content, str) else "".join(b["text"] for b in content))
        return super()._generate(messages, *args, **kwargs)


@pytest.fixture(autouse=True)
def _fresh():
    shipfinder.reset_state()
    SYSTEM.clear()


def run(agent_deps, loop: str, vessel: bool, text: str = "TESTVSL0001 어디쯤 왔어요?"):
    written: list[str] = []

    def write(prompt):
        written.append(prompt)
        return Draft(answer="확인했어요", citations=[], next_options=[], forwarder_message="")

    deps = agent_deps(model=Spy(messages=iter([AIMessage("")] * 4)), now=lambda: NOW, write=write)
    graph = build_main_graph(deps, InMemorySaver(), loop=loop, store=InMemoryStore(), vessel=vessel)
    graph.invoke({"text": text}, {"configurable": {"thread_id": "t"}})
    return written


def test_the_fragments_are_added_only_when_the_switch_is_on(agent_deps):
    run(agent_deps, "agent", True)
    assert SYSTEM[0].startswith(
        render("agent") + "\n\n" + render("vessel_agent")
    )  # 뒤에는 할 일 미들웨어의 글이 붙는다
    SYSTEM.clear()
    run(agent_deps, "agent", False)
    assert SYSTEM[0].startswith(render("agent")) and "Ship verdicts" not in SYSTEM[0]  # 꺼지면 그대로다


def test_the_fragments_have_no_ship_identifiers_or_numbers():
    for name in ("vessel_agent", "vessel_write"):
        text = (ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")
        assert not re.search(r"QQ|999\d|TEST CARGO|TESTVSL|DEMO\d|[A-Z0-9]{8,}", text), name
        assert "\u2014" not in text, name


def test_the_off_prompts_are_unchanged(agent_deps):
    # 해시로 묶은 값은 test_vessel_off.py의 MODEL_SHA다. 여기서는 작성자 입력에 조각과 블록이 없음을 본다
    for loop in ("planner", "agent"):
        (prompt, *_) = run(agent_deps, loop, False)
        assert "vessel_lines" not in prompt and "Ship verdicts" not in prompt


@pytest.mark.parametrize("loop", ["planner", "agent"])
def test_the_writer_input_has_the_block_when_a_verdict_exists(agent_deps, loop):
    (prompt, *_) = run(agent_deps, loop, True)
    assert render("vessel_write") in prompt and "<vessel_lines>\n[BL1]: 배 확인:" in prompt
    assert "QQTST1" not in prompt and "TEST CARGO A" not in prompt


def test_the_supervisor_path_gets_no_fragment_and_no_block(agent_deps):
    # [왜] 수퍼바이저 길에는 새 도구를 주지 않는다 (C9). 그 길의 모델 입력과 작성자 입력에는 조각이 없다
    (prompt, *_) = run(agent_deps, "supervisor", True)
    assert SYSTEM and not any("Ship verdicts" in s for s in SYSTEM)
    assert "vessel_lines" not in prompt and "Ship verdicts" not in prompt
