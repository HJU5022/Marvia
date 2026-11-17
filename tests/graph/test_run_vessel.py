"""평가 실행기의 --vessel 인자와 기준 시각 시험 (계획 8c T8, CC10, CC14, 결정 C8). 키 없이 돈다."""

from datetime import UTC, date, datetime

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from marvia.eval import run as eval_run
from marvia.eval.dataset import Item
from marvia.tools import shipfinder
from marvia.tools.deadlines import KST
from marvia.tools.rules import load_rules

AS_OF = date(2026, 11, 6)
BASE = {"id": "T1", "group": "related", "kind": "시험", "behaviour": ["answer"]}


def item(**more) -> Item:
    return Item.model_validate({**BASE, "question": "TESTVSL0001 어디쯤 왔어요?", **more})


class Spy(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, *args, **kwargs):
        SEEN.append("\n".join(str(m.content) for m in messages))
        BOUND.append(len(messages))
        return super()._generate(messages, *args, **kwargs)


SEEN: list[str] = []
BOUND: list[int] = []


@pytest.fixture(autouse=True)
def _fresh():
    shipfinder.reset_state()
    SEEN.clear()
    BOUND.clear()


@pytest.fixture
def built(monkeypatch):
    graphs = []
    real = eval_run.build_main_graph
    monkeypatch.setattr(
        eval_run, "build_main_graph", lambda *a, **k: graphs.append(real(*a, **k)) or graphs[-1]
    )
    return graphs


def evaluate(agent_deps, asked: Item, **kwargs):
    deps = agent_deps(model=Spy(messages=iter([AIMessage("끝")] * 6)))
    return eval_run.evaluate_item(deps, asked, "agent", AS_OF, load_rules("pricing"), **kwargs)


def test_the_argument_turns_the_graph_on_and_only_the_argument(agent_deps, built):
    row, _ = evaluate(agent_deps, item(), vessel=True)
    assert "vessel" in built[0].nodes and row["vessel_graph"] is True


def test_the_environment_alone_never_turns_it_on(agent_deps, built, monkeypatch):
    monkeypatch.setenv("MARVIA_VESSEL", "on")
    row, _ = evaluate(agent_deps, item())
    assert "vessel" not in built[0].nodes and row["vessel_graph"] is False


def test_a_mismatch_between_the_argument_and_the_graph_is_a_problem():
    meta = {"unipass_mode": "replay", "annex_units": 1, "vessel": "on"}
    summary = {}
    ok = [{"id": "N01", "vessel_graph": True}]
    off = [{"id": "N01", "vessel_graph": False}]
    assert not [p for p in eval_run.run_problems(meta, ok, summary, set()) if "--vessel" in p]
    (problem,) = [p for p in eval_run.run_problems(meta, off, summary, set()) if "--vessel" in p]
    assert "N01" in problem
    # 반대: 끈 길로 돌렸는데 그래프에 배 단계가 있다
    problems = eval_run.run_problems({**meta, "vessel": "off"}, ok, summary, set())
    assert [p for p in problems if "--vessel off" in p]
    # 옛 결과 파일(meta.vessel 없음)은 이 검사를 하지 않는다
    assert not [
        p for p in eval_run.run_problems({**meta, "vessel": None}, off, summary, set()) if "--vessel" in p
    ]


def test_the_meta_records_the_switch_and_the_clock(agent_deps):
    assert eval_run.vessel_meta(True)["vessel"] == "on" and eval_run.vessel_meta(False)["vessel"] == "off"
    assert len(eval_run.vessel_meta(True)["vessel_replay_sha256"]) == 64
    row, _ = evaluate(agent_deps, item(now=datetime(2026, 9, 22, 3, 0, tzinfo=UTC)), vessel=True)
    assert row["now"] == "2026-09-22T03:00:00+00:00"
    row, _ = evaluate(agent_deps, item())
    assert row["now"] == "2026-11-06T09:00:00+09:00"  # v3 문항: as_of 날짜 09:00 한국 시각


def test_each_item_has_one_clock_the_item_now_or_the_set_date_at_nine_in_korea():
    assert eval_run.item_clock(item(), AS_OF) == datetime(2026, 11, 6, 9, tzinfo=KST)
    fixed = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)
    assert eval_run.item_clock(item(now=fixed), AS_OF) == fixed
    # 실제 시계가 아니다
    assert eval_run.item_clock(item(), AS_OF).year == 2026


def test_the_model_sees_todays_date_from_the_items_clock_on_the_on_path(agent_deps):
    # 문항의 now 09-26 16:00 UTC = 한국 09-27. as_of(2026-11-06)나 실제 날짜가 아니다
    asked = item(now=datetime(2026, 9, 26, 16, 0, tzinfo=UTC))
    evaluate(agent_deps, asked, vessel=True)
    assert "Today is 2026-09-27" in SEEN[0]


def test_the_off_path_keeps_the_set_date_as_today_and_has_no_vessel_text(agent_deps):
    evaluate(agent_deps, item())
    assert "Today is 2026-11-06" in SEEN[0]  # as_of
    assert "vessel_lines" not in SEEN[0] and "Ship verdicts" not in SEEN[0]


def test_vessel_only_items_are_skipped_when_the_argument_is_off():
    plain, only = item(), item(id="N01", vessel_only=True)
    assert eval_run.runnable([plain, only], vessel=False) == [plain]
    assert eval_run.runnable([plain, only], vessel=True) == [plain, only]


def test_an_on_run_gives_the_card_the_items_reply_and_records_the_new_metrics(agent_deps):
    # N02 꼴: 같은 이름의 배에서 둘째 후보를 고른다. 모델의 답은 가짜 작성자가 쓴 글이다
    from marvia.graph.schemas import Draft

    asked = item(
        question="TESTVSL0002 화물은 제때 들어와요?",
        behaviour=["choice"],
        replies=[1],
        now=datetime(2026, 9, 22, 3, 0, tzinfo=UTC),
        expect_verdict=[{"token": "[BL1]", "grade": "순항", "confidence": "부분"}],
    )
    # [왜] 검증자는 "등급" 옆의 이름만 본다. "판정은 경계예요"는 검증자를 지나 답에 남고 탐지기가 센다
    wrong = Draft(answer="[BL1]의 판정은 경계예요.", citations=[], next_options=[], forwarder_message="")
    prompts: list[str] = []
    deps = agent_deps(
        model=Spy(messages=iter([AIMessage("끝")] * 6)), write=lambda p: prompts.append(p) or wrong
    )
    row, raw = eval_run.evaluate_item(deps, asked, "agent", AS_OF, load_rules("pricing"), vessel=True)
    assert row["behaviour"] == "choice" and row["vessel_graph"] is True
    # 문항의 답(둘째 후보)이 카드에 갔다. 답이 없었다면 권장안(배 없이 진행)이다
    assert "고르신 배로 봤어요" in prompts[0] and "배 없이 진행" not in prompts[0]
    assert (row["detector"], row["assertive"], row["ship_leak"]) == (1, 0, False)
    assert raw["detector_sentences"] == ["[BL1]의 판정은 경계예요."]
    # 끈 길 줄에는 새 칸이 없다
    off_row, _ = evaluate(agent_deps, item())
    assert not {"detector", "assertive", "ship_leak"} & set(off_row)
