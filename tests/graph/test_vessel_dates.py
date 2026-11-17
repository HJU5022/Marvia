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
    assert results(state)[0].startswith("판매 예정일 2026-09-30(말씀하신 날)로 받았어요")


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


def server_like(agent_deps, script, written=None):
    """서버처럼 today는 덮어쓰지 않고 now만 준 켠 그래프. now = 09-26 16:00 UTC(한국 09-27)."""

    def write(prompt):
        if written is not None:
            written.append(prompt)
        return Draft(answer="확인했어요", citations=[], next_options=[], forwarder_message="")

    deps = agent_deps(
        model=ToolModel(messages=iter(script)),
        now=lambda: datetime(2026, 9, 26, 16, 0, tzinfo=UTC),
        write=write,
    )
    return build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore(), vessel=True)


def test_note_dates_reads_a_year_less_date_on_the_korean_date_not_the_utc_date(agent_deps):
    # [왜] 11-17 R-175(P3). "9월 19일"은 한국 날짜(09-27)로 8일 지나 내년이고
    #      UTC 날짜(09-26)로는 7일이라 올해다. 모델이 넘긴 2027-09-19는 한국 날짜로 읽을 때만 받는다
    graph = server_like(agent_deps, [say(note(sale_date="2027-09-19")), say()])
    state = turn(graph, "TESTVSL0001 9월 19일에 팔아요")
    assert state.values["cargo_dates"] == {"[BL1]": {"sale_date": "2027-09-19"}}


def test_the_writers_prompt_has_todays_korean_date_from_now(agent_deps):
    # [왜] 11-17 R-175(P4). 작성자 프롬프트의 Today도 시계 하나(now의 한국 날짜)에서 와야 한다
    written: list[str] = []
    turn(server_like(agent_deps, [say()], written), "TESTVSL0001 언제 와요?")
    assert "Today is 2026-09-27" in written[0]


def test_a_forwarder_date_from_the_users_text_reaches_the_judge(agent_deps, monkeypatch):
    # [왜] 11-17 R-176. TESTVSL0001은 해수부 입항 예정이 있어 포워더 날이 판정 값을 바꾸지 않는다.
    #      그래서 first_eta 시험처럼 judge 인자를 엿본다
    seen = []
    real = vessel.judge
    monkeypatch.setattr(vessel, "judge", lambda *a, **k: (seen.append(k), real(*a, **k))[1])
    graph = graph_on(agent_deps, say(note(forwarder_eta="2026-09-26")), say(), say())
    state = turn(graph, "TESTVSL0001 포워더는 9월 26일 도착이라고 했어요", "g")
    assert "포워더가 알려 준 도착 예정일 2026-09-26(말씀하신 날)" in results(state)[0]
    turn(graph, "TESTVSL0001 어디쯤 왔어요?", "g")
    assert seen[-1]["forwarder_eta"] == date(2026, 9, 26)


def test_ask_user_writes_turn_answers_only_when_the_switch_is_on(monkeypatch):
    # [왜] 11-17 R-177. 꺼진 길은 루프 공책에 그 칸이 없어 써도 버려지니 공책 시험으로는 못 본다.
    #      도구가 돌려준 Command.update를 직접 본다 (MC34)
    from types import SimpleNamespace

    from marvia.graph import tools

    monkeypatch.setattr(tools, "interrupt", lambda payload: {"custom": "11월 20일이요"})
    options = [tools.Choice(label="가", description="가"), tools.Choice(label="나", description="나")]
    runtime = SimpleNamespace(state={"mask_map": {}}, tool_call_id="x", config={})
    for vessel_on in (False, True):
        ask = next(t for t in make_tools(None, date.today, vessel=vessel_on) if t.name == "ask_user")
        out = ask.func(question="날짜?", options=options, runtime=runtime)  # type: ignore[attr-defined]
        assert ("turn_answers" in out.update) is vessel_on
        assert out.update.get("turn_answers", ["11월 20일이요"]) == ["11월 20일이요"]


def test_the_on_planner_path_uses_the_one_clock_for_the_search_date_and_the_deadline_calc(
    agent_deps, fake_rag
):
    # [왜] 11-17 R-178. 켠 길은 계획자 길의 search_law as_of와 calc의 오늘도 now의 한국 날짜(09-27)다.
    #      꺼진 길은 deps.today(fixture의 2026-11-02) 그대로다
    from dataclasses import replace

    from marvia.graph.schemas import Plan, Step

    def run_planner(vessel: bool) -> tuple[list[date], dict]:
        asked: list[date] = []
        rag = fake_rag()
        rag = replace(rag, search=lambda query, as_of: (asked.append(as_of), rag_search(query, as_of))[1])
        rag_search = fake_rag().search
        plans = iter(
            [
                Plan(steps=[Step(action="search_law", query="수입신고 기한", reason="찾는다")]),
                Plan(steps=[Step(action="calc", query="", reason="계산한다")]),
                Plan(steps=[Step(action="write", query="", reason="쓴다")]),
            ]
        )
        deps = agent_deps(
            rag=rag,
            plan=lambda prompt: next(plans),
            now=lambda: datetime(2026, 9, 26, 16, 0, tzinfo=UTC),
        )
        graph = build_main_graph(deps, InMemorySaver(), loop="planner", store=InMemoryStore(), vessel=vessel)
        config = {"configurable": {"thread_id": f"p{vessel}"}}
        graph.invoke({"text": "DEMO0001 수입신고 기한이 언제예요?"}, config)
        return asked, graph.get_state(config).values["calc"]

    for vessel_on, today in ((True, date(2026, 9, 27)), (False, date(2026, 11, 2))):
        asked, calc = run_planner(vessel_on)
        assert set(asked) == {today}
        cell = calc["deadlines"][0]
        assert cell["days_left"] == (date.fromisoformat(cell["due"]) - today).days


def test_the_on_supervisor_subagent_turn_gets_the_korean_date_of_now_as_today(agent_deps):
    # [왜] 11-17 R-178(수퍼바이저). 켠 길이면 서브에이전트 차례 글의 Today도 now의 한국 날짜(09-27)다.
    #      fixture의 today(2026-11-02)가 아니다
    seen: list[str] = []

    class Spy(ToolModel):
        def _generate(self, messages, *args, **kwargs):
            seen.append("\n".join(str(m.content) for m in messages))
            return super()._generate(messages, *args, **kwargs)

    script = [say(("handoff", {"to": "law", "task": "조문 찾기"})), say(), say(), say()]
    deps = agent_deps(
        model=Spy(messages=iter(script)),
        now=lambda: datetime(2026, 9, 26, 16, 0, tzinfo=UTC),
        write=lambda p: Draft(answer="확인했어요", citations=[], next_options=[], forwarder_message=""),
    )
    graph = build_main_graph(deps, InMemorySaver(), loop="supervisor", store=InMemoryStore(), vessel=True)
    graph.invoke({"text": "TESTVSL0001 조문을 찾아 줘"}, {"configurable": {"thread_id": "s"}})
    sub_turns = [s for s in seen if "조문 찾기" in s and "Today is" in s]
    assert sub_turns and all("Today is 2026-09-27" in s and "2026-11-02" not in s for s in sub_turns)


def test_a_date_accepted_this_turn_changes_the_grade_in_the_same_turn_without_new_outside_calls(
    agent_deps, monkeypatch
):
    # [왜] 11-17 R-184. verdict 노드는 루프보다 먼저 돈다. 이번 차례에 받은 날짜는
    #      루프 뒤 rejudge가 같은 시계로
    #      다시 판정해, 카드와 작성자 블록이 새 값을 보인다. 위치·일정은 이번 차례에 받은 것을 다시 쓴다
    from marvia.graph.vessel_text import vessel_lines
    from marvia.tools import mof

    calls = []
    real_pos, real_plan = shipfinder.vessel_position, mof.port_schedule
    monkeypatch.setattr(
        shipfinder, "vessel_position", lambda *a, **k: (calls.append("pos"), real_pos(*a, **k))[1]
    )
    monkeypatch.setattr(mof, "port_schedule", lambda *a, **k: (calls.append("plan"), real_plan(*a, **k))[1])
    written: list[str] = []
    graph = graph_on(
        agent_deps,
        say(note(sale_date="2026-09-25")),
        say(),
        write=lambda p: (
            written.append(p) or Draft(answer="x", citations=[], next_options=[], forwarder_message="")
        ),
    )
    state = turn(graph, "TESTVSL0001 판매는 2026년 9월 25일에 해요")
    cell = state.values["verdicts"][0]
    assert (cell["grade"], cell["margin_days"]) == ("alert", 1) and "no_sale_date" not in cell["info"]
    (line,) = vessel_lines(state.values["cargos"], state.values["vessels"], state.values["verdicts"])
    assert "등급: 경계" in line and "여유 일수: 1일" in line and "판매 예정일을 받지 않아" not in line
    assert "등급: 경계" in written[0] and "판매 예정일을 받지 않아" not in written[0]
    assert calls == ["pos", "plan"]  # 판정 한 번의 위치 1, 일정 1. 다시 판정해도 늘지 않는다
    assert "다시 계산해요" in results(state)[0]
    # 받은 날짜가 없는 차례는 다시 판정하지 않는다
    calls.clear()
    plain = graph_on(agent_deps, say())
    turn(plain, "TESTVSL0001 어디쯤 왔어요?")
    assert calls == ["pos", "plan"]


def test_the_on_path_gives_the_verifier_the_verdicts_with_ship_status_and_the_dates_the_user_gave(
    agent_deps, monkeypatch
):
    # [왜] 11-17 R-187. main.on_args가 검증자에 주는 값: 판정 줄마다 배 확인 상태(ship_status)와
    #      사용자가 말해 받은 날짜(user_dates). 상태를 빼면 고른 배의 단정 어구 규칙이 확신 값에만 기대고,
    #      날짜를 빼면 사용자가 말한
    #      날짜를 옮겨 쓴 답이 위반이 된다
    from langgraph.types import Command

    from marvia.graph import main as graph_main

    seen = []
    real = graph_main.verify
    monkeypatch.setattr(graph_main, "verify", lambda *a, **k: (seen.append(k), real(*a, **k))[1])
    graph = graph_on(agent_deps, say(note(sale_date="2026-09-25")), say(), say())
    turn(graph, "TESTVSL0001 판매는 2026년 9월 25일에 해요", "k")
    (kwargs,) = seen
    assert kwargs["user_dates"] == {"2026-09-25"}
    assert [(v["token"], v["ship_status"]) for v in kwargs["verdicts"]] == [("[BL1]", "confirmed")]
    # 사용자가 고른 배는 user_choice로 간다
    seen.clear()
    picked = graph_on(agent_deps, say(), say())
    config = {"configurable": {"thread_id": "k2"}}
    picked.invoke({"text": "TESTVSL0002 어디쯤 왔어요?"}, config)
    picked.invoke(Command(resume={"selected": 1}), config)
    assert [(v["token"], v["ship_status"]) for v in seen[-1]["verdicts"]] == [("[BL1]", "user_choice")]
    assert seen[-1]["user_dates"] == set()


# --- 다시 판정(rejudge)의 사전과 재시작 (11-17 R-189, R-190) ---

ASK_MORE = (
    "ask_user",
    {"question": "더 알려 줄 것?", "options": [{"label": "없음", "description": "없음"}] * 2},
)


def counted(monkeypatch, fail=None):
    from marvia.identify.models import ToolError
    from marvia.tools import mof

    calls: list[str] = []
    real_pos, real_plan = shipfinder.vessel_position, mof.port_schedule

    def broken():
        return ToolError(code="unavailable", message="x", retryable=True)

    def pos(*a, **k):
        calls.append("pos")
        return broken() if fail and fail["on"] else real_pos(*a, **k)

    def plan(*a, **k):
        calls.append("plan")
        return broken() if fail and fail["on"] else real_plan(*a, **k)

    monkeypatch.setattr(shipfinder, "vessel_position", pos)
    monkeypatch.setattr(mof, "port_schedule", plan)
    return calls


def rebuilt(agent_deps, saver, store, script):
    """같은 체크포인트로 새로 만든 그래프 = 다시 시작한 프로세스(빈 사전)."""
    deps = agent_deps(
        model=ToolModel(messages=iter(script)),
        now=lambda: NOW,
        write=lambda p: Draft(answer="x", citations=[], next_options=[], forwarder_message=""),
    )
    return build_main_graph(deps, saver, loop="agent", store=store, vessel=True)


def test_a_restart_in_the_middle_of_the_turn_refetches_once_and_still_judges_the_new_date(
    agent_deps, monkeypatch
):
    # [왜] 11-17 R-189(S2). 날짜를 받고 루프 안 질문에서 멈춘 뒤 새 프로세스로 재개하면 사전이 비었다.
    #      판정 줄의 날짜와 공책의 날짜가 달라 다시 판정하고, 위치·일정은 한 번만 다시 받는다
    calls = counted(monkeypatch)
    saver, store = InMemorySaver(), InMemoryStore()
    config = {"configurable": {"thread_id": "s2"}}
    first = rebuilt(agent_deps, saver, store, [say(note(sale_date="2026-09-25")), say(ASK_MORE)])
    first.invoke({"text": "TESTVSL0001 판매는 2026년 9월 25일에 해요"}, config)
    before = list(calls)
    second = rebuilt(agent_deps, saver, store, [say(), say()])
    second.invoke(Command(resume={"custom": "없어요"}), config)
    cell = second.get_state(config).values["verdicts"][0]
    assert (cell["grade"], cell["margin_days"]) == ("alert", 1)
    assert calls[len(before) :] == ["pos", "plan"]


def test_a_restart_resume_with_only_an_old_date_makes_no_new_outside_call(agent_deps, monkeypatch):
    # [왜] 11-17 R-189(S3). 날짜는 앞 차례에 받았고 이번 차례는 질문에서 멈췄다.
    #      판정 줄이 쓴 날짜가 공책과 같으니
    #      새 프로세스의 빈 사전에서도 다시 받지 않는다
    calls = counted(monkeypatch)
    saver, store = InMemorySaver(), InMemoryStore()
    config = {"configurable": {"thread_id": "s3"}}
    first = rebuilt(agent_deps, saver, store, [say(note(sale_date="2026-09-25")), say(), say(ASK_MORE)])
    first.invoke({"text": "TESTVSL0001 판매는 2026년 9월 25일에 해요"}, config)
    first.invoke({"text": "TESTVSL0001 지금은요?"}, config)
    before = list(calls)
    second = rebuilt(agent_deps, saver, store, [say(), say()])
    second.invoke(Command(resume={"custom": "없어요"}), config)
    assert calls == before
    assert second.get_state(config).values["verdicts"][0]["grade"] == "alert"


def test_two_conversations_in_one_process_never_read_each_others_fetched_data(agent_deps, monkeypatch):
    # [왜] 11-17 R-190(S4). A가 날짜를 받고 루프 안 질문에서 멈춘 사이 B가 같은 토큰으로 바깥 호출이
    #      모두 실패하는 차례를 돌고 B도 질문에서 멈춘다(B의 사전 항목이 남는다). A를 재개하면 A의
    #      위치·일정으로 경계가 나와야 한다. 사전 키에 대화 번호가 있어야 한다
    fail = {"on": False}
    counted(monkeypatch, fail)
    saver, store = InMemorySaver(), InMemoryStore()
    script = [say(note(sale_date="2026-09-25")), say(ASK_MORE), say(ASK_MORE), say(), say(), say()]
    graph = rebuilt(agent_deps, saver, store, script)
    a, b = {"configurable": {"thread_id": "A"}}, {"configurable": {"thread_id": "B"}}
    graph.invoke({"text": "TESTVSL0001 판매는 2026년 9월 25일에 해요"}, a)
    fail["on"] = True
    graph.invoke({"text": "TESTVSL0001 어디쯤 왔어요?"}, b)
    fail["on"] = False
    graph.invoke(Command(resume={"custom": "없어요"}), a)
    assert graph.get_state(a).values["verdicts"][0]["grade"] == "alert"
    assert graph.get_state(b).values["verdicts"][0]["grade"] is None


def test_the_verdict_row_carries_the_dates_it_was_judged_with_and_the_cache_is_emptied_by_rejudge(agent_deps):
    # [왜] 11-17 R-189. 판정 줄의 dates는 판정에 쓴 날짜다(배 값이 아니다). rejudge는 쓴 항목을 지운다
    graph = graph_on(agent_deps, say(note(sale_date="2026-09-25")), say())
    state = turn(graph, "TESTVSL0001 판매는 2026년 9월 25일에 해요")
    assert state.values["verdicts"][0]["dates"] == {"sale_date": "2026-09-25"}
    plain = turn(graph_on(agent_deps, say()), "TESTVSL0001 어디쯤 왔어요?", "p")
    assert plain.values["verdicts"][0]["dates"] == {}


def test_the_planner_and_supervisor_paths_do_not_write_the_fetch_cache(monkeypatch):
    # [왜] 11-17 R-189. rejudge가 없는 켠 길은 위치·일정을 사전에 남기지 않는다(keep=False).
    #      보이는 차이는 이것이다:
    #      사전을 쓰는 쪽은 다시 판정할 때 바깥 호출이 늘지 않고, 안 쓰는 쪽은 다시 받는다
    from marvia.graph.vessel import verdict_nodes
    from marvia.tools.unipass_replay import lookup_cargo

    calls = counted(monkeypatch)
    cargo = {"token": "[BL1]", "facts": lookup_cargo("TESTVSL0001").model_dump(mode="json")}
    ship = {"token": "[BL1]", "status": "confirmed", "reason": "mrn_call_sign", "mmsi": "999000001",
            "call_sign": "QQTST1", "name": "TEST CARGO A", "basis": ["call_sign"], "cap": None}  # fmt: skip
    config = {"configurable": {"thread_id": "keep"}}
    extra = {}
    for keep in (True, False):
        verdict, rejudge = verdict_nodes(lambda: NOW, keep=keep)
        state = {"cargos": [cargo], "vessels": [ship]}
        state["verdicts"] = verdict(state, config)["verdicts"]  # type: ignore[arg-type,typeddict-item]
        calls.clear()
        state["cargo_dates"] = {"[BL1]": {"sale_date": "2026-09-25"}}  # type: ignore[typeddict-unknown-key]
        rejudge(state, config)  # type: ignore[arg-type]
        extra[keep] = list(calls)
        if keep:  # 쓴 항목은 지워졌다: 같은 공책으로 한 번 더 다시 판정하면 이번에는 다시 받는다
            calls.clear()
            rejudge(state, config)  # type: ignore[arg-type]
            extra["again"] = list(calls)
    assert extra == {True: [], "again": ["pos", "plan"], False: ["pos", "plan"]}


def test_a_refetch_after_a_restart_stays_within_the_per_turn_cargo_cap(monkeypatch):
    # [왜] 11-17 R-189. 사전이 없을 때의 다시 받기도 한 차례의 화물 수 상한(max_cargos 3)을 센다. 넷째 화물은
    #      받지 않고 over_cap으로 남는다
    from marvia.graph.vessel import verdict_nodes
    from marvia.tools.unipass_replay import lookup_cargo

    calls = counted(monkeypatch)
    facts = lookup_cargo("TESTVSL0001").model_dump(mode="json")
    ship = {"status": "confirmed", "reason": "mrn_call_sign", "mmsi": "999000001", "call_sign": "QQTST1",
            "name": "TEST CARGO A", "basis": ["call_sign"], "cap": None}  # fmt: skip
    verdict, rejudge = verdict_nodes(lambda: NOW, keep=False)
    config = {"configurable": {"thread_id": "cap"}}
    tokens = ["[BL1]", "[BL2]", "[BL3]", "[BL4]"]
    cargos = [{"token": t, "facts": facts} for t in tokens]
    ships = [{**ship, "token": t} for t in tokens]
    rows = []
    for t in tokens:  # 따로 판정해 어느 줄에도 over_cap이 없다
        rows += verdict({"cargos": [{"token": t, "facts": facts}], "vessels": ships}, config)["verdicts"]  # type: ignore[arg-type]
    assert not any("over_cap" in r["notes"] for r in rows)
    calls.clear()
    dates = {t: {"sale_date": "2026-09-25"} for t in tokens}
    out = rejudge({"cargos": cargos, "vessels": ships, "verdicts": rows, "cargo_dates": dates}, config)  # type: ignore[arg-type]
    assert len(calls) == 6 and ["over_cap" in r["notes"] for r in out["verdicts"]] == [False] * 3 + [True]
