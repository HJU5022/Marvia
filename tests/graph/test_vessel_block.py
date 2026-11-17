"""판정 블록 시험 (계획 8c T4, CC7). 글은 화물 카드와 같은 함수에서 온다."""

import re
from datetime import UTC, datetime

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from marvia.graph.main import build_main_graph
from marvia.graph.schemas import Draft
from marvia.graph.vessel_text import vessel_block, vessel_lines
from marvia.tools import shipfinder
from marvia.view import _ship, _verdict  # pyright: ignore[reportPrivateUsage]

NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)


SEEN: list[str] = []


class Spy(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, *args, **kwargs):
        SEEN.append("\n".join(str(m.content) for m in messages))
        return super()._generate(messages, *args, **kwargs)


@pytest.fixture(autouse=True)
def _fresh():
    shipfinder.reset_state()


def run(agent_deps, text: str, vessel: bool = True, steps=None):
    SEEN.clear()
    model = Spy(messages=iter(steps or [AIMessage("")] * 4))
    deps = agent_deps(
        model=model,
        now=lambda: NOW,
        write=lambda p: Draft(answer="확인했어요", citations=[], next_options=[], forwarder_message=""),
    )
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore(), vessel=vessel)
    config = {"configurable": {"thread_id": "t"}}
    graph.invoke({"text": text}, config)
    return graph.get_state(config), list(SEEN)


def test_the_block_uses_the_same_words_as_the_card(agent_deps):
    state, _ = run(agent_deps, "TESTVSL0001 어디쯤 왔어요?")
    v = state.values
    card, ship = _verdict(v["verdicts"][0]), _ship(v["vessels"][0])
    (line,) = vessel_lines(v["cargos"], v["vessels"], v["verdicts"])
    for text in (
        ship["reason"],
        card["grade_label"],
        card["confidence"],
        card["schedule"],
        card["eta_source"],
    ):
        assert text in line
    assert "2026-09-24 12:00(한국 시각, 해수부 입항 예정)" in line


def test_the_block_has_no_ship_identifiers(agent_deps):
    state, seen = run(agent_deps, "TESTVSL0001 어디쯤 왔어요?")
    block = vessel_block(state.values["cargos"], state.values["vessels"], state.values["verdicts"])
    for value in ("QQTST1", "999000001", "TEST CARGO A", "26TEST0001I"):
        assert value not in block
    assert "<vessel_lines>" in seen[0] and block in seen[0]  # 차례 메시지에 붙는다


def test_two_cargos_make_two_token_lines(agent_deps):
    state, _ = run(agent_deps, "TESTVSL0001 TESTVSL0006 어디예요?")
    v = state.values
    lines = vessel_lines(v["cargos"], v["vessels"], v["verdicts"])
    assert [line.split(":")[0] for line in lines] == ["[BL1]", "[BL2]"]


def test_no_verdict_says_so_instead_of_reusing_an_old_line():
    cargos = [{"token": "[BL1]", "facts": None, "error": {"message": "x"}}]
    stale = [{"token": "[BL1]", "status": "confirmed", "reason": "mrn_call_sign"}]
    (line,) = vessel_lines(cargos, stale, [])
    assert line.startswith("[BL1]: 배 판정이 없어요")
    assert "배 확인" not in line


def test_the_block_is_absent_when_the_switch_is_off(agent_deps):
    _, seen = run(agent_deps, "TESTVSL0001 어디쯤 왔어요?", vessel=False)
    assert "vessel_lines" not in seen[0]


def test_a_landed_cargo_block_says_the_customs_stage_only(agent_deps):
    state, _ = run(agent_deps, "TESTVSL0006 어디예요?")
    v = state.values
    (line,) = vessel_lines(v["cargos"], v["vessels"], v["verdicts"])
    assert "통관 단계만으로 본 등급이에요" in line and "도착 예정:" not in line


def test_the_block_eta_is_a_kst_date_and_time():
    # UTC 00:30 도착은 한국 시각으로 같은 날 09:30이고, UTC 16:00 도착은 한국 시각 다음 날 01:00이다
    row = {
        "token": "[BL1]", "grade": "fine", "confidence": "sure", "schedule": None, "stage": None,
        "signals": [], "trusted_eta": "2026-09-23T16:00:00+00:00", "eta_source": "mof_planned",
        "margin_days": None, "notes": [], "info": [],
    }  # fmt: skip
    (line,) = vessel_lines([{"token": "[BL1]"}], [], [row])
    assert "2026-09-24 01:00(한국 시각" in line
    assert not re.search(r"2026-09-23", line)


def test_a_papers_path_cargo_with_twin_call_signs_asks_and_the_pick_stays_partial(agent_deps):
    # [왜] 11-16 결정. TESTVSL0008: MRN 신고에 호출부호가 없고 같은 호출부호(QQTWB)의 배가 둘이다.
    #      서류로 가르는 길에서도 R-147의 버튼 글이 보이고 고른 뒤 확신이 부분을 넘지 못한다
    from langgraph.types import Command

    from marvia.view import ship_texts

    SEEN.clear()
    deps = agent_deps(
        model=Spy(messages=iter([AIMessage("")] * 4)),
        now=lambda: NOW,
        write=lambda p: Draft(answer="확인했어요", citations=[], next_options=[], forwarder_message=""),
    )
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore(), vessel=True)
    config = {"configurable": {"thread_id": "twin"}}
    graph.invoke({"text": "TESTVSL0008 어디쯤 왔어요?"}, config)
    asked = graph.get_state(config)
    question = asked.values["vessel_question"]
    assert question["token"] == "[BL1]" and (question["lookup"], question["mrn_call_sign"]) == (
        "found_unsigned",
        None,
    )
    assert all(
        "같은 호출부호의 배가 여럿이에요" in v
        for k, v in ship_texts(question["candidates"]).items()
        if "info" in k
    )
    graph.invoke(Command(resume={"selected": 1}), config)
    state = graph.get_state(config)
    ship, cell = state.values["vessels"][0], state.values["verdicts"][0]
    assert (ship["status"], ship["cap"]) == ("user_choice", "partial")
    assert cell["confidence"] == "partial"
    (line,) = vessel_lines(state.values["cargos"], state.values["vessels"], state.values["verdicts"])
    assert "같은 호출부호의 배가 여럿이에요" in line and "TEST TWIN B" not in line and "QQTWB" not in line


def test_a_turn_without_a_cargo_gets_no_fragment_and_no_blank_lines_after_a_ship_was_confirmed(agent_deps):
    # [왜] 11-17 R-183. 배를 확정한 뒤 화물을 말하지 않은 차례는 화물 칸과 판정이 비고 확정 행만 남는다.
    #      블록이 없으면 쓰는 법 조각도, brief 끝의 빈 줄도 붙지 않는다
    from marvia.prompts import render

    prompts: list[str] = []
    humans: list[str] = []

    class Human(Spy):
        def _generate(self, messages, *args, **kwargs):
            humans.append(str([m.content for m in messages if m.type == "human"][-1]))
            return super()._generate(messages, *args, **kwargs)

    deps = agent_deps(
        model=Human(messages=iter([AIMessage("")] * 6)),
        now=lambda: NOW,
        write=lambda p: (
            prompts.append(p) or Draft(answer="x", citations=[], next_options=[], forwarder_message="")
        ),
    )
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore(), vessel=True)
    config = {"configurable": {"thread_id": "hi"}}
    graph.invoke({"text": "TESTVSL0001 어디쯤 왔어요?"}, config)
    assert render("vessel_write") in prompts[0] and "<vessel_lines>" in humans[0]
    graph.invoke({"text": "안녕하세요"}, config)
    values = graph.get_state(config).values
    assert values["vessels"] and not values["verdicts"]  # 확정 행만 남은 차례다
    assert render("vessel_write") not in prompts[1] and "vessel_lines" not in prompts[1]
    # brief 끝은 차례 글 틀의 끝(</question> 줄바꿈) 그대로다. 빈 줄이 더 붙지 않는다
    assert "vessel_lines" not in humans[-1] and humans[-1].endswith("</question>\n")


def test_a_cargo_without_a_verdict_is_never_filled_from_another_cargos_verdict():
    # [왜] 11-17 R-180(가). 화물 둘 중 하나만 판정이 있을 때 줄은 토큰으로 짝지어진다
    cargos = [{"token": "[BL1]", "facts": None, "error": {"message": "x"}}, {"token": "[BL2]"}]
    ships = [{"token": "[BL2]", "status": "confirmed", "reason": "mrn_call_sign"}]
    cell = {"token": "[BL2]", "grade": "act", "confidence": "sure", "schedule": None, "stage": None,
            "signals": [], "trusted_eta": None, "eta_source": None, "margin_days": None, "notes": [],
            "info": []}  # fmt: skip
    first, second = vessel_lines(cargos, ships, [cell])
    assert first.startswith("[BL1]: 배 판정이 없어요") and "긴급" not in first and "배 확인" not in first
    assert second.startswith("[BL2]: 배 확인:") and "긴급" in second
