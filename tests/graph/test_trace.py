"""트레이스 가림 문 시험 (R-010·R-022·R-039, done 3.9, 계획 6b). 기록 콜백·메모리 내보내기로 키 없이 본다."""

import json
import os
import socket
import subprocess
import sys
from uuid import uuid4

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool
from langfuse import Langfuse, get_client
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command, Send
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode, get_tracer

from marvia import langfuse_trace, trace
from marvia.config import Settings
from marvia.graph import tools
from marvia.graph.main import build_main_graph
from marvia.graph.schemas import Draft
from marvia.trace import MASK, scrub, tracer_callbacks
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

    def on_tool_error(self, error, *, inputs=None, **kwargs):
        self.payloads.append([error, inputs])  # [왜] Langfuse 핸들러는 도구 오류에도 입력을 함께 내보낸다

    def on_tool_end(self, output, **kwargs):
        self.payloads.append(output)

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.payloads.append(messages)

    def on_llm_end(self, response, **kwargs):
        self.payloads.append(response)


def _flat(value):
    """콜백 값 안의 모든 값을 평평하게 푼다(dict·list·tuple을 따라간다)."""
    yield value
    if isinstance(value, dict):
        value = [*value.keys(), *value.values()]
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _flat(item)


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
    # [왜] 번호별이 아니라 길별로 본다: 첫 입력에도 있는 번호가 길이 빠진 것을 가리지 않게
    seen = list(_flat(record.payloads))
    assert any(isinstance(item, Send) for item in seen)  # 조회 갈래(Send 묶음)
    assert any(isinstance(item, GraphInterrupt) for item in seen)  # 끼어들기가 오류 길로 온 것
    assert any(item == {"query": "수입신고 기한"} for item in seen)  # 조사 서브에이전트 안의 도구 입력
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
    # YYYYMMDD·YYYY-MM-DD 날짜, 짧은 글, unit_id는 그대로 둔다
    # (L001556은 7자, 20261002는 날짜라 번호 후보가 아니다)
    assert scrub({"unit_id": "L001556@20261002#제241조.3항", "n": 3}) == {
        "unit_id": "L001556@20261002#제241조.3항",
        "n": 3,
    }


def test_scrub_takes_the_value_by_position_or_as_data_keyword():
    # [왜] Langfuse 클라이언트는 마스크 함수를 mask(data=...)로 부른다
    assert scrub("DEMO0001") == MASK
    assert scrub(data="DEMO0001") == MASK


def test_scrub_survives_odd_keys_cycles_and_broken_objects():
    class Broken:
        def __str__(self):
            raise RuntimeError("DEMO0009")

    looped: list = ["DEMO0001"]
    looped.append(looped)
    odd = scrub({("DEMO0001", 1): "a", frozenset({"DEMO0002"}): "b", Broken(): "c", 7: "d"})
    assert "DEMO" not in json.dumps(odd, ensure_ascii=False) and 7 in odd and len(odd) == 4
    assert MASK in json.dumps(scrub(looped), ensure_ascii=False)
    assert scrub(Broken()) == MASK


def test_distinct_number_keys_keep_both_values():
    # [왜] 서로 다른 번호 키가 같은 가림 키로 합쳐져 값 하나가 사라지지 않게 한다
    cleaned = scrub({"DEMO0001": "a", "DEMO0002": "b"})
    assert sorted(cleaned.values()) == ["a", "b"] and len(cleaned) == 2
    assert all("DEMO" not in key for key in cleaned)


def test_scrub_hides_container_numbers_whole():
    # [왜] 컨테이너 번호(11자)도 8자 이상 영문·숫자 덩어리라 같은 규칙에 걸린다 (계획 6a에서 확인)
    assert scrub("컨테이너 DEMU1234560, DEMU-123456-0") == f"컨테이너 {MASK}, {MASK}"


def test_scrub_hides_a_spaced_container_number():
    assert scrub("DEMU 123456 0 도착") == f"{MASK} 도착"


def test_scrub_hides_a_number_hyphen_joined_to_a_spaced_container():
    assert scrub("HASL0001-DEMU 123456 0 어디?") == f"{MASK}-{MASK} 어디?"
    assert scrub("DEMU 123456 0-HASL0001 어디?") == f"{MASK}-{MASK} 어디?"


def test_scrub_hides_every_container_shaped_spaced_form():
    for form in ("DEMU 123456 1", "DEMU 123456 (0)", "DEMU 123 456 0", "DEMU\t1234560", "DEMU  123456  0"):
        assert scrub(f"{form} 도착") == f"{MASK} 도착", form


def test_scrub_hides_hyphen_only_numbers_whole_and_keeps_an_outer_bracket():
    assert scrub("HDMU-1234567-001 도착") == f"{MASK} 도착"
    assert scrub("MAEU-1234567-89 도착") == f"{MASK} 도착"
    assert scrub("컨테이너(DEMU1234560)로") == f"컨테이너({MASK})로"


# 계획 6b: Langfuse로 내보낸 span 전체를 본다. 메모리 내보내기라 키·서버·네트워크가 없다

# 시나리오에 넣은 번호. 어느 칸으로 나가는지에 따라 묶었다
SAID = ("DEMO0001", "DEMO0002", "DEMO0003", "DEMO0004")  # 질문·직접 입력·감시 변화: 입력과 출력
FAILED = ("DEMO0005", "DEMO0006", "DEMO0007")  # 도구 예외·모델 오류·도구 오류 결과: span 상태 설명
ASKED = ("MOCK12345678", "TEST87654321")  # 애매한 덩어리: 식별 끼어들기의 질문 글(status_message)
OTHER = ("DEMO0008",)  # 다른 라이브러리 span의 예외 사건과 상태 설명
THREAD = ("DEMO0009",)  # 사용자가 정한 thread_id: 트레이스 metadata로 나가며 ①을 거치지 않는다(②만 가린다)
GATE = SAID + FAILED + ASKED + OTHER + THREAD
# 가림 네 겹: ⓪ should_export_span, ① mask, ② mask_otel_spans, ③ 오류를 가리는 콜백(errors)
LAYERS = ("should_export_span", "mask", "mask_otel_spans", "errors")


def strip(patch, *layers):
    """가림 겹을 뺀다. ⓪①②는 build가 Langfuse에 넘기는 인자에서 빼고, ③은 SDK 콜백을 그대로 쓴다."""
    patch.setattr(
        langfuse_trace, "Langfuse", lambda **kw: Langfuse(**{k: v for k, v in kw.items() if k not in layers})
    )
    if "errors" in layers:
        patch.setattr(langfuse_trace, "ScrubbedHandler", CallbackHandler)


class Scripted(ToolModel):
    """ToolModel과 같되 차례가 예외이면 그 예외를 낸다(모델 오류 길)."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        step = next(self.messages)
        if isinstance(step, Exception):
            raise step
        return ChatResult(generations=[ChatGeneration(message=step)])


def tracer():
    """메모리 내보내기에 붙인 가린 콜백. [왜] SDK는 공개키마다 클라이언트를 하나만 둔다. 시험마다 새 키"""
    exporter = InMemorySpanExporter()
    key = f"pk-test-{uuid4().hex}"
    return exporter, key, langfuse_trace.build(key, "sk-test", "http://127.0.0.1:9", exporter)


def exported(exporter, key) -> list[str]:
    """내보낸 span마다 SDK가 span 전체를 적는 글(to_json: 이름·속성·사건·상태·연결·자원)과 계측 범위."""
    client = get_client(public_key=key)
    client.flush()
    client.shutdown()  # [주의] 스레드·처리기는 빌드마다 2개씩 남는다(11-08 실측). 정리가 아니다
    # [왜] to_json은 한글을 \u로 적는다. 다시 읽어 한글 그대로 적어야 [가림]이 보인다
    return [
        json.dumps(json.loads(span.to_json()), ensure_ascii=False) + repr(span.instrumentation_scope)
        for span in exporter.get_finished_spans()
    ]


def gate_run(agent_deps, monkeypatch, callbacks: list) -> str:
    """한 대화와 오류 두 길을 같은 콜백으로 돌리고 대화의 답을 돌려준다."""
    # 1) 번호 둘 + 애매한 덩어리 → 식별 끼어들기 → 재개 → Send 갈래 → news(감시 변화) → lookup_cargo
    #    → ask_user 끼어들기 → 직접 입력 → research(서브에이전트 안 search_law) → 답
    script = [
        say("lookup_cargo", {"tokens": ["[BL1]"]}, 1),
        say("ask_user", {"question": "어느 화물부터 볼까요?", "options": TWO}, 2),
        say("research", {"question": "수입신고 기한의 근거"}, 3),
        say("search_law", {"query": "수입신고 기한"}, 4),  # 조사 서브에이전트 안
        AIMessage("관세법 제241조가 30일을 정해요."),
        AIMessage(""),
    ]
    news = [{"id": 1, "number": "DEMO0004", "old_stage": "", "new_stage": "반입신고"}]
    watch = WatchDeps(add=lambda *row: None, news=lambda user: news, ack=lambda user, ids: None)
    citing = Draft(
        answer="[BL1]은 반입일부터 30일 안에 신고해요.", citations=[], next_options=[], forwarder_message=""
    )
    deps = agent_deps(model=ToolModel(messages=iter(script)), watch=watch, write=lambda prompt: citing)
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
    config = {"configurable": {"thread_id": "gate-DEMO0009"}, "callbacks": callbacks}
    out = graph.invoke({"text": "DEMO0001 DEMO0002 MOCK12345678TEST87654321 언제까지 신고해요?"}, config)
    assert "MOCK12345678" in out["__interrupt__"][0].value["question"]  # 식별 끼어들기는 실제 번호를 싣는다
    out = graph.invoke(Command(resume={"selected": 0}), config)
    assert out["__interrupt__"][0].value["question"] == "어느 화물부터 볼까요?"
    answer = graph.invoke(Command(resume={"custom": "DEMO0003부터 봐 주세요"}), config)["answer"]
    # 2) 모델 오류: Guards가 받아 부분 답으로 끝낸다
    broken = agent_deps(model=Scripted(messages=iter([OutputParserException("DEMO0006 모양이 틀린 답")])))
    graph = build_main_graph(broken, InMemorySaver(), loop="agent", store=InMemoryStore())
    graph.invoke({"text": "어디쯤이에요?"}, {"configurable": {"thread_id": "llm"}, "callbacks": callbacks})

    # 3) 도구 오류: 도구 안에서 난 예외는 차례를 멈춘다
    def fail(cargos, today):
        raise ValueError("DEMO0005 기한 계산 실패")

    monkeypatch.setattr(tools, "cargo_deadlines", fail)
    failing = agent_deps(model=ToolModel(messages=iter([say("calc_deadlines", {}, 5)])))
    graph = build_main_graph(failing, InMemorySaver(), loop="agent", store=InMemoryStore())
    with pytest.raises(ValueError, match="DEMO0005"):
        graph.invoke(
            {"text": "언제까지예요?"}, {"configurable": {"thread_id": "tool"}, "callbacks": callbacks}
        )

    # 4) 도구가 오류 결과(status="error")를 돌려주는 길: Langfuse가 그 글을 span 상태 설명에 넣는다
    @tool
    def refuse(token: str) -> ToolMessage:
        """오류 결과를 돌려주는 도구."""
        return ToolMessage("DEMO0007 조회 실패", tool_call_id="t7", status="error")

    call = {"name": "refuse", "args": {"token": "[BL1]"}, "id": "t7", "type": "tool_call"}
    refuse.invoke(call, {"callbacks": callbacks})

    # 6) 값 전체가 data URI인 입력(DEMO0010을 base64로 적은 글): SDK는 이를 미디어로 올리려 한다 (R-084)
    RunnableLambda(lambda text: "ok").invoke("data:text/plain;base64,REVNTzAwMTA=", {"callbacks": callbacks})

    # 5) 다른 라이브러리의 OTel span(MCP 서버 꼴): 트레이서가 놓은 전역 TracerProvider로 들어온다
    with get_tracer("mcp-python-sdk").start_as_current_span(
        "tools/call search_law", attributes={"gen_ai.tool.name": "search_law"}
    ) as span:
        span.record_exception(ValueError("DEMO0008 검색 실패"))
        span.set_status(StatusCode.ERROR, "DEMO0008 검색 실패")
    return answer


def test_every_exported_span_field_is_free_of_numbers(agent_deps, monkeypatch):
    calls: list = []
    monkeypatch.setattr(socket.socket, "connect", lambda self, address: calls.append(address))
    exporter, key, handler = tracer()
    jobs: list = []  # [왜] data URI(DEMO0010의 base64)가 미디어 줄에 들어가면 안 된다 (R-084)
    queue = get_client(public_key=key)._resources._media_upload_queue
    put = queue.put
    monkeypatch.setattr(
        queue, "put", lambda *a, **kw: (jobs.extend([kw["item"]] if "item" in kw else []), put(*a, **kw))
    )
    answer = gate_run(agent_deps, monkeypatch, [handler])
    spans = exported(exporter, key)
    assert jobs == []
    dump = "".join(spans)
    with monkeypatch.context() as bare:  # [왜] 가림을 모두 빼면 실패하는 시험인지 같은 길로 먼저 본다
        strip(bare, *LAYERS)
        raw_exporter, raw_key, raw_handler = tracer()
        raw_answer = gate_run(agent_deps, bare, [raw_handler])
        raw = exported(raw_exporter, raw_key)
    assert [number for number in GATE if number not in "".join(raw)] == []
    assert [number for number in GATE if number in dump] == []
    # [왜] 가려도 SDK span은 하나도 빠지지 않는다. 빠지는 것은 다른 라이브러리 span(⓪) 하나뿐이다
    assert MASK in dump and len(spans) == len(raw) - len(OTHER)
    assert "DEMO0001" in answer and answer == raw_answer  # 가림은 트레이스에만, 답은 그대로
    assert calls == []  # Langfuse 주소로 연결하지 않았다


@pytest.mark.parametrize(
    "layer, left",
    [
        ("should_export_span", OTHER),
        ("mask", SAID + ASKED),
        ("mask_otel_spans", ASKED + THREAD),
        ("errors", FAILED),
    ],
)
def test_removing_any_one_layer_leaves_its_numbers(agent_deps, monkeypatch, layer, left):
    strip(monkeypatch, layer)
    exporter, key, handler = tracer()
    gate_run(agent_deps, monkeypatch, [handler])
    dump = "".join(exported(exporter, key))
    assert [number for number in left if number not in dump] == []


def test_layer_two_reads_sdk_json_values_so_they_stay_json_and_times_stay_times():
    # [왜] SDK는 trace metadata 값과 시각을 JSON 글로 적는다. 글 그대로 가리면 \n 뒤 덩어리가 \[가림]이 되어
    #      JSON이 깨지고, 시각은 [가림]:34:56이 된다 (계획 6c). 읽어서 가리되 번호는 남기지 않는다
    clean = langfuse_trace._clean
    assert json.loads(clean(json.dumps("gate\nDEMO0011", ensure_ascii=False))) == f"gate\n{MASK}"
    when = json.dumps("2026-11-08T12:34:56.123456+00:00")
    assert clean(when, langfuse_trace.TIME_ATTRIBUTE) == when
    # [왜] 시각 예외는 SDK의 시각 속성뿐이다. 다른 속성의 시각 모양 글(thread_id 등)은 번호 덩어리처럼 가린다
    assert clean(when) != when
    fake = json.dumps("1234-56-78T90:12:34.567890")
    assert clean(fake, langfuse_trace.TIME_ATTRIBUTE) != fake and MASK in clean(
        fake, langfuse_trace.TIME_ATTRIBUTE
    )
    assert clean(fake) != fake and "1234-56-78" not in clean(fake)
    meta = json.dumps({"thread_id": "1234-56-78T90:12:34"})
    assert MASK in clean(meta) and "1234-56-78" not in clean(meta)
    numbers = json.dumps({"bl": 123456789012, "n": 3, "said": "DEMO0012 어디야"})
    assert json.loads(clean(numbers)) == {"bl": MASK, "n": 3, "said": f"{MASK} 어디야"}
    assert clean("DEMO0013 조회 실패") == f"{MASK} 조회 실패"  # JSON이 아닌 글은 전처럼 가린다
    assert clean("123456789012") == json.dumps(MASK, ensure_ascii=False)


def test_layer_two_lets_no_number_through_a_long_fraction_or_a_repeated_key():
    # [왜] 시각 예외의 소수부가 길면 번호가 들 수 있고, 같은 키가 두 번이면 읽은 값에서 앞 값이 사라져
    #      "같다"로 보여 원본 글이 그대로 나간다 (계획 6c 리뷰)
    clean = langfuse_trace._clean
    long_fraction = json.dumps("2026-10-02T12:34:56.123456789012")
    assert "123456789012" not in clean(long_fraction)
    repeated = clean('{"a": "DEMO0001", "a": "x"}')
    assert "DEMO0001" not in repeated


def test_media_upload_is_off(monkeypatch):
    # [왜] data URI 사진은 ①이 가리기 전에 SDK가 미디어로 올린다. 끄는 길은 환경 변수 하나뿐이다
    exporter, key, handler = tracer()
    manager = get_client(public_key=key)._resources._media_manager
    assert manager._enabled is False
    get_client(public_key=key).shutdown()


def test_a_failing_mask_exports_nothing_or_masks_the_value_whole(monkeypatch):
    def boom(**_):
        raise RuntimeError("가림 실패")

    step = RunnableLambda(lambda text: text)
    for name, expected in (("scrub_spans", "nothing"), ("scrub", "masked")):
        with monkeypatch.context() as broken:
            broken.setattr(langfuse_trace, name, boom)
            exporter, key, handler = tracer()
            step.invoke("DEMO0001", {"callbacks": [handler]})
            spans = exported(exporter, key)
        # [왜] ②가 죽으면 SDK가 묶음을 통째로 버리고, ①이 죽으면 값을 통째로 가린 글로 바꾼다
        assert spans == [] if expected == "nothing" else spans and "DEMO0001" not in "".join(spans), name


OFF = """
import socket, sys, threading
calls = []
socket.socket.connect = lambda self, address: calls.append(address)
from marvia.config import Settings
from marvia.trace import tracer_callbacks
before = threading.active_count()
callbacks = tracer_callbacks(Settings(_env_file=None))
print(callbacks, "langfuse" in sys.modules, threading.active_count() - before, calls)
"""


def test_without_keys_tracing_is_off_with_no_sdk_thread_or_socket():
    # [왜] 이미 langfuse를 불러온 이 시험 프로세스가 아니라 새 프로세스에서 본다
    env = {name: value for name, value in os.environ.items() if not name.startswith("MARVIA_LANGFUSE_")}
    done = subprocess.run([sys.executable, "-c", OFF], capture_output=True, text=True, check=True, env=env)
    assert done.stdout.split() == ["[]", "False", "0", "[]"]  # 콜백 없음, SDK 안 부름, 스레드 0, 연결 0


@pytest.mark.parametrize(
    "given",
    [{"langfuse_public_key": "pk-x", "langfuse_secret_key": "sk-x"}, {"langfuse_host": "https://x.test"}],
)
def test_tracing_stays_off_unless_all_three_settings_are_given(monkeypatch, given):
    for name in ("MARVIA_LANGFUSE_PUBLIC_KEY", "MARVIA_LANGFUSE_SECRET_KEY", "MARVIA_LANGFUSE_HOST"):
        monkeypatch.delenv(name, raising=False)  # [왜] 셸에 걸린 값이 빈 칸을 채우지 않게 한다
    assert tracer_callbacks(Settings(_env_file=None, **given)) == []


@pytest.mark.parametrize(
    "host", ["https://x.test", "http://localhost", "http://127.0.0.1:3000", "http://[::1]:3000"]
)
def test_https_or_loopback_http_host_is_accepted(monkeypatch, host):
    monkeypatch.setattr(langfuse_trace, "build", lambda *keys: object())
    trace._handler.cache_clear()
    settings = Settings(
        _env_file=None, langfuse_public_key="pk-x", langfuse_secret_key="sk-x", langfuse_host=host
    )
    assert len(tracer_callbacks(settings)) == 1
    trace._handler.cache_clear()


@pytest.mark.parametrize(
    "host",
    [
        "http://langfuse.example.com",
        "http://localhost.evil.test",
        "ftp://x.test",
        # [왜] urlsplit은 역슬래시 앞을 사용자 칸으로 읽어 localhost를 보지만 urllib3은 evil.test로 보낸다
        "http://evil.test\\@localhost",
        "https://x.test\\@localhost",
        "http://evil.test\t@localhost",  # [왜] 탭은 urlsplit이 지우고 requests는 %09로 남겨 읽는 값이 갈린다
    ],
)
def test_a_remote_plain_http_host_is_refused_without_naming_the_keys(monkeypatch, host):
    monkeypatch.setattr(langfuse_trace, "build", lambda *keys: pytest.fail("building must not start"))
    settings = Settings(
        _env_file=None, langfuse_public_key="pk-secret", langfuse_secret_key="sk-secret", langfuse_host=host
    )
    with pytest.raises(ValueError) as error:
        tracer_callbacks(settings)
    assert "pk-secret" not in str(error.value) and "sk-secret" not in str(error.value)


def test_all_three_settings_give_one_shared_tracer_and_keys_stay_hidden(monkeypatch):
    built = []
    monkeypatch.setattr(langfuse_trace, "build", lambda *keys: built.append(keys) or object())
    trace._handler.cache_clear()
    settings = Settings(
        _env_file=None,
        langfuse_public_key="pk-x",
        langfuse_secret_key="sk-secret",
        langfuse_host="https://x.test",
    )
    first, second = tracer_callbacks(settings), tracer_callbacks(settings)
    trace._handler.cache_clear()
    assert len(first) == 1 and first[0] is second[0]  # [왜] 클라이언트·스레드 하나
    assert built == [("pk-x", "sk-secret", "https://x.test")]
    assert "sk-secret" not in repr(settings) and "pk-x" not in repr(settings)
