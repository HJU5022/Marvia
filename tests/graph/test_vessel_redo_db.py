"""되돌리기와 날짜 칸이 암호화 저장기를 거쳐 차례를 넘는지 본다 (계획 8c T5, R-173). DB가 꺼지면 건너뜀.

[왜] 서버를 껐다 켠 것처럼 차례마다 새 연결·새 그래프·새 모델로 이어 간다. 시험용 스키마(test_url)만 쓴다.
"""

import itertools
from datetime import UTC, datetime

from cryptography.fernet import Fernet
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.store.memory import InMemoryStore

from marvia.graph.live import live_memory
from marvia.graph.main import build_main_graph
from marvia.graph.schemas import Draft
from marvia.tools import shipfinder

NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)


_ids = itertools.count()


def say(*calls: tuple[str, dict]) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": n, "args": a, "id": f"d{next(_ids)}-{n}"} for n, a in calls])


def redo() -> AIMessage:
    return say(("redo_vessel", {"token": "[BL1]"}))


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def test_the_refind_count_and_the_consumed_request_field_survive_a_checkpointer_round_trip_across_two_turns(
    agent_deps, test_url
):
    shipfinder.reset_state()
    key = Fernet.generate_key().decode()  # [왜] 시험 안에서 만든 키. 저장소의 키를 쓰지 않는다
    config = {"configurable": {"thread_id": "pg-redo", "user_id": "u1"}}
    text = "TESTVSL0001 판매는 9월 30일에 해요"
    note = say(("note_dates", {"token": "[BL1]", "sale_date": "2026-09-30"}))

    def turn(script, text=text):
        with live_memory(test_url, key) as (saver, _store):
            deps = agent_deps(
                model=ToolModel(messages=iter(script)),
                now=lambda: NOW,
                write=lambda p: Draft(
                    answer="확인했어요", citations=[], next_options=[], forwarder_message=""
                ),
            )
            graph = build_main_graph(deps, saver, loop="agent", store=InMemoryStore(), vessel=True)
            graph.invoke({"text": text}, config)
            return graph.get_state(config).values

    first = turn([note, redo(), say()])
    assert first["vessel_redo"] == {"[BL1]": 1} and first["cargo_dates"] == {
        "[BL1]": {"sale_date": "2026-09-30"}
    }
    second = turn([say()], "TESTVSL0001 어디쯤 왔어요?")  # 새 연결: 다시 찾는다
    assert second["vessel_refound"] == {"[BL1]": 1} and second["vessel_consumed"] == {"[BL1]": 1}
    assert second["turn_answers"] == [] and second["cargo_dates"] == {"[BL1]": {"sale_date": "2026-09-30"}}
    third = turn([redo(), say()], "TESTVSL0001 어디쯤 왔어요?")
    assert third["vessel_redo"] == {"[BL1]": 2}
    fourth = turn([say()], "TESTVSL0001 어디쯤 왔어요?")
    assert fourth["vessel_refound"] == {"[BL1]": 2} and fourth["vessel_consumed"] == {"[BL1]": 2}
    fifth = turn([redo(), say()], "TESTVSL0001 어디쯤 왔어요?")  # 상한: 요청 수가 늘지 않는다
    assert fifth["vessel_redo"] == {"[BL1]": 2} and fifth["vessel_refound"] == {"[BL1]": 2}
