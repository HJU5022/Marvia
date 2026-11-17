"""검증자의 새 규칙 넷 시험 (계획 8c T7, CC8, 결정 C4, D18, D24). 판정 값을 받은 호출에서만 돈다."""

from datetime import UTC, date, datetime

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from marvia.graph.main import build_main_graph
from marvia.graph.schemas import Draft
from marvia.graph.verify import verify
from marvia.graph.vessel_text import vessel_lines
from marvia.tools import shipfinder
from marvia.tools.rules import load_rules
from marvia.tools.verdict import CONFIDENCE_LABEL, GRADE_LABEL

TODAY = date(2026, 9, 22)
MASK = {"[BL1]": "TESTVSL0001", "[BL2]": "TESTVSL0006"}


def row(token="[BL1]", grade="fine", confidence="sure", margin=None, eta="2026-09-24T12:00:00+09:00", **more):
    return {
        "token": token, "grade": grade, "confidence": confidence, "schedule": None, "stage": None,
        "signals": [], "trusted_eta": eta, "eta_source": "mof_planned", "margin_days": margin,
        "notes": [], "info": [], **more,
    }  # fmt: skip


def check(answer: str, rows: list[dict] | None, user_dates: set[str] | None = None) -> list[str]:
    draft = Draft(answer=answer, citations=[], next_options=[], forwarder_message="")
    return verify(draft, [], {}, [], MASK, TODAY, verdicts=rows, user_dates=user_dates)


def test_a_wrong_grade_name_next_to_the_word_grade_is_a_violation():
    for said in ("[BL1]의 등급은 경계예요.", "[BL1]은 경계 등급이에요."):
        (found,) = check(said, [row()])
        assert "[BL1]" in found and "판정은 순항" in found


def test_the_right_grade_name_passes():
    assert check("[BL1]의 등급은 순항이에요. 순항 등급이라 안심하세요.", [row()]) == []


def test_everyday_words_do_not_trip_the_rule():
    for said in (
        "주의하세요. 서류를 챙기세요.",
        "기한을 경계를 넘어 늦으면 가산세가 붙어요.",
        "부분적으로 맞아요.",
        "긴급 연락처예요.",
    ):
        assert check(said, [row()]) == [], said


def test_a_confidence_name_that_differs_is_a_violation():
    (found,) = check("[BL1]의 확신은 부분이에요.", [row()])
    assert "[BL1]" in found and "판정은 확실" in found
    assert check("[BL1]의 확신은 확실이에요.", [row()]) == []


def test_two_cargos_with_different_grades_need_a_token():
    rows = [row("[BL1]"), row("[BL2]", grade="act", confidence="partial")]
    (found,) = check("등급은 순항이에요.", rows)
    assert "토큰" in found
    # 값이 같으면 토큰 없이도 말할 수 있다
    assert check("등급은 순항이에요.", [row("[BL1]"), row("[BL2]")]) == []


def test_two_cargos_token_matched_grades_pass_and_swapped_grades_fail():
    rows = [row("[BL1]"), row("[BL2]", grade="act", confidence="partial")]
    assert check("[BL1]의 등급은 순항이에요. [BL2]의 등급은 긴급이에요.", rows) == []
    swapped = check("[BL1]의 등급은 긴급이에요. [BL2]의 등급은 순항이에요.", rows)
    assert len(swapped) == 2 and "[BL1]" in swapped[0] and "[BL2]" in swapped[1]


def test_an_eta_date_in_the_block_is_allowed_and_another_date_is_not():
    assert check("[BL1]은 2026-09-24에 와요.", [row()]) == []
    (found,) = check("[BL1]은 2026-09-26에 와요.", [row()])
    assert "2026-09-26" in found
    # 판정이 없으면(꺼진 길) 이전 규칙 그대로 막는다
    assert check("[BL1]은 2026-09-24에 와요.", None) != []


def test_a_date_the_user_gave_is_allowed():
    assert check("판매는 2026-11-20이라고 하셨어요.", [row()], {"2026-11-20"}) == []
    assert check("판매는 2026-11-20이라고 하셨어요.", [row()], set()) != []


def test_assertive_words_about_a_partial_cargo_are_a_violation():
    rows = [row(confidence="partial")]
    (found,) = check("[BL1]은 분명히 제때 와요.", rows)
    assert "[BL1]" in found and "단정" in found
    assert check("[BL1]은 제때 올 것으로 보여요.", rows) == []
    # 사용자가 고른 배는 확신 값이 같아도 단정하지 않는다
    assert check("[BL1]은 반드시 와요.", [row(ship_status="user_choice")]) != []


def test_assertive_words_about_a_sure_cargo_pass():
    assert check("[BL1]은 분명히 제때 와요.", [row()]) == []


def test_a_grade_for_a_cargo_without_grade_is_a_violation():
    (found,) = check("[BL1]의 등급은 순항이에요.", [row(grade=None, confidence="unknown")])
    assert "등급이 없는 화물" in found
    assert check("[BL1]은 등급을 낼 수 없어요.", [row(grade=None, confidence="unknown")]) == []
    # 내린 화물은 통관 신호로 낸 등급이 있다. 등급 없음으로 오판하지 않는다
    assert check("[BL1]의 등급은 긴급이에요.", [row(grade="act", info=["landed"])]) == []


def test_without_verdicts_the_result_is_that_of_the_old_verify():
    for said in ("[BL1]의 등급은 경계예요.", "분명히 와요. 확신은 부분이에요.", "여유 일수는 6일이에요."):
        assert check(said, None) == verify(
            Draft(answer=said, citations=[], next_options=[], forwarder_message=""), [], {}, [], MASK, TODAY
        )


def test_violations_name_no_real_numbers_or_ship_values():
    found = check(
        "[BL1]의 등급은 경계예요. [BL2] 확신은 부분이에요.", [row(), row("[BL2]", confidence="sure")]
    )
    assert found and not any(
        v in " ".join(found) for v in ("TESTVSL0001", "TESTVSL0006", "QQTST1", "999000001")
    )


def test_the_margin_days_of_that_cargo_are_allowed_as_n_days():
    assert check("[BL1]은 판매일까지 6일 남아요.", [row(margin=6)]) == []


def test_a_day_count_that_is_not_that_cargos_margin_days_is_still_flagged():
    rows = [row(margin=6), row("[BL2]", margin=2)]
    assert check("[BL1]은 7일 남아요.", rows) != []  # 그 화물의 여유 일수가 아닌 N일
    assert check("[BL1]은 2일 남아요.", rows) != []  # 다른 화물의 여유 일수
    assert check("[BL1]은 6일, [BL2]는 2일 남아요.", rows) == []


def test_no_reason_text_of_the_verdict_names_a_confidence_so_quoting_it_never_trips_the_rule():
    # [왜] 11-17 R-185. 판정의 까닭 글에 확신 이름이 있으면 옮겨 쓸 때 걸린다. 이름을 뺐으니 예외가 필요 없다
    import re

    cfg = load_rules("verify")["vessel_verdict"]
    texts = [*load_rules("verdict")["notes"].values(), *load_rules("verdict")["info"].values()]
    pattern = re.compile(r"확신\s*(?:은|이|을|도)?\s*(" + "|".join(cfg["confidence_names"]) + ")")
    assert [t for t in texts if pattern.search(t)] == []
    assert check("[BL1]의 확신을 부분이라고 봐요.", [row(confidence="unknown")]) != []


def test_the_name_lists_in_the_rules_are_the_labels_the_code_writes():
    cfg = load_rules("verify")["vessel_verdict"]
    assert cfg["grade_names"] == list(GRADE_LABEL.values())
    assert cfg["confidence_names"] == list(CONFIDENCE_LABEL.values())


# --- 판정 블록 줄을 그대로 옮긴 초안 ---

NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)
PICKS = {"TESTVSL0002": 1, "TESTVSL0005": 1, "TESTVSL0007": 1, "TESTVSL0008": 1}


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.mark.parametrize("number", [f"TESTVSL000{n}" for n in range(1, 9)])
def test_a_draft_quoting_the_block_lines_verbatim_passes(agent_deps, number):
    # [왜] 신호 글과 참고 글에 숫자가 섞이는 경우까지: 재생 화물 여덟 개의 실제 판정의 블록 줄 전부로 돈다
    shipfinder.reset_state()
    deps = agent_deps(
        model=ToolModel(messages=iter([AIMessage("")] * 3)),
        now=lambda: NOW,
        write=lambda p: Draft(answer="x", citations=[], next_options=[], forwarder_message=""),
    )
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore(), vessel=True)
    config = {"configurable": {"thread_id": number}}
    graph.invoke({"text": f"{number} 어디쯤 왔어요?"}, config)
    if graph.get_state(config).interrupts:
        graph.invoke(Command(resume={"selected": PICKS[number]}), config)
    v = graph.get_state(config).values
    lines = vessel_lines(v["cargos"], v["vessels"], v["verdicts"])
    rows = [
        {**r, "ship_status": next(s["status"] for s in v["vessels"] if s["token"] == r["token"])}
        for r in v["verdicts"]
    ]
    dates = {d for cells in v.get("cargo_dates", {}).values() for d in cells.values()}
    draft = Draft(answer="\n".join(lines), citations=[], next_options=[], forwarder_message="")
    assert (
        verify(draft, [], {}, v["cargos"], v["mask_map"], date(2026, 9, 22), verdicts=rows, user_dates=dates)
        == []
    )
