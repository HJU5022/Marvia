"""승인 재개 값 정리(graph/resume.py) 시험."""

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from marvia.graph.main import build_main_graph
from marvia.graph.resume import NEW_NUMBER, REJECTED, approval_reply, remask_reply

REJECT = {"type": "reject", "message": "승인 값을 읽지 못해 실행하지 않았어요"}


def test_valid_decisions_pass_through():
    raw = {
        "decisions": [
            {"type": "approve"},
            {"type": "reject", "message": "싫어요"},
            {"type": "edit", "edited_action": {"name": "save_item_card", "args": {"name": "고추"}}},
        ]
    }
    names = ["a", "b", "save_item_card"]
    assert approval_reply(raw, 3, names) == raw


def test_string_becomes_rejections():
    assert approval_reply("a", 2) == {"decisions": [REJECT, REJECT]}


def test_empty_list_and_wrong_count_become_rejections():
    assert approval_reply({"decisions": []}, 1) == {"decisions": [REJECT]}
    assert approval_reply({"decisions": [{"type": "approve"}]}, 2) == {"decisions": [REJECT, REJECT]}
    assert approval_reply({"x": 1}, 1) == {"decisions": [REJECT]}


def test_unknown_type_becomes_rejection_but_others_stay():
    raw = {"decisions": [{"type": "approve"}, {"type": "run"}]}
    assert approval_reply(raw, 2) == {"decisions": [{"type": "approve"}, REJECT]}


def test_edit_that_renames_the_tool_is_rejected():
    edit = {"type": "edit", "edited_action": {"name": "decline", "args": {}}}
    assert approval_reply({"decisions": [edit]}, 1, ["save_item_card"]) == {"decisions": [REJECT]}


def test_names_with_a_different_count_reject_all_without_raising():
    raw = {"decisions": [{"type": "approve"}]}
    assert approval_reply(raw, 1, ["a", "b"]) == {"decisions": [REJECT]}


# --- 재개 값 다시 가리기 (done 1.4, 계획 4b Task 5b) ---

MAP = {"[BL1]": "DEMO0001"}


def _edit(args: dict) -> dict:
    return {"type": "edit", "edited_action": {"name": "save_item_card", "args": args}}


def test_edited_args_and_reject_text_get_this_threads_tokens_back():
    reply = {
        "decisions": [
            _edit({"name": "DEMO0001 고추", "n": 3}),
            {"type": "reject", "message": "DEMO0001 빼 줘"},
        ]
    }
    assert remask_reply(reply, MAP) == {
        "decisions": [_edit({"name": "[BL1] 고추", "n": 3}), {"type": "reject", "message": "[BL1] 빼 줘"}]
    }


def test_a_number_new_to_the_thread_turns_the_decision_into_a_fixed_rejection():
    # [왜] 고치기로 새 번호를 들여오면 서버가 새 토큰을 공책에 넣을 길이 없다. 실행하지 않는 쪽으로 간다
    reply = {"decisions": [_edit({"name": "DEMO0009"}), {"type": "reject", "message": "DEMO0009는 아니에요"}]}
    assert remask_reply(reply, MAP) == {"decisions": [NEW_NUMBER, {"type": "reject", "message": REJECTED}]}


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class Inputs(BaseCallbackHandler):
    """채팅 모델에 들어간 메시지 글과 도구 호출 인자를 모은다."""

    def __init__(self):
        self.seen: list[str] = []

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.seen += [f"{m.content} {getattr(m, 'tool_calls', '')}" for batch in messages for m in batch]


CHILI = {
    "category": "농산물·임산물",
    "same": ["생산국", "품명", "수출업소", "포장장소"],
    "different": [],
    "prior_precise": "받음",
    "prior_result": "적합",
    "prior_cert_on": "2026-03-10",
    "flags": [],
}


@pytest.mark.parametrize(
    "decision", [_edit({"name": "DEMO0001 고추"}), {"type": "reject", "message": "DEMO0001은 빼 주세요"}]
)
@pytest.mark.parametrize("remask", [True, False])
def test_the_model_never_sees_a_number_typed_on_the_approval_card(agent_deps, decision, remask):
    steps = [
        AIMessage("", tool_calls=[{"name": "check_reimport", "args": {"facts": CHILI}, "id": "c1"}]),
        AIMessage("", tool_calls=[{"name": "save_item_card", "args": {"name": "건고추"}, "id": "c2"}]),
        AIMessage(""),
    ]
    graph = build_main_graph(
        agent_deps(model=ToolModel(messages=iter(steps))),
        InMemorySaver(),
        loop="agent",
        store=InMemoryStore(),
    )
    inputs = Inputs()
    config = {"configurable": {"thread_id": f"remask-{remask}"}, "callbacks": [inputs]}
    out = graph.invoke({"text": "DEMO0001 건고추 카드로 기억해 줘"}, config)
    reply = approval_reply({"decisions": [decision]}, 1, ["save_item_card"])
    mask_map = graph.get_state(config).values["mask_map"]
    graph.invoke(Command(resume=remask_reply(reply, mask_map) if remask else reply), config)
    assert "__interrupt__" in out
    # [왜] 다시 가리지 않으면 실패하는 시험인지 함께 본다 (가린 쪽만 0이다)
    assert any("DEMO0001" in text for text in inputs.seen) is (not remask)


@pytest.mark.parametrize("args", [{"DEMO0001": "x"}, {"note": 123456789012}], ids=["key", "int-value"])
def test_a_number_in_a_key_or_a_non_text_value_is_refused(args):
    # [왜] 정수 값에는 글자 접두어를 붙일 수 없어 숫자만 있는 가공 값을 쓴다
    # [왜] 고친 인자는 json.dumps 알림으로 모델에 간다. 키와 숫자 값도 글이 된다
    assert remask_reply({"decisions": [_edit(args)]}, MAP) == {"decisions": [NEW_NUMBER]}


def test_decisions_are_rebuilt_from_fixed_keys_only():
    reply = {
        "decisions": [
            {"type": "approve", "message": "DEMO0009"},
            {"type": "reject", "message": "no", "why": "DEMO0009"},
            {"type": "edit", "edited_action": {"name": "n", "args": {"a": 1}, "note": "DEMO0009"}, "x": 1},
        ]
    }
    assert remask_reply(reply, MAP) == {
        "decisions": [
            {"type": "approve"},
            {"type": "reject", "message": "no"},
            {"type": "edit", "edited_action": {"name": "n", "args": {"a": 1}}},
        ]
    }


@pytest.mark.parametrize(
    ("args", "needle"),
    [
        ({"name": "건고추", "DEMO0001": "x"}, "DEMO0001"),
        # 정수 값에는 글자 접두어를 붙일 수 없어 숫자만 있는 가공 값을 쓴다
        ({"name": "건고추", "note": 123456789012}, "123456789012"),
    ],
    ids=["key", "int-value"],
)
def test_the_model_never_sees_a_number_in_an_edited_key_or_number_value(agent_deps, args, needle):
    steps = [
        AIMessage("", tool_calls=[{"name": "check_reimport", "args": {"facts": CHILI}, "id": "c1"}]),
        AIMessage("", tool_calls=[{"name": "save_item_card", "args": {"name": "건고추"}, "id": "c2"}]),
        AIMessage(""),
    ]
    graph = build_main_graph(
        agent_deps(model=ToolModel(messages=iter(steps))),
        InMemorySaver(),
        loop="agent",
        store=InMemoryStore(),
    )
    inputs = Inputs()
    config = {"configurable": {"thread_id": "keys"}, "callbacks": [inputs]}
    graph.invoke({"text": "DEMO0001 건고추 카드로 기억해 줘"}, config)
    reply = approval_reply({"decisions": [_edit(args)]}, 1, ["save_item_card"])
    graph.invoke(Command(resume=remask_reply(reply, graph.get_state(config).values["mask_map"])), config)
    assert not any(needle in text for text in inputs.seen)
