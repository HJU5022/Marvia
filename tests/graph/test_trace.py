"""트레이스 가림 문 시험 (R-010·R-022·R-039, done 3.9). 트레이서 없이 기록 콜백으로 본다. 키 없이 돈다."""

import json

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command, Send

from marvia.graph.main import build_main_graph
from marvia.graph.schemas import Draft
from marvia.trace import MASK, scrub
from marvia.watch import WatchDeps

NUMBERS = ("DEMO0001", "DEMO0002", "DEMO0003", "DEMO0004")
TWO = [{"label": "부산", "description": "부산항 기준"}, {"label": "인천", "description": "인천항 기준"}]


class ToolModel(GenericFakeChatModel):
    """정해 둔 AIMessage를 차례로 내는 가짜 모델 (tests/graph/test_agent.py와 같다)."""

    def bind_tools(self, tools, **kwargs):
        return self


def say(name: str, args: dict, n: int) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"t{n}-{name}"}])


class Record(BaseCallbackHandler):
    """콜백이 받는 값을 모두 모은다. 트레이서(Langfuse)가 받는 값과 같은 자리다."""

    def __init__(self):
        self.payloads: list = []

    def on_chain_start(self, serialized, inputs, **kwargs):
        self.payloads.append(inputs)

    def on_chain_end(self, outputs, **kwargs):
        self.payloads.append(outputs)

    def on_chain_error(self, error, **kwargs):
        self.payloads.append(error)  # [왜] 끼어들기(GraphInterrupt)는 오류 길로 질문 값을 싣고 온다

    def on_tool_start(self, serialized, input_str, *, inputs=None, **kwargs):
        self.payloads.append([input_str, inputs])

    def on_tool_end(self, output, **kwargs):
        self.payloads.append(output)

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.payloads.append(messages)

    def on_llm_end(self, response, **kwargs):
        self.payloads.append(response)


def test_every_callback_payload_is_free_of_numbers_after_scrub(agent_deps):
    # 한 대화가 지나는 길: 번호 둘(Send 두 갈래) → news(감시 변화 DEMO0004) → lookup_cargo
    # → ask_user(직접 입력 DEMO0003) → research(조사 서브에이전트 안의 search_law) → 작성자
    # → 답(DEMO0001을 되돌린 글)
    script = [
        say("lookup_cargo", {"tokens": ["[BL1]"]}, 1),
        say("ask_user", {"question": "어느 화물부터 볼까요?", "options": TWO}, 2),
        say("research", {"question": "수입신고 기한의 근거"}, 3),
        say("search_law", {"query": "수입신고 기한"}, 4),  # 조사 서브에이전트 안
        AIMessage("관세법 제241조가 30일을 정해요."),  # 조사 요약
        AIMessage(""),  # 부모 루프 끝
    ]
    news = [{"id": 1, "number": "DEMO0004", "old_stage": "", "new_stage": "반입신고"}]
    watch = WatchDeps(add=lambda *row: None, news=lambda user: news, ack=lambda user, ids: None)
    citing = Draft(
        answer="[BL1]은 반입일부터 30일 안에 신고해요.", citations=[], next_options=[], forwarder_message=""
    )
    deps = agent_deps(model=ToolModel(messages=iter(script)), watch=watch, write=lambda prompt: citing)
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
    record = Record()
    config = {"configurable": {"thread_id": "trace"}, "callbacks": [record]}
    out = graph.invoke({"text": "DEMO0001 DEMO0002 언제까지 신고해요?"}, config)
    assert "__interrupt__" in out
    out = graph.invoke(Command(resume={"custom": "DEMO0003부터 봐 주세요"}), config)
    assert "DEMO0001" in out["answer"]
    raw = json.dumps(record.payloads, ensure_ascii=False, default=str)
    # [왜] 가림을 빼면 실패하는 시험인지 먼저 본다: 길마다 넣은 번호가 가리기 전 값에는 모두 있다
    assert all(number in raw for number in NUMBERS)
    scrubbed = json.dumps(scrub(record.payloads), ensure_ascii=False)
    assert [number for number in NUMBERS if number in scrubbed] == []
    assert MASK in scrubbed


def test_scrub_walks_send_packets_models_and_unknown_objects():
    packet = Send("one", {"idx": 0, "number": "DEMO0001", "mask_map": {"[BL1]": "DEMO0001"}})
    message = AIMessage("", tool_calls=[{"name": "watch_cargo", "args": {"token": "DEMO0002"}, "id": "c1"}])
    cleaned = json.dumps(scrub([packet, message, ValueError("DEMO0003 조회 실패")]), ensure_ascii=False)
    assert "DEMO" not in cleaned and cleaned.count(MASK) == 4
    # 날짜·짧은 글·unit_id는 그대로 둔다 (L001556은 7자, 20261002는 날짜라 번호 후보가 아니다)
    assert scrub({"unit_id": "L001556@20261002#제241조.3항", "n": 3}) == {
        "unit_id": "L001556@20261002#제241조.3항",
        "n": 3,
    }
