"""승인 재개 값 정리(graph/resume.py) 시험."""

from marvia.graph.resume import approval_reply

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
