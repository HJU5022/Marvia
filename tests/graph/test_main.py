from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from marvia.graph.main import build_main_graph


def cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def test_unambiguous_answers_directly():
    graph = build_main_graph(InMemorySaver())
    out = graph.invoke({"text": "demo0001 demo0002 어디야?"}, cfg("t1"))
    assert "2건으로 읽었어요." in out["answer"]
    assert "DEMO0002: 수입신고 (부산)" in out["answer"]


def test_ambiguous_interrupts_then_resumes():
    graph = build_main_graph(InMemorySaver())
    out = graph.invoke({"text": "MOCK12345678TEST87654321"}, cfg("t2"))
    question = out["__interrupt__"][0].value
    assert question["kind"] == "choice" and question["recommended"] == 0
    out = graph.invoke(Command(resume={"selected": 0}), cfg("t2"))
    assert "MOCK12345678: 입항 (인천)" in out["answer"]
    assert "TEST87654321: 하선신고 (인천)" in out["answer"]


def test_custom_reply():
    graph = build_main_graph(InMemorySaver())
    graph.invoke({"text": "MOCK12345678TEST87654321"}, cfg("t3"))
    out = graph.invoke(Command(resume={"custom": "MOCK12345678"}), cfg("t3"))
    assert "MOCK12345678" in out["answer"]
    assert "TEST87654321" not in out["answer"]


def test_no_number_guides_user():
    graph = build_main_graph(InMemorySaver())
    out = graph.invoke({"text": "다음 주에 칭다오에서 고추 와요"}, cfg("t4"))
    assert "B/L" in out["answer"]
