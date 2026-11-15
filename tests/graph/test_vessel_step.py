"""배 식별 단계 시험 (계획 8b). 바깥 조회는 재생 데이터이고 키 없이 돈다."""

import json
from datetime import UTC, datetime

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from marvia.graph import vessel
from marvia.graph.main import build_main_graph
from marvia.graph.schemas import Draft
from marvia.identify.models import CargoFacts, ToolError
from marvia.tools import mof, shipfinder
from marvia.tools.rules import load_rules
from marvia.tools.shipfinder import VesselHit
from marvia.tools.unipass_replay import lookup_cargo


def facts(number: str) -> CargoFacts:
    found = lookup_cargo(number)
    assert isinstance(found, CargoFacts)
    return found


@pytest.fixture(autouse=True)
def _fresh():
    shipfinder.reset_state()


def test_mrn_leads_to_one_ship_and_the_call_sign_is_what_was_checked(monkeypatch):
    monkeypatch.setattr(
        mof, "plans_for", lambda *a, **k: pytest.fail("호출부호를 맞췄는데 입항 신고를 받았다")
    )
    found = vessel.find_vessel(facts("TESTVSL0001"))
    assert found == {
        "status": "confirmed",
        "reason": "mrn_call_sign",
        "basis": ["call_sign"],
        "cap": None,
        "mmsi": "999000001",
        "call_sign": "QQTST1",
        "name": "TEST CARGO A",
    }


def test_same_name_ships_are_not_picked_and_each_says_why_papers_cannot_settle_it():
    # TESTVSL0002: MRN의 입항 신고가 없어(서류로 확정하는 길이 닫힘) 같은 이름의 셋 가운데 고르지 못한다
    found = vessel.find_vessel(facts("TESTVSL0002"))
    assert found["status"] == "ask" and found["reason"] == "mrn_report_missing"
    assert [c["mmsi"] for c in found["candidates"]] == ["999000001", "999000002", "999000003"]
    assert "mmsi" not in found  # 고르지 않았다
    # 후보마다 서류로 맞춰 본 이유가 따라온다(선택 카드가 보인다). 상한은 고른 뒤 검사가 건다
    assert {c["check"] for c in found["candidates"]} == {"mrn_report_missing"}
    assert all("cap" not in c for c in found["candidates"])
    assert (found["lookup"], found["mrn_call_sign"]) == ("not_found", None)  # 고른 뒤 검사가 쓸 것


def test_papers_decide_between_two_ships_only_when_the_mrn_report_has_no_call_sign(monkeypatch):
    # TESTVSL0004: MRN의 입항 신고가 있고 호출부호가 없다. 서류(입항일 09-24, 적재항 QINGDAO)가 한 척에만
    #      맞는다
    hits = [VesselHit(mmsi=999000004, call_sign="QQTST4"), VesselHit(mmsi=999000005, call_sign="QQTST9")]
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: hits)
    found = vessel.find_vessel(facts("TESTVSL0004"))
    assert (found["status"], found["reason"], found["mmsi"]) == ("confirmed", "papers_match", "999000004")
    assert (found["basis"], found["cap"]) == (["entry_date", "loading_port"], "partial")


def test_one_ship_found_by_name_is_checked_against_its_own_sailing_report():
    # TESTVSL0004: 한 척이고 그 배의 입항 신고가 입항일과 적재항이 맞는다. 맞춰 본 칸은 둘이고 호출부호는
    #      아니다
    found = vessel.find_vessel(facts("TESTVSL0004"))
    assert (found["status"], found["reason"], found["basis"], found["cap"]) == (
        "confirmed",
        "papers_match",
        ["entry_date", "loading_port"],
        "partial",
    )
    # TESTVSL0005: 한 척인데 MRN이 없다. 이름이 닮았을 뿐이니 서류가 맞아도 확정하지 않고 되묻는다
    asked = vessel.find_vessel(facts("TESTVSL0005"))
    assert (asked["status"], asked["reason"]) == ("ask", "mrn_report_missing")
    assert [c["name"] for c in asked["candidates"]] == ["TEST CARGO E"]


def test_ships_sharing_a_call_sign_are_asked_and_a_pick_among_them_is_capped():
    found = vessel.find_vessel(facts("TESTVSL0007"))
    assert (found["status"], found["reason"]) == ("ask", "same_call_sign_many_mmsi")
    assert [(c["mmsi"], c["check"]) for c in found["candidates"]] == [
        ("999000007", "mrn_call_sign"),  # 그 후보 하나만 있다면 호출부호가 맞는다
        ("999000008", "mrn_call_sign"),
    ]
    assert (found["lookup"], found["mrn_call_sign"]) == ("found_signed", "QQTWN")


def test_a_failed_mrn_lookup_is_a_card_not_a_papers_confirmation(monkeypatch):
    broken = ToolError(code="too_many", message="입항 신고가 너무 많아요", retryable=False)
    monkeypatch.setattr(mof, "plans_near", lambda *a, **k: broken)
    found = vessel.find_vessel(facts("TESTVSL0004"))  # 서류는 맞지만 MRN으로 입항 신고를 받지 못했다
    assert (found["status"], found["reason"]) == ("ask", "mrn_lookup_failed")
    assert [c["check"] for c in found["candidates"]] == ["mrn_lookup_failed"]


def test_no_candidate_no_clue_and_failed_lookup_never_name_a_ship(monkeypatch):
    assert vessel.find_vessel(facts("TESTVSL0003")) == {"status": "none", "reason": "no_candidate"}
    bare = CargoFacts(number="TESTVSL0009", stage="입항", fetched_at=datetime.now(UTC))
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: pytest.fail("단서 없이 찾았다"))
    assert vessel.find_vessel(bare) == {"status": "unknown", "reason": "no_clue"}
    quota = ToolError(code="quota_exhausted", message="오늘 조회할 수 있는 횟수를 다 썼어요", retryable=False)
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: quota)
    # 클라이언트의 정한 오류 글을 그대로 싣는다: 한도 소진("내일")과 일시 실패("잠시 뒤")가 갈린다
    assert vessel.find_vessel(facts("TESTVSL0004")) == {
        "status": "unknown",
        "reason": "lookup_failed",
        "detail": "오늘 조회할 수 있는 횟수를 다 썼어요",
    }


def test_cargo_off_the_ship_is_not_looked_up_at_all(monkeypatch):
    for name in ("plans_near", "plans_for"):
        monkeypatch.setattr(mof, name, lambda *a, **k: pytest.fail("내린 화물인데 해수부를 불렀다"))
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: pytest.fail("내린 화물인데 찾았다"))
    assert vessel.find_vessel(facts("TESTVSL0006")) == {"status": "unknown", "reason": "landed"}


def test_too_many_candidates_are_asked_without_one_schedule_call_each(monkeypatch):
    many = [VesselHit(mmsi=999000010 + n, call_sign=f"QQMNY{n}", ship_name="TEST CARGO A") for n in range(7)]
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: many)
    monkeypatch.setattr(mof, "plans_for", lambda *a, **k: pytest.fail("후보 수 상한을 넘었는데 조회했다"))
    found = vessel.find_vessel(facts("TESTVSL0004"))  # 서류로 확정하는 길이 열린 화물
    assert found["status"] == "ask" and found["reason"] == "schedule_lookup_failed"
    assert len(found["candidates"]) == 5  # rules/vessel.yaml max_candidates
    assert len(found["hits"]) == 7  # 검색 결과 전체는 자르지 않는다(같은 호출부호의 배를 가리는 데 쓴다)


def test_the_call_budget_per_cargo_stops_before_the_limit_is_passed(monkeypatch):
    # 한 화물의 해수부·ShipFinder 요청 수는 rules의 상한을 넘지 않는다(쪽 넘김은 쪽 수 상한만큼 센다).
    # 닿으면 배를 지어내지 않고 조회 한도에 닿았다고 한다
    calls = []
    for name, module in (("plans_near", mof), ("plans_for", mof), ("vessel_candidates", shipfinder)):
        real = getattr(module, name)
        monkeypatch.setattr(module, name, lambda *a, _n=name, _r=real, **k: calls.append(_n) or _r(*a, **k))
    cfg = load_rules("vessel")
    vessel.find_vessel(facts("TESTVSL0002"))
    assert calls[0] == "plans_near" and calls.count("vessel_candidates") == 1
    monkeypatch.setitem(cfg, "max_find_calls", cfg["max_mrn_pages"])  # MRN 길만 쓰면 바닥이다
    calls.clear()
    assert vessel.find_vessel(facts("TESTVSL0002")) == {"status": "unknown", "reason": "call_limit"}
    assert calls == ["plans_near"]  # 배 검색은 부르지 않았다
    monkeypatch.setitem(cfg, "max_find_calls", cfg["max_mrn_pages"] - 1)
    calls.clear()
    assert vessel.find_vessel(facts("TESTVSL0002")) == {"status": "unknown", "reason": "call_limit"}
    assert calls == []  # MRN 길의 쪽 수도 못 쓰면 아무것도 부르지 않는다


def test_the_same_day_sailing_list_is_fetched_once_per_turn(monkeypatch):
    calls = []
    real = mof.plans_near
    monkeypatch.setattr(mof, "plans_near", lambda *a, **k: calls.append(1) or real(*a, **k))
    near: dict = {}
    for number in ("TESTVSL0001", "TESTVSL0002", "TESTVSL0004"):
        vessel.find_vessel(facts(number), near=near)
    assert len(calls) == 1  # 세 화물 모두 부산, 같은 입항일


def test_the_budget_numbers_add_up_and_leave_the_mrn_path_enough_pages_for_busan():
    cfg = load_rules("vessel")
    assert cfg["max_find_calls"] == cfg["max_mrn_pages"] + 1 + cfg["max_candidates"]
    assert cfg["max_find_calls"] + cfg["verdict_calls"] + cfg["pick_calls"] == cfg["max_calls"]
    # v1이 부산 5일치를 12쪽으로 쟀다. 창이 3일이면 약 7쪽이라 쪽 상한이 그보다 커야
    # MRN 길이 too_many로 끝나지 않는다
    window_days = 2 * load_rules("ports")["ports"]["KRPUS"]["mrn_search_days"] + 1
    assert cfg["max_mrn_pages"] >= -(-12 * window_days // 5)


# 아래는 그래프에 붙인 단계 시험. 스위치를 켠 그래프(vessel=True)만 본다. 꺼진 쪽은 test_vessel_off.py가 본다
NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)  # 한국 시각 09-22 12:00. 재생 배의 마지막 위치 수신 30분 뒤


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def graph_on(agent_deps, prompts: list | None = None, now=NOW):
    def write(prompt):
        if prompts is not None:
            prompts.append(prompt)
        return Draft(answer="확인했어요", citations=[], next_options=[], forwarder_message="")

    deps = agent_deps(model=ToolModel(messages=iter([AIMessage("")] * 9)), now=lambda: now, write=write)
    return build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore(), vessel=True)


def run(graph, text: str, thread: str = "t"):
    config = {"configurable": {"thread_id": thread}}
    graph.invoke({"text": text}, config)
    return config, graph.get_state(config)


def test_confirmed_ship_gets_a_verdict_from_position_and_schedule(agent_deps):
    _, state = run(graph_on(agent_deps), "TESTVSL0001 어디쯤 왔어요?")
    assert not state.interrupts
    ship, cell = state.values["vessels"][0], state.values["verdicts"][0]
    assert (ship["token"], ship["status"], ship["mmsi"]) == ("[BL1]", "confirmed", "999000001")
    assert cell["token"] == "[BL1]" and cell["grade"] == "fine" and cell["eta_source"] == "mof_planned"
    assert cell["trusted_eta"].startswith("2026-09-24T12:00")  # 해수부 입항 예정 09-24 12:00(한국 시각)
    assert cell["confidence"] == "sure" and cell["schedule"] is None  # 호출부호를 맞췄고, 처음 예정은 없다
    assert "no_position" not in cell["notes"] and "no_schedule" not in cell["notes"]


def test_the_schedule_lookup_gets_the_customs_entry_date(agent_deps, monkeypatch):
    # [왜] 입항 일정은 세관 입항일 근처로 좁혀 받는다. 입항일을 넘기지 않으면 엉뚱한 날의 신고를 받는다
    seen = []
    real = mof.port_schedule
    monkeypatch.setattr(mof, "port_schedule", lambda *a, **k: (seen.append(k), real(*a, **k))[1])
    run(graph_on(agent_deps), "TESTVSL0001 어디쯤 왔어요?")
    assert seen and seen[0]["entry_date"] is not None


def test_papers_only_ship_is_capped_at_partial_even_with_every_other_input_clear(agent_deps, monkeypatch):
    # [왜] 11-15 판정. 호출부호를 맞추지 못하고 서류(입항일·적재항)로만 확정한 배는 확신이 부분을 넘지 못한다.
    #      TESTVSL0004의 배(QQTST4)는 위치 파일이 없어 이미 부분이다. 위치가 있는 배(QQTST1)로 상한이 실제로
    #      걸리는지 본다
    hits = [VesselHit(mmsi=999000001, call_sign="QQTST1"), VesselHit(mmsi=999000005, call_sign="QQTST9")]
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: hits)
    _, state = run(graph_on(agent_deps), "TESTVSL0004 어디쯤 왔어요?")
    ship, cell = state.values["vessels"][0], state.values["verdicts"][0]
    assert (ship["reason"], ship["basis"], ship["cap"]) == (
        "papers_match",
        ["entry_date", "loading_port"],
        "partial",
    )
    assert cell["grade"] == "fine" and cell["confidence"] == "partial" and "ship_unchecked" in cell["notes"]
    _, mrn = run(graph_on(agent_deps), "TESTVSL0001 어디쯤 왔어요?", "t2")
    assert (
        mrn.values["verdicts"][0]["confidence"] == "sure"
        and "ship_unchecked" not in mrn.values["verdicts"][0]["notes"]
    )


def test_without_any_arrival_time_there_is_no_grade_and_the_card_says_why(agent_deps, monkeypatch):
    _, state = run(graph_on(agent_deps), "TESTVSL0003 TESTVSL0004 어디쯤 왔어요?")
    ships = {v["token"]: v for v in state.values["vessels"]}
    cells = {v["token"]: v for v in state.values["verdicts"]}
    assert (ships["[BL1]"]["status"], ships["[BL1]"]["reason"]) == ("none", "no_candidate")
    assert cells["[BL1]"]["grade"] is None and cells["[BL1]"]["confidence"] == "unknown"
    assert {"no_position", "no_eta"} <= set(cells["[BL1]"]["notes"])
    # 서류로 확정한 배(위치 파일 없음)는 해수부 입항 예정이 있어 등급이 나오되 확신은 부분이다
    assert ships["[BL2]"]["status"] == "confirmed" and cells["[BL2]"]["eta_source"] == "mof_planned"
    assert (cells["[BL2]"]["grade"], cells["[BL2]"]["confidence"]) == ("fine", "partial")
    # 입항 일정도 못 받으면 도착 시각을 알 출처가 없어 등급이 없다
    failed = ToolError(code="timeout", message="시간 초과", retryable=True)
    monkeypatch.setattr(mof, "port_schedule", lambda *a, **k: failed)
    _, none_left = run(graph_on(agent_deps), "TESTVSL0004 어디쯤 왔어요?", "t2")
    cell = none_left.values["verdicts"][0]
    assert cell["grade"] is None and cell["confidence"] == "unknown" and "no_eta" in cell["notes"]


def test_cargo_off_the_ship_gets_a_customs_only_verdict_and_nothing_is_looked_up(agent_deps, monkeypatch):
    for module, name in (
        (shipfinder, "vessel_position"),
        (shipfinder, "vessel_candidates"),
        (mof, "port_schedule"),
    ):
        monkeypatch.setattr(module, name, lambda *a, **k: pytest.fail("내린 화물인데 바깥을 불렀다"))
    _, state = run(graph_on(agent_deps), "TESTVSL0006 어디쯤 왔어요?")
    ship, cell = state.values["vessels"][0], state.values["verdicts"][0]
    assert (ship["status"], ship["reason"]) == ("unknown", "landed")
    assert (cell["grade"], cell["confidence"], cell["schedule"], cell["info"]) == (
        "fine",
        "sure",
        None,
        ["landed"],
    )
    assert cell["trusted_eta"] is None and cell["notes"] == []


def test_same_name_ships_stop_for_a_choice_card_with_placeholders_not_names(agent_deps):
    _, state = run(graph_on(agent_deps), "TESTVSL0002 어디쯤 왔어요?")
    card = state.interrupts[0].value
    assert sorted(card) == ["kind", "options", "question", "recommended"] and card["kind"] == "choice"
    assert "[BL1]" in card["question"] and "TESTVSL0002" not in card["question"]
    assert card["recommended"] == 0 and card["options"][0]["label"] == "모르겠어요"
    assert [o["label"] for o in card["options"][1:]] == ["{ship1}", "{ship2}"]  # 합쳐 셋
    # [왜] 끼어들기 값은 트레이스와 체크포인트로 간다. 배 이름·호출부호·배 번호는 자리표로만 싣는다
    shown = json.dumps(card, ensure_ascii=False)
    assert not any(word in shown for word in ("TEST CARGO", "QQTST", "99900"))
    assert state.values["vessels"][0]["status"] == "ask" and state.values["verdicts"] == []


@pytest.mark.parametrize(
    ("reply", "status", "reason", "mmsi"),
    [
        ({"selected": 1}, "user_choice", "mrn_report_missing", "999000001"),
        ({"selected": 2}, "user_choice", "mrn_report_missing", "999000002"),
        ({"selected": 0}, "unknown", "user_skipped", None),
        ({"timeout": True}, "unknown", "no_answer", None),
    ],
)
def test_the_reply_to_the_choice_card_decides_and_no_answer_is_an_assumption(
    agent_deps, reply, status, reason, mmsi
):
    graph = graph_on(agent_deps)
    config, _ = run(graph, "TESTVSL0002 어디쯤 왔어요?")
    graph.invoke(Command(resume=reply), config)
    values = graph.get_state(config).values
    ship = values["vessels"][0]
    assert (ship["status"], ship["reason"], ship.get("mmsi")) == (status, reason, mmsi)
    assert values["vessel_question"] is None and len(values["verdicts"]) == 1
    noted = [a for a in values["assumptions"] if "배를 확인하지 못해" in a]
    assert len(noted) == (1 if reason == "no_answer" else 0)
    assert all("[BL1]" in a and "TEST CARGO" not in a for a in noted)  # 가정 글에 배 이름을 넣지 않는다


def test_a_picked_ship_stays_a_user_choice_with_its_reason_and_the_cap_reaches_the_judge(
    agent_deps, monkeypatch
):
    # (다) 공책에 user_choice와 그 reason이 그대로 남고 judge에 cap이 넘어간다
    seen = []
    real = vessel.judge
    monkeypatch.setattr(vessel, "judge", lambda *a, **k: seen.append(k.get("cap")) or real(*a, **k))
    graph = graph_on(agent_deps)
    config, _ = run(graph, "TESTVSL0002 어디쯤 왔어요?")
    seen.clear()
    graph.invoke(Command(resume={"selected": 1}), config)
    values = graph.get_state(config).values
    ship, cell = values["vessels"][0], values["verdicts"][0]
    # MRN으로 찾은 입항 신고가 없어 서류로도 맞춰 볼 수 없다. 사용자 선택만으로는 확실이 되지 않는다
    assert (ship["status"], ship["reason"], ship["basis"], ship["cap"]) == (
        "user_choice",
        "mrn_report_missing",
        [],
        "partial",
    )
    assert seen == ["partial"]  # judge가 받은 확신 상한 그대로
    assert cell["grade"] == "fine" and cell["confidence"] == "partial" and "ship_unchecked" in cell["notes"]


def test_a_pick_among_ships_sharing_a_call_sign_is_capped_even_though_the_call_sign_matches(agent_deps):
    graph = graph_on(agent_deps)
    config, state = run(graph, "TESTVSL0007 어디쯤 왔어요?")
    assert state.interrupts and state.values["vessels"][0]["reason"] == "same_call_sign_many_mmsi"
    graph.invoke(Command(resume={"selected": 1}), config)
    values = graph.get_state(config).values
    ship, cell = values["vessels"][0], values["verdicts"][0]
    assert (ship["status"], ship["reason"], ship["cap"]) == (
        "user_choice",
        "same_call_sign_many_mmsi",
        "partial",
    )
    assert "call_sign" not in ship["basis"]
    assert (
        cell["confidence"] != "sure" and "ship_unchecked" in cell["notes"]
    )  # 호출부호는 같지만 배를 가르지 못했다


def test_the_finder_never_calls_check_candidate_only_the_pick_step_does(monkeypatch):
    # (나) 배 찾기 단계(되묻기 전)는 check_candidate를 부르지 않는다: 그 검사는 사용자가 고른 뒤의 것이다.
    #      호출 시험과 소스 읽기(AST) 둘로 본다
    import ast
    import inspect

    monkeypatch.setattr(
        vessel, "check_candidate", lambda *a, **k: pytest.fail("고르기 전에 check_candidate를 불렀다")
    )
    for number in ("TESTVSL0001", "TESTVSL0002", "TESTVSL0004", "TESTVSL0005", "TESTVSL0007"):
        vessel.find_vessel(facts(number))
    tree = ast.parse(inspect.getsource(vessel))
    users = {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
        for call in ast.walk(fn)
        if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "check_candidate"
    }
    assert users == {"check_pick"}  # ask_vessel이 check_pick을 통해서만 부른다


def test_the_pick_refetches_only_the_picked_ships_report_and_a_failure_is_a_lookup_failure(
    agent_deps, monkeypatch
):
    # 서류로 맞추는 길(TESTVSL0004의 MRN 신고에 호출부호가 없음): 고른 뒤 그 배의 입항 신고를 한 번 받는다.
    #      그 요청도 화물당 상한(rules pick_calls)의 셈에 든다. 받지 못하면 조회 실패로 보고 확신 상한과
    #      이유를 단다
    hits = [VesselHit(mmsi=999000001, call_sign="QQTST1"), VesselHit(mmsi=999000005, call_sign="QQTST9")]
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: hits)
    monkeypatch.setitem(load_rules("vessel"), "max_candidates", 1)  # 후보 수가 상한을 넘어 되묻는다
    calls = []
    real = mof.plans_for
    monkeypatch.setattr(mof, "plans_for", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
    graph = graph_on(agent_deps)
    config, state = run(graph, "TESTVSL0004 어디쯤 왔어요?")
    assert state.interrupts and calls == []  # 찾을 때는 후보 수 상한 때문에 받지 않았다
    graph.invoke(Command(resume={"selected": 1}), config)
    assert calls == ["QQTST1"] and len(calls) <= load_rules("vessel")["pick_calls"]
    ship = graph.get_state(config).values["vessels"][0]
    assert (ship["status"], ship["reason"], ship["basis"], ship["cap"]) == (
        "user_choice",
        "papers_match",
        ["entry_date", "loading_port"],
        "partial",
    )
    broken = ToolError(code="timeout", message="시간 초과", retryable=True)
    monkeypatch.setattr(mof, "plans_for", lambda *a, **k: broken)
    graph2 = graph_on(agent_deps)
    config2, _ = run(graph2, "TESTVSL0004 어디쯤 왔어요?", "t2")
    graph2.invoke(Command(resume={"selected": 1}), config2)
    failed = graph2.get_state(config2).values["vessels"][0]
    assert (failed["status"], failed["reason"], failed["cap"]) == (
        "user_choice",
        "mrn_lookup_failed",
        "partial",
    )


def test_only_the_first_undecided_cargo_is_asked_and_the_cap_stops_lookups(agent_deps, monkeypatch):
    calls = []
    real = vessel.find_vessel
    monkeypatch.setattr(
        vessel, "find_vessel", lambda facts, **kw: calls.append(facts.number) or real(facts, **kw)
    )
    monkeypatch.setitem(load_rules("vessel"), "max_cargos", 2)
    graph = graph_on(agent_deps)
    _, state = run(graph, "TESTVSL0002 TESTVSL0001 TESTVSL0004")
    rows = [(v["token"], v["status"], v["reason"]) for v in state.values["vessels"]]
    assert calls == ["TESTVSL0002", "TESTVSL0001"]  # 상한 2: 셋째 화물은 찾지 않는다
    assert rows[0][1] == "ask" and rows[1][1] == "confirmed" and rows[2][1:] == ("unknown", "over_cap")


def test_second_undecided_cargo_is_not_asked_in_the_same_turn(agent_deps, monkeypatch):
    ship = {"mmsi": "999000001", "call_sign": None, "name": "", "check": "no_papers", "basis": []}
    undecided = {"status": "ask", "reason": "no_papers", "candidates": [ship]}
    monkeypatch.setattr(vessel, "find_vessel", lambda facts, **kw: dict(undecided))
    _, state = run(graph_on(agent_deps), "TESTVSL0001 TESTVSL0004")
    rows = [(v["status"], v["reason"]) for v in state.values["vessels"]]
    assert rows == [("ask", "no_papers"), ("unknown", "another_question")] and len(state.interrupts) == 1


def test_the_time_cap_leaves_the_rest_of_the_cargos_unlooked(agent_deps, monkeypatch):
    clock = iter([0.0, 40.0])  # 시작, 둘째 화물 전(40초 지남)
    monkeypatch.setattr(vessel, "_clock", lambda: next(clock))
    _, state = run(graph_on(agent_deps), "TESTVSL0001 TESTVSL0004")
    rows = [(v["status"], v["reason"]) for v in state.values["vessels"]]
    assert rows[0][0] == "confirmed" and rows[1] == ("unknown", "time_limit")


def test_a_confirmed_ship_is_not_looked_up_again_next_turn(agent_deps, monkeypatch):
    graph = graph_on(agent_deps)
    config, _ = run(graph, "TESTVSL0001 어디쯤 왔어요?")
    monkeypatch.setattr(vessel, "find_vessel", lambda facts, **kw: pytest.fail("확정한 배를 다시 찾았다"))
    graph.invoke({"text": "TESTVSL0001 지금은요?"}, config)
    assert graph.get_state(config).values["vessels"][0]["status"] == "confirmed"


def test_a_confirmed_ship_is_remembered_across_turns_that_do_not_name_the_cargo(agent_deps, monkeypatch):
    graph = graph_on(agent_deps)
    config, _ = run(graph, "TESTVSL0001 어디쯤 왔어요?")
    graph.invoke({"text": "고마워요"}, config)
    assert graph.get_state(config).values["verdicts"] == []  # 화물을 말하지 않은 차례에는 판정도 없다
    monkeypatch.setattr(vessel, "find_vessel", lambda facts, **kw: pytest.fail("확정한 배를 다시 찾았다"))
    graph.invoke({"text": "TESTVSL0001 지금은요?"}, config)
    values = graph.get_state(config).values
    assert values["vessels"][0]["status"] == "confirmed" and values["verdicts"][0]["grade"] == "fine"


def test_a_cargo_whose_lookup_fails_this_turn_gets_no_verdict_even_if_its_ship_was_confirmed(
    agent_deps, monkeypatch
):
    from marvia.graph import identify

    graph = graph_on(agent_deps)
    config, _ = run(graph, "TESTVSL0001 어디쯤 왔어요?")
    failed = ToolError(code="timeout", message="시간 초과", retryable=True)
    monkeypatch.setattr(identify, "lookup_cargo", lambda number: failed)
    graph.invoke({"text": "TESTVSL0001 지금은요?"}, config)
    values = graph.get_state(config).values
    assert values["cargos"][0]["facts"] is None and values["verdicts"] == []  # 화물 사실 없이 판정하지 않는다
    assert values["vessels"][0]["status"] == "confirmed"  # 확정한 배는 남는다


def test_the_cap_also_limits_position_and_schedule_lookups_for_ships_already_confirmed(
    agent_deps, monkeypatch
):
    graph = graph_on(agent_deps)
    config, _ = run(graph, "TESTVSL0001 어디쯤 왔어요?")
    graph.invoke({"text": "TESTVSL0004 어디쯤 왔어요?"}, config)
    asked = []
    real = shipfinder.vessel_position
    monkeypatch.setattr(shipfinder, "vessel_position", lambda mmsi: asked.append(mmsi) or real(mmsi))
    monkeypatch.setitem(load_rules("vessel"), "max_cargos", 1)
    graph.invoke({"text": "TESTVSL0001 TESTVSL0004 둘 다 어디쯤 왔어요?"}, config)
    values = graph.get_state(config).values
    assert asked == [999000001]  # 둘째 화물의 배는 확정돼 있어도 이번 차례에는 조회하지 않는다
    first, second = values["verdicts"]
    assert "over_cap" not in first["notes"] and first["grade"] == "fine"
    assert (
        "over_cap" in second["notes"] and second["grade"] is None
    )  # 조회하지 않은 화물에 등급을 내지 않는다
    assert [v["status"] for v in values["vessels"]] == ["confirmed", "confirmed"]  # 확정은 잊지 않는다


def test_one_cargo_makes_at_most_the_budgeted_number_of_requests_in_the_verdict_step(agent_deps, monkeypatch):
    # 위치 1 + 해수부 입항 실적 1 + 입항 예정 1 = rules/vessel.yaml verdict_calls
    counts = {"n": 0}
    for module, name in ((shipfinder, "fetch_position"), (mof, "control_arrivals"), (mof, "sailing_plans")):
        real = getattr(module, name)
        monkeypatch.setattr(
            module, name, lambda *a, _r=real, **k: counts.__setitem__("n", counts["n"] + 1) or _r(*a, **k)
        )
    graph = graph_on(agent_deps)
    config, _ = run(graph, "TESTVSL0001 어디쯤 왔어요?")
    before = counts["n"]
    graph.invoke({"text": "TESTVSL0001 지금은요?"}, config)  # 확정한 배: 찾기는 건너뛰고 판정의 요청만 남는다
    assert counts["n"] - before == load_rules("vessel")["verdict_calls"]


def test_ship_identifiers_and_ais_text_never_reach_the_model(agent_deps):
    prompts: list[str] = []
    graph = graph_on(agent_deps, prompts)
    config, state = run(graph, "TESTVSL0001 어디쯤 왔어요?")
    seen = "\n".join(prompts) + "\n".join(str(m.content) for m in state.values["messages"])
    assert prompts and "QQTST1" not in seen and "999000001" not in seen and "26TEST0001I" not in seen
    # 배 신호의 목적지 글(재생 값 "BUSAN, KR")은 공책 어디에도 없다
    assert "BUSAN, KR" not in json.dumps(state.values, ensure_ascii=False, default=str)


def test_a_pick_is_checked_against_every_search_hit_not_only_the_ones_the_card_shows(agent_deps, monkeypatch):
    # R-132. 같은 호출부호의 배가 셋인데 카드에는 둘만 보인다(max_choices). 보이는 하나를 골라도 잘린 쪽의
    #      같은 호출부호가
    #      확신 상한을 건다. 후보 목록과 같은 자리로 자르면 상한이 빠진다
    trio = [VesselHit(mmsi=999000020 + n, call_sign="QQTWN", ship_name="TEST TWIN") for n in range(3)]
    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: trio)
    monkeypatch.setitem(load_rules("vessel"), "max_candidates", 2)
    graph = graph_on(agent_deps)
    config, state = run(graph, "TESTVSL0007 어디쯤 왔어요?")
    question = state.values["vessel_question"]
    assert len(question["candidates"]) == 2 and len(question["hits"]) == 3
    graph.invoke(Command(resume={"selected": 1}), config)
    ship = graph.get_state(config).values["vessels"][0]
    assert (ship["status"], ship["reason"], ship["cap"]) == (
        "user_choice",
        "same_call_sign_many_mmsi",
        "partial",
    )


class Recorder(BaseCallbackHandler):
    """트레이서가 받는 값을 그대로 모은다: 노드마다의 입력과 출력, 따로따로."""

    def __init__(self):
        self.payloads: list = []

    def on_chain_start(self, serialized, inputs, **kwargs):
        self.payloads.append(inputs)

    def on_chain_end(self, outputs, **kwargs):
        self.payloads.append(outputs)


def test_trace_scrub_hides_ships_the_step_met_inside_each_payload(agent_deps):
    # [왜] Langfuse는 span마다 값을 따로 scrub에 넣는다. 한 덩어리로 넣으면 다른 값에서 찾은 배 이름
    #      으로 가려져 실제보다 잘 가려진 것처럼 보인다. 값을 모으는 일도 받은 값 안에서만 한다
    from marvia.trace import MASK, _ship_values, scrub

    recorder = Recorder()
    graph = graph_on(agent_deps)
    config = {"configurable": {"thread_id": "tr"}, "callbacks": [recorder]}
    graph.invoke({"text": "TESTVSL0002 어디쯤 왔어요?"}, config)  # 선택 카드에서 멈춘다
    assert graph.get_state(config).interrupts
    graph.invoke(Command(resume={"selected": 1}), config)  # 번호로 재개한다
    graph.invoke({"text": "TESTVSL0001 어디쯤 왔어요?"}, {**config, "configurable": {"thread_id": "tr2"}})
    raw = [json.dumps(p, ensure_ascii=False, default=str) for p in recorder.payloads]
    ids = ("QQTST1", "QQTST3", "999000001", "999000002", "999000003")
    assert any(s in text for text in raw for s in ids)  # 가리기 전에는 배의 값이 있다
    for payload in recorder.payloads:
        shown = json.dumps(scrub(payload), ensure_ascii=False, default=str)
        for secret in (*ids, "26TEST0001I", "26TEST0009I", "TESTVSL0001", "TESTVSL0002"):
            assert secret not in shown, (secret, shown[:200])
        # 배 이름은 배 값(vessels, candidates)이 함께 든 값에서 가린다. 세관이 준 화물 사실의 vessel_name은
        # 그 값 옆에 배 값이 없어 지금도 남는다(8b 전부터의 동작, 가림 규칙을 고치는 일은 이 계획 밖이다)
        names: set[str] = set()
        _ship_values(payload, names)
        if names:
            assert "TEST CARGO" not in json.dumps(scrub(payload), ensure_ascii=False, default=str)
    assert any(MASK in json.dumps(scrub(p), ensure_ascii=False, default=str) for p in recorder.payloads)


def test_scrub_is_stateless_and_only_hides_values_found_inside_what_it_is_given():
    from marvia.trace import MASK, scrub

    held = {
        "vessels": [{"token": "[BL1]", "name": "TEST CARGO A", "call_sign": "QQTST1", "mmsi": "999000001"}]
    }
    assert scrub(held)["vessels"][0]["name"] == MASK and scrub(held)["vessels"][0]["call_sign"] == MASK
    # 같은 글이라도 그 값 밖의 다른 값에서는 가리지 않는다(앞 호출의 기억이 남지 않는다)
    other = {"note": "TEST CARGO A QQTST1"}
    assert scrub(other) == other
    # 후보 목록과 되묻는 값 안의 값도 모은다. 너무 짧은 값(세 글자 미만)은 다른 글을 지우므로 모으지 않는다
    asked = {
        "vessel_question": {"candidates": [{"name": "TEST CARGO C", "call_sign": "QQ", "mmsi": "999000004"}]}
    }
    out = scrub({**asked, "text": "TEST CARGO C QQ"})
    assert out["text"] == f"{MASK} QQ"
    # 검색 결과 전체(hits)와 MRN 호출부호(mrn_call_sign)도 모은다. 질문 값은 그 둘을 함께 든다
    more = {
        "vessel_question": {"hits": [{"mmsi": "999000020", "call_sign": "QQTWN"}], "mrn_call_sign": "QQMRN"}
    }
    out = scrub({**more, "text": "999000020 QQTWN QQMRN"})
    assert out["text"] == f"{MASK} {MASK} {MASK}"
