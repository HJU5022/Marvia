"""날짜 받기 도구 note_dates 시험 (계획 8c T3, CC4, 결정 C5·C11·C12, D16·D20·D21). 키 없이 돈다."""

from datetime import UTC, date, datetime

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from marvia.graph import vessel
from marvia.graph.main import build_main_graph
from marvia.graph.schemas import Draft
from marvia.graph.tools import make_tools
from marvia.tools import shipfinder
from marvia.tools.deadlines import KST

# 한국 시각 09-22 12:00. 재생 배의 마지막 위치 수신 30분 뒤. 공용 fixture의 오늘(2026-11-02)과 다르다
NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def say(*calls: tuple[str, dict]) -> AIMessage:
    return AIMessage(
        "", tool_calls=[{"name": n, "args": a, "id": f"c{i}-{n}"} for i, (n, a) in enumerate(calls)]
    )


def note(token="[BL1]", **fields) -> tuple[str, dict]:
    return ("note_dates", {"token": token, **fields})


@pytest.fixture(autouse=True)
def _fresh():
    shipfinder.reset_state()


def graph_on(agent_deps, *script: AIMessage, now=NOW, write=None):
    def default_write(prompt):
        return Draft(answer="확인했어요", citations=[], next_options=[], forwarder_message="")

    deps = agent_deps(model=ToolModel(messages=iter(script)), now=lambda: now, write=write or default_write)
    return build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore(), vessel=True)


def turn(graph, text: str, thread: str = "t"):
    config = {"configurable": {"thread_id": thread}}
    graph.invoke({"text": text}, config)
    return graph.get_state(config)


def results(state) -> list[str]:
    return [m.content for m in state.values["messages"] if m.type == "tool"]


def test_a_date_the_user_wrote_this_turn_is_accepted(agent_deps):
    graph = graph_on(agent_deps, say(note(sale_date="2026-09-30")), say())
    state = turn(graph, "TESTVSL0001 판매는 9월 30일에 해요")
    assert state.values["cargo_dates"] == {"[BL1]": {"sale_date": "2026-09-30"}}
    # 받은 값을 되풀이해 사용자가 틀린 역할을 알아챌 수 있게 한다
    assert results(state) == ["판매 예정일 2026-09-30(말씀하신 날)로 받았어요"]


def test_a_date_not_in_this_turns_text_is_refused(agent_deps):
    graph = graph_on(agent_deps, say(note(sale_date="2026-09-30")), say())
    state = turn(graph, "TESTVSL0001 언제 도착해요?")
    assert not state.values.get("cargo_dates")
    assert "말씀하신 글에 없는" in results(state)[0] or "사용자가 쓴 글에 없는" in results(state)[0]


def test_a_relative_expression_is_refused_with_a_reason_the_model_can_relay(agent_deps):
    graph = graph_on(agent_deps, say(note(sale_date="2026-09-23")), say())
    state = turn(graph, "TESTVSL0001 내일 팔 거예요")
    assert not state.values.get("cargo_dates")
    assert "내일이나 다음 주 같은 말은 받지 않아요" in results(state)[0]
    assert "날짜(예: 11월 20일)로" in results(state)[0]


def test_a_date_only_in_an_earlier_turn_is_refused(agent_deps):
    graph = graph_on(agent_deps, say(), say(note(sale_date="2026-09-30")), say())
    turn(graph, "TESTVSL0001 판매는 9월 30일에 해요")
    state = turn(graph, "그 화물은 어디쯤이에요?")
    assert not state.values.get("cargo_dates")
    assert "받지 않았어요" in results(state)[-1]


def test_an_unknown_token_is_refused(agent_deps):
    graph = graph_on(agent_deps, say(note(token="[BL9]", sale_date="2026-09-30")), say())
    state = turn(graph, "TESTVSL0001 판매는 9월 30일에 해요")
    assert results(state) == ["[BL9]: 모르는 토큰이에요"]
    assert not state.values.get("cargo_dates")


def test_out_of_range_is_refused(agent_deps):
    graph = graph_on(agent_deps, say(note(sale_date="2030-01-01")), say())
    state = turn(graph, "TESTVSL0001 판매는 2030-01-01에 해요")
    assert not state.values.get("cargo_dates")
    assert "너무 먼 날짜" in results(state)[0]


def test_a_malformed_date_is_refused(agent_deps):
    graph = graph_on(agent_deps, say(note(sale_date="9월 30일")), say())
    state = turn(graph, "TESTVSL0001 판매는 9월 30일에 해요")
    assert not state.values.get("cargo_dates")
    assert "YYYY-MM-DD" in results(state)[0]


def test_a_second_call_replaces_the_value(agent_deps):
    graph = graph_on(agent_deps, say(note(sale_date="2026-09-30")), say(note(sale_date="2026-10-05")), say())
    state = turn(graph, "TESTVSL0001 판매는 9월 30일이라고 했다가 10월 5일로 바꿔요")
    assert state.values["cargo_dates"] == {"[BL1]": {"sale_date": "2026-10-05"}}


def test_only_the_accepted_fields_are_written(agent_deps):
    graph = graph_on(agent_deps, say(note(sale_date="2026-09-30", forwarder_eta="2026-09-25")), say())
    state = turn(graph, "TESTVSL0001 판매는 9월 30일에 해요")
    assert state.values["cargo_dates"] == {"[BL1]": {"sale_date": "2026-09-30"}}
    text = results(state)[0]
    assert (
        "판매 예정일 2026-09-30(말씀하신 날)" in text
        and "포워더가 알려 준 도착 예정일: 사용자가 쓴 글에 없는" in text
    )


def test_the_sale_date_reaches_the_judge_and_changes_the_margin_grade(agent_deps):
    # TESTVSL0001의 믿을 도착 예정은 해수부 입항 예정 09-24 12:00(한국 시각)이다
    plain = turn(graph_on(agent_deps, say()), "TESTVSL0001 어디쯤 왔어요?").values["verdicts"][0]
    assert plain["margin_days"] is None and "no_sale_date" in plain["info"]
    graph = graph_on(agent_deps, say(note(sale_date="2026-09-30")), say(), say())
    turn(graph, "TESTVSL0001 판매는 9월 30일에 해요", "d")
    cell = turn(graph, "TESTVSL0001 어디쯤 왔어요?", "d").values["verdicts"][0]
    assert cell["margin_days"] == 6 and "no_sale_date" not in cell["info"]  # 09-24 도착, 09-30 판매
    # 여유 일수가 줄면 같은 도착 예정에서 등급이 달라진다(판매 예정일이 도착 예정 바로 다음 날)
    close = graph_on(agent_deps, say(note(sale_date="2026-09-25")), say(), say())
    turn(close, "TESTVSL0001 판매는 9월 25일에 해요", "c")
    tight = turn(close, "TESTVSL0001 어디쯤 왔어요?", "c").values["verdicts"][0]
    assert tight["margin_days"] == 1 and tight["grade"] != cell["grade"]


def test_first_eta_is_read_as_that_days_noon_in_korea(agent_deps, monkeypatch):
    seen = []
    real = vessel.judge
    monkeypatch.setattr(vessel, "judge", lambda *a, **k: (seen.append(k), real(*a, **k))[1])
    graph = graph_on(agent_deps, say(note(first_eta="2026-09-23")), say(), say())
    state = turn(graph, "TESTVSL0001 처음엔 9월 23일 도착이라고 했어요", "f")
    assert "낮 12시(한국 시각)로 봤어요" in results(state)[0]
    turn(graph, "TESTVSL0001 어디쯤 왔어요?", "f")
    assert seen[-1]["first_eta"] == datetime(2026, 9, 23, 12, tzinfo=KST)


def test_the_tool_exists_only_when_the_switch_is_on():
    assert "note_dates" not in {t.name for t in make_tools(None, date.today)}
    assert "note_dates" in {t.name for t in make_tools(None, date.today, vessel=True)}


ASK = (
    "ask_user",
    {
        "question": "판매 예정일이 언제예요?",
        "options": [
            {"label": "2026-09-30", "description": "이번 달 말"},
            {"label": "2026-10-05", "description": "다음 주"},
        ],
    },
)


def ask_then_note(agent_deps, date_text, token_date, selected=None):
    graph = graph_on(agent_deps, say(ASK), say(note(sale_date=token_date)), say())
    config = {"configurable": {"thread_id": "a"}}
    graph.invoke({"text": "TESTVSL0001 판매 예정일을 정해야 해요"}, config)
    resume = {"selected": selected} if selected is not None else {"custom": date_text}
    graph.invoke(Command(resume=resume), config)
    return graph.get_state(config)


def test_a_date_the_user_typed_into_an_ask_user_card_this_turn_is_accepted(agent_deps):
    state = ask_then_note(agent_deps, "11월 20일이요", "2026-11-20")
    assert state.values["cargo_dates"] == {"[BL1]": {"sale_date": "2026-11-20"}}


def test_a_date_only_in_a_picked_option_is_refused(agent_deps):
    state = ask_then_note(agent_deps, "", "2026-09-30", selected=0)
    assert not state.values.get("cargo_dates")
    assert state.values["turn_answers"] == []


def test_turn_answers_reaches_the_parent_through_a_real_ask_user_resume(agent_deps):
    state = ask_then_note(agent_deps, "11월 20일이요", "2026-11-20")
    assert state.values["turn_answers"] == ["11월 20일이요"]


def test_a_card_answer_from_an_earlier_turn_is_refused_in_a_turn_without_cargo(agent_deps):
    graph = graph_on(agent_deps, say(ASK), say(), say(note(sale_date="2026-11-20")), say())
    config = {"configurable": {"thread_id": "e"}}
    graph.invoke({"text": "TESTVSL0001 판매 예정일을 정해야 해요"}, config)
    graph.invoke(Command(resume={"custom": "11월 20일이요"}), config)
    graph.invoke({"text": "그 날짜로 해 주세요"}, config)
    state = graph.get_state(config)
    assert not state.values.get("cargo_dates")
    assert state.values["turn_answers"] == []
    assert "받지 않았어요" in results(state)[-1]


def test_two_note_dates_calls_in_one_message_both_survive(agent_deps):
    both = say(note(sale_date="2026-09-30"), note(forwarder_eta="2026-09-25"))
    state = turn(graph_on(agent_deps, both, say()), "TESTVSL0001 판매 9월 30일, 포워더는 9월 25일이래요")
    assert state.values["cargo_dates"] == {
        "[BL1]": {"sale_date": "2026-09-30", "forwarder_eta": "2026-09-25"}
    }


def test_a_year_less_date_is_read_against_the_turns_clock_not_the_real_today(agent_deps):
    # 판정의 기준 시각은 2026-09-22다. 실제 오늘(이 시험을 돌리는 날)로 읽으면 내년이 될 수 있다
    state = turn(
        graph_on(agent_deps, say(note(sale_date="2026-09-25")), say()), "TESTVSL0001 9월 25일에 팔아요"
    )
    assert state.values["cargo_dates"] == {"[BL1]": {"sale_date": "2026-09-25"}}


def test_an_on_graph_built_like_the_server_reads_today_from_now_in_kst(agent_deps):
    # [왜] 서버처럼 today는 덮어쓰지 않고 now만 준다. now = 2026-09-26 16:00 UTC는 한국 시각 09-27 01:00이라
    #      실제 날짜, fixture의 today(2026-11-02), UTC 날짜(09-26), 이 화물의 단계 날짜(09-22)와 모두 다르다
    seen: list[str] = []

    class Spy(ToolModel):
        def _generate(self, messages, *args, **kwargs):
            seen.append(" ".join(str(m.content) for m in messages))
            return super()._generate(messages, *args, **kwargs)

    deps = agent_deps(
        model=Spy(messages=iter([say(note(sale_date="2026-09-29")), say()])),
        now=lambda: datetime(2026, 9, 26, 16, 0, tzinfo=UTC),
        write=lambda p: Draft(
            answer="오늘은 2026-09-27예요", citations=[], next_options=[], forwarder_message=""
        ),
    )
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore(), vessel=True)
    state = turn(graph, "TESTVSL0001 9월 29일에 팔아요")
    assert "Today is 2026-09-27" in seen[0]  # brief의 Today
    assert state.values["cargo_dates"] == {"[BL1]": {"sale_date": "2026-09-29"}}  # 연도 없는 날짜
    assert state.values["verification"] == []  # 검증자가 허용하는 오늘
