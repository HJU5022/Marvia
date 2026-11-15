"""배 식별 단계의 화면 쪽 시험: 화물 카드의 배·판정 칸과 선택 카드 (계획 8b). 스위치를 켠 그래프만 본다."""

import json
from datetime import UTC, datetime

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from starlette.testclient import TestClient

from marvia.graph.main import build_main_graph
from marvia.server import build_app
from marvia.tools.rules import load_rules
from marvia.view import screen_view

NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)  # 한국 시각 09-22 12:00
CARD_KEYS = [
    "error",
    "fetched_at",
    "number",
    "port",
    "ship",
    "source",
    "stage",
    "stage_at",
    "verdict",
    "vessel",
]


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def served(agent_deps, now=NOW, vessel=True, first: list | None = None):
    deps = agent_deps(model=ToolModel(messages=iter([*(first or []), *[AIMessage("")] * 9])), now=lambda: now)
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore(), vessel=vessel)
    return TestClient(build_app(graph, lambda token: "user-a", web_origin="http://web.test", forget=print))


def run(client, thread: str, text: str = "", resume: list | None = None) -> list[dict]:
    payload: dict = {"threadId": thread, "runId": f"run-{thread}", "messages": []}
    if text:
        payload["messages"] = [{"id": "m1", "role": "user", "content": text}]
    if resume:
        payload["resume"] = resume
    response = client.post("/agui", json=payload, headers={"Authorization": "Bearer tok"})
    assert response.status_code == 200, response.text
    return [json.loads(line[6:]) for line in response.text.split("\n") if line.startswith("data: ")]


def cards(events: list[dict]) -> list[dict]:
    return [e["snapshot"] for e in events if e["type"] == "STATE_SNAPSHOT"][-1]["cargos"]


def test_cargo_card_carries_ship_and_verdict_in_fixed_words(agent_deps):
    events = run(served(agent_deps), "s1", "TESTVSL0001 TESTVSL0003 어디쯤 왔어요?")
    assert events[-1]["outcome"] == {"type": "success"}
    first, second = cards(events)
    assert sorted(first) == CARD_KEYS and first["number"] == "TESTVSL0001"
    assert first["ship"] == {
        "status": "confirmed",
        "reason": "맞춰 본 칸은 호출부호예요. 입항 신고의 호출부호와 같아요",
        "detail": None,
        "check": None,
        "name": "TEST CARGO A",
        "call_sign": "QQTST1",
        "mmsi": "999000001",
    }
    cell = first["verdict"]
    assert (cell["grade"], cell["grade_label"], cell["confidence"], cell["schedule"]) == (
        "fine",
        "순항",
        "확실",
        "일정 모름",  # 처음 알던 도착 예정을 받지 않아 지연을 보지 못했다: 일정 칸은 비어 있다
    )
    assert cell["eta"].startswith("2026-09-24T12:00") and cell["eta_source"] == "해수부 입항 예정"
    assert cell["signals"] == [] and cell["notes"] == []
    # 판매 예정일과 처음 알던 도착 예정을 받는 통로가 아직 없다. 카드가 그렇다고 말한다
    assert cell["margin_days"] is None
    assert cell["info"] == [
        "판매 예정일을 받지 않아 여유 일수는 세지 않았어요. 배와 통관 상태만으로 본 등급이에요",
        "처음 알던 도착 예정이 없어 지연은 보지 못했어요",
    ]
    # 배를 확인하지 못한 화물: 등급을 지어내지 않고 "등급 없음"과 그 까닭을 보인다
    assert second["ship"]["status"] == "none" and second["ship"]["reason"] == "배 후보를 찾지 못했어요"
    assert second["ship"]["name"] is None and second["ship"]["mmsi"] is None
    lost = second["verdict"]
    assert lost["grade"] is None and lost["grade_label"] == "등급 없음" and lost["schedule"] == "일정 모름"
    assert lost["confidence"] == "불명" and lost["eta"] is None and lost["eta_source"] is None
    assert "도착 시각을 알 출처가 없어 등급을 내지 않았어요" in lost["notes"]


def test_lookup_failure_texts_differ_between_quota_and_a_passing_failure(agent_deps, monkeypatch):
    from marvia.identify.models import ToolError
    from marvia.tools import shipfinder

    quota = ToolError(code="quota_exhausted", message="오늘 조회할 수 있는 횟수를 다 썼어요", retryable=False)
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: quota)
    ship = cards(run(served(agent_deps), "s5", "TESTVSL0004 어디쯤 왔어요?"))[0]["ship"]
    assert ship["reason"] == "배 위치 서비스에서 후보를 받지 못했어요"
    assert ship["detail"] == "오늘 조회할 수 있는 횟수를 다 썼어요"  # 클라이언트의 정한 글 그대로
    busy = ToolError(code="busy", message="서비스가 바빠요. 잠시 뒤 다시 조회할 수 있어요", retryable=True)
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: busy)
    again = cards(run(served(agent_deps), "s6", "TESTVSL0004 어디쯤 왔어요?"))[0]["ship"]
    assert again["detail"] != ship["detail"] and "잠시 뒤" in again["detail"]


def test_cargo_off_the_ship_says_so_and_shows_customs_only(agent_deps):
    card = cards(run(served(agent_deps), "s7", "TESTVSL0006 어디쯤 왔어요?"))[0]
    assert card["ship"]["reason"] == "배에서 내린 화물이라 배 위치는 보지 않았어요"
    assert (card["verdict"]["grade_label"], card["verdict"]["eta"]) == ("순항", None)
    assert card["verdict"]["info"] == [
        "배에서 내린 화물이라 배 위치는 보지 않았어요. 통관 단계만으로 본 등급이에요"
    ]


def test_a_cargo_the_loop_looked_up_itself_says_the_ship_was_not_looked_at_this_turn(agent_deps):
    # [왜] 루프 안에서 lookup_cargo로 새로 찾은 화물은 배 식별 단계를 지나지 않는다(결정 3). "확인한 뒤에 보여
    #      드려요"가 아니라 사실대로 말한다
    values = {
        "cargos": [{"token": "[BL1]", "facts": {"stage": "입항", "fetched_at": "2026-09-22T03:00:00Z"}}],
        "mask_map": {"[BL1]": "TESTVSL0001"},
        "vessels": [],
        "verdicts": [],
    }
    card = screen_view(values, vessel=True)["cargos"][0]
    assert card["ship"]["reason"] == "이번 차례에는 배를 보지 않았어요" and card["verdict"] is None


def test_the_cards_follow_the_server_switch_not_leftover_values_in_the_notebook(agent_deps):
    # [왜] 스위치를 켰다가 끈 대화의 공책에는 vessels·verdicts가 남아 있다. 꺼진 서버는 그 칸을 보이지 않는다
    values = {
        "cargos": [{"token": "[BL1]", "facts": {"stage": "입항", "fetched_at": "2026-09-22T03:00:00Z"}}],
        "mask_map": {"[BL1]": "TESTVSL0001"},
        "vessels": [{"token": "[BL1]", "status": "confirmed", "reason": "mrn_call_sign"}],
        "verdicts": [],
    }
    assert sorted(screen_view(values, vessel=False)["cargos"][0]) == sorted(
        set(CARD_KEYS) - {"ship", "verdict"}
    )
    off = served(agent_deps, vessel=False)
    assert sorted(cards(run(off, "s8", "TESTVSL0001"))[0]) == sorted(set(CARD_KEYS) - {"ship", "verdict"})


def test_triggered_signals_are_named_on_the_card(agent_deps):
    late = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)  # 마지막 위치 수신 뒤 9시간 반
    cell = cards(run(served(agent_deps, now=late), "s2", "TESTVSL0001 어디쯤 왔어요?"))[0]["verdict"]
    assert cell["grade_label"] == "주의" and cell["signals"] == ["배 위치가 한동안 들어오지 않았어요"]


def test_every_signal_info_and_note_has_a_card_word():
    cfg, rules = load_rules("vessel"), load_rules("verdict")
    assert set(cfg["labels"]["signals"]) == set(rules["signal_ids"])
    for name in ("over_cap", "call_limit", "not_looked", "landed", "lookup_failed"):
        assert name in cfg["reasons"], name
    assert "ship_unchecked" in rules["notes"]  # 확신 상한의 까닭 글은 판정 쪽(rules/verdict.yaml)에 있다


def test_choice_card_shows_real_names_in_place_of_placeholders_and_the_typed_text_becomes_a_number(
    agent_deps,
):
    client = served(agent_deps)
    events = run(client, "s3", "TESTVSL0002 어디쯤 왔어요?")
    outcome = events[-1]["outcome"]
    assert outcome["type"] == "interrupt"
    card = outcome["interrupts"][0]
    meta = card["metadata"]
    assert card["reason"] == "choice" and "TESTVSL0002" in meta["question"] and meta["recommended"] == 0
    assert [o["label"] for o in meta["options"]] == ["모르겠어요", "TEST CARGO A", "TEST CARGO A"]
    first, second = meta["options"][1]["description"], meta["options"][2]["description"]
    missing = "MRN)로 찾은 입항 신고가 없어 서류로 확정하지 않았어요"
    assert "호출부호 QQTST1 · 배 번호 999000001" in first and missing in first
    assert "호출부호 없음 · 배 번호 999000002" in second and missing in second
    assert "{ship" not in json.dumps(meta, ensure_ascii=False)  # 자리표가 남지 않는다
    assert "candidates" not in meta and "token" not in meta  # 화면에는 카드 칸만 간다
    waiting = cards(events)[0]
    assert waiting["ship"]["status"] == "ask" and waiting["verdict"] is None
    # 직접 입력: 서버가 후보와 맞춰 번호로 바꿔 보낸다. 그래프는 사용자가 적은 호출부호를 받지 않는다
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"custom": "qqtst1 이에요"}}]
    events = run(client, "s3", resume=resume)
    assert events[-1]["outcome"] == {"type": "success"}
    chosen = cards(events)[0]
    assert chosen["ship"]["reason"] == "고르신 배로 봤어요" and chosen["ship"]["mmsi"] == "999000001"
    assert (
        chosen["verdict"]["confidence"] == "부분"
        and "호출부호를 맞춰 보지 못해" in chosen["verdict"]["notes"][0]
    )


@pytest.mark.parametrize(
    ("typed", "reason"),
    [
        ("모르겠어요 잘", "배를 모른다고 하셔서 배 없이 진행했어요"),
        ("QQTST1과 QQTST3 둘 다", "배를 모른다고 하셔서 배 없이 진행했어요"),
    ],
)
def test_typed_text_that_matches_no_single_candidate_is_a_skip(agent_deps, typed, reason):
    client = served(agent_deps)
    card = run(client, "s9", "TESTVSL0002 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"custom": typed}}]
    assert cards(run(client, "s9", resume=resume))[0]["ship"]["reason"] == reason


def test_cancelled_card_goes_on_without_a_ship_and_says_so_in_the_answer(agent_deps):
    client = served(agent_deps)
    card = run(client, "s4", "TESTVSL0002 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
    events = run(client, "s4", resume=[{"interruptId": card["id"], "status": "cancelled"}])
    assert events[-1]["outcome"] == {"type": "success"}
    after = cards(events)[0]
    assert after["ship"]["reason"] == "답이 없어 배 없이 진행했어요" and after["verdict"]["grade"] is None
    answer = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert "TESTVSL0002 화물의 배를 확인하지 못해 배 정보 없이 진행했어요" in answer


def test_a_hidden_candidate_can_be_picked_by_typing_its_call_sign(agent_deps):
    # [왜] 카드에는 후보가 둘만 보이지만 후보는 셋이다. 직접 입력은 보이지 않는 셋째도 맞춘다.
    #      번호가 카드의 선택지 수를 넘어도 서버가 거절하지 않는다(번호는 후보 목록 안이다)
    client = served(agent_deps)
    card = run(client, "s10", "TESTVSL0002 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
    assert len(card["metadata"]["options"]) == 3
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"custom": "qqtst3 이에요"}}]
    events = run(client, "s10", resume=resume)
    assert events[-1]["outcome"] == {"type": "success"}
    assert cards(events)[0]["ship"]["mmsi"] == "999000003"


def test_an_old_unanswered_ship_question_does_not_take_over_a_later_card(agent_deps):
    # [왜] 공책의 vessel_question은 다음 차례가 비우기 전까지 남는다. 그 사이에 번호를 묻는 카드(오타)가 뜨면
    #      사용자가 적은 번호는 그 카드의 답이다. 배 후보와 맞춰 바꾸면 안 된다
    client = served(agent_deps)
    first = run(client, "s11", "TESTVSL0002 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
    assert first["reason"] == "choice"
    later = run(client, "s11", "DEMU1234565 어디야?")[-1]["outcome"]["interrupts"][0]  # 오타 번호를 묻는 카드
    assert "컨테이너 번호 모양인데" in later["metadata"]["question"]
    resume = [{"interruptId": later["id"], "status": "resolved", "payload": {"custom": "TESTVSL0001"}}]
    events = run(client, "s11", resume=resume)
    assert events[-1]["outcome"] == {"type": "success"}
    assert cards(events)[0]["number"] == "TESTVSL0001"  # 적은 번호가 그대로 읽혔다


def test_typing_a_call_sign_that_two_ships_share_cannot_pick_either_and_the_mmsi_can(agent_deps):
    # 호출부호가 같은 두 배(TESTVSL0007): 호출부호만 적으면 어느 배인지 모른다(0번, 모르겠어요). 배 번호를
    #      적으면 그 배다
    client = served(agent_deps)
    card = run(client, "s12", "TESTVSL0007 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"custom": "qqtwn"}}]
    skipped = cards(run(client, "s12", resume=resume))[0]
    assert skipped["ship"]["reason"] == "배를 모른다고 하셔서 배 없이 진행했어요"
    card = run(client, "s13", "TESTVSL0007 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"custom": "배 번호 999000008"}}]
    picked = cards(run(client, "s13", resume=resume))[0]
    assert (
        picked["ship"]["mmsi"] == "999000008" and picked["ship"]["check"] == "같은 호출부호의 배가 여럿이에요"
    )
    assert picked["verdict"]["confidence"] != "확실"  # 위치와 일정이 없어 등급도 없다(불명). 확실은 아니다


def test_a_picked_ship_at_a_ship_watching_stage_never_reads_as_sure(agent_deps):
    # (가) 카드 글은 status가 아니라 reason과 basis로 만든다. 배를 보는 단계에서 고른 배는 확신 상한(부분)
    #      때문에 "확실"로 보이지 않는다(내린 단계의 화물은 아래 시험이 따로 본다).
    #      위치와 입항 일정이 모두 있는 배(TESTVSL0002의 QQTST1), 같은 호출부호의 두 배 가운데 하나를 고른
    #      경우를 본다
    client = served(agent_deps)
    card = run(client, "s14", "TESTVSL0002 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"selected": 1}}]
    picked = cards(run(client, "s14", resume=resume))[0]
    assert picked["ship"]["status"] == "user_choice" and picked["ship"]["reason"] == "고르신 배로 봤어요"
    assert picked["ship"]["check"] == "입항 신고 번호(MRN)로 찾은 입항 신고가 없어 서류로 확정하지 않았어요"
    assert picked["verdict"]["grade_label"] == "순항" and picked["verdict"]["confidence"] == "부분"
    assert "호출부호를 맞춰 보지 못해 확신을 부분으로 낮췄어요" in picked["verdict"]["notes"]
    shown = json.dumps(picked, ensure_ascii=False)
    assert "확실" not in shown  # 고른 배의 카드 어디에도 "확실"이 없다
    card = run(client, "s15", "TESTVSL0007 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"selected": 1}}]
    twin = cards(run(client, "s15", resume=resume))[0]
    assert (
        twin["ship"]["status"] == "user_choice" and twin["ship"]["check"] == "같은 호출부호의 배가 여럿이에요"
    )
    assert "확실" not in json.dumps(twin, ensure_ascii=False)


def test_a_picked_ship_whose_cargo_has_landed_is_sure_and_the_card_says_it_was_not_watched(
    agent_deps, monkeypatch
):
    # [왜] 11-16 R-139. 내린 화물은 통관만 보므로 고른 배라도 확신 상한이 걸리지 않고 확실이다.
    #      그 카드에 "고르신 배로 봤어요"만 있으면 배를 보고 확실이라 한 것처럼 읽히니, 배를 보지 않았다는
    #      참고 글이 같은 카드에 함께 보여야 한다
    from marvia.graph import identify
    from marvia.tools.unipass_replay import lookup_cargo

    client = served(agent_deps)
    card = run(client, "s16", "TESTVSL0002 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"selected": 1}}]
    cards(run(client, "s16", resume=resume))
    monkeypatch.setattr(
        identify, "lookup_cargo", lambda number: lookup_cargo(number).model_copy(update={"stage": "반입신고"})
    )
    landed = cards(run(client, "s16", "TESTVSL0002 지금은요?"))[0]
    assert landed["ship"]["reason"] == "고르신 배로 봤어요"
    assert landed["verdict"]["confidence"] == "확실"
    assert "배에서 내린 화물이라 배 위치는 보지 않았어요" in json.dumps(landed["verdict"], ensure_ascii=False)


def test_an_injected_ask_user_card_with_ship_placeholders_is_not_treated_as_the_ship_card(
    agent_deps, monkeypatch
):
    # [왜] 11-16 R-144. 배 카드인지는 선택지의 "{ship" 글이 아니라 멈춘 노드(ask_vessel)로 가른다. 모델이 부른
    #      ask_user의 선택지가 같은 자리표를 써도(공책에 옛 배 질문이 남아 있어도) 카드 글은 그대로 보이고
    #      직접 적은 답이 번호로 바뀌지 않는다
    from marvia import server

    options = [{"label": "{ship1}", "description": "{ship1_info}"}, {"label": "{ship2}", "description": "x"}]
    call = AIMessage(
        content="",
        tool_calls=[
            {"name": "ask_user", "args": {"question": "어느 쪽이에요?", "options": options}, "id": "c1"}
        ],
    )
    client = served(agent_deps, first=[call])
    assert (
        run(client, "s17", "TESTVSL0002 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]["reason"] == "choice"
    )
    stopped = run(client, "s17", "그냥 물어볼게요")[-1]["outcome"]["interrupts"][0]
    assert stopped["metadata"]["question"] == "어느 쪽이에요?"
    assert [o["label"] for o in stopped["metadata"]["options"]] == [
        "{ship1}",
        "{ship2}",
    ]  # 이름으로 바뀌지 않는다
    monkeypatch.setattr(
        server, "vessel_choice", lambda *a, **k: pytest.fail("ask_user 답을 배 번호로 바꿨다")
    )
    resume = [{"interruptId": stopped["id"], "status": "resolved", "payload": {"custom": "qqtst1"}}]
    assert run(client, "s17", resume=resume)[-1]["outcome"] == {"type": "success"}
