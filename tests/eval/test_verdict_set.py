"""판정 평가 문항 시험 (계획 8a). LLM 없이, 키 없이, DB 없이 돈다."""

from collections import Counter

from marvia.eval.dataset import file_sha256
from marvia.eval.verdict_set import (
    SET_PATH,
    load_verdict_set,
    match_mismatches,
    mismatches,
    run_item,
    summarize,
)
from marvia.tools.rules import load_rules

SET = load_verdict_set()
LAYERS = {"ported": 20, "port": 5, "conflict": 14, "failure": 6, "nodata": 4, "stage": 4, "edge": 32}


def test_set_is_frozen_and_has_every_layer():
    recorded = (SET_PATH.parent / "verdict_set_v1.sha256").read_text(encoding="utf-8").split()[0]
    assert file_sha256(SET_PATH) == recorded
    assert Counter(item.layer for item in SET.items) == LAYERS
    assert len(SET.matches) == 12
    ids = [item.id for item in SET.items] + [m.id for m in SET.matches]
    assert len(ids) == len(set(ids))


def test_every_item_gets_the_expected_signals_and_verdict():
    wrong = {item.id: found for item in SET.items if (found := mismatches(item))}
    assert wrong == {}


def test_every_vessel_match_item_gets_the_expected_result():
    wrong = {item.id: found for item in SET.matches if (found := match_mismatches(item))}
    assert wrong == {}


def test_ported_items_give_the_same_six_signals_as_v1():
    # [왜] 옮긴 문항의 v1 칸은 v1 신호 코드가 같은 입력에 낸 값이다. 다르면 옮기다 판단이 바뀐 것이다
    ids = load_rules("verdict")["signal_ids"]
    for item in SET.items:
        if item.layer != "ported":
            assert item.v1 is None
            continue
        assert item.v1 is not None and sorted(item.v1.signals) == sorted(ids)
        assert item.expect.signals == item.v1.signals, item.id


def test_grade_differs_from_v1_only_where_the_set_says_why():
    # [왜] v2는 등급이 넷이고 판매일 신호가 없다(설계 결정 13). v1 표와 다른 문항에는 이유가 적혀 있어야 한다
    same = {"fine": "fine", "watch": "watch", "act": "act"}
    for item in (i for i in SET.items if i.v1 is not None):
        assert item.v1 is not None
        if item.v1.differs:
            continue
        assert item.expect.grade == same[item.v1.table_verdict], item.id
    assert sorted(i.v1.id for i in SET.items if i.v1 is not None and i.v1.differs) == [
        "B08",
        "B09",
        "B13",
        "F04",
    ]


def test_no_item_borrows_busan_values_for_another_port():
    for item in SET.items:
        code = (item.cargo or {}).get("port_code")
        if code != "KRPUS":
            assert item.expect.signals["anchor_wait"] == "unknown", item.id
            assert item.expect.confidence != "sure", item.id


def test_less_data_never_gives_a_better_grade_in_any_item():
    # [왜] 11-13 결정. 도착 시각을 알 출처가 없으면 "순항"도 "정시"도 아니다. 순항은 믿을 ETA가 있어야 나온다
    for item in SET.items:
        want = item.expect
        if want.eta_source is None:
            assert want.grade != "fine" and want.schedule != "on_time", item.id
            assert "no_eta" in want.notes, item.id
        if want.grade is None:
            assert want.confidence == "unknown", item.id
    assert sum(1 for item in SET.items if item.expect.grade is None) >= 3


def test_edge_layer_has_cases_around_every_threshold():
    # [왜] 기준값 한 칸(초과와 이상, 이하와 미만)을 틀려도 통과하는 문항 묶음은 기준을 지키지 못한다
    edges = [item for item in SET.items if item.layer == "edge"]
    for word in (
        "위치 끊김 6시간",
        "ETA 어긋남 12시간",
        "멈춤 속도 0.5노트",
        "정지 24시간",
        "정지 반경 30해리",
    ):
        assert sum(word in item.why for item in edges) >= 2, word
    for word in ("2.0노트 초과", "0.3노트 미만", "여유 2일 미만", "여유 0일 미만", "지연 1일 이상"):
        assert sum(word in item.why for item in edges) >= 2, word


def test_summary_counts_every_item_once():
    done = summarize(SET)
    assert done["items"] == {"n": 85, "passed": 85} and done["matches"] == {"n": 12, "passed": 12}
    assert {name: row["n"] for name, row in done["layers"].items()} == LAYERS


def test_free_text_from_the_ship_signal_never_reaches_a_verdict():
    # [왜] 배 신호의 목적지 글은 선원이 손으로 넣는 자유 글이다. v1 평가 문항 F03은 거기에 지시문을 넣었다.
    #      판정 결과(신호 값, 이유, 등급)는 나중에 모델과 화면으로 간다. 그 어디에도 원문이 없어야 한다
    seen = 0
    for item in SET.items:
        raw = (item.position or {}).get("dest")
        if not raw:
            continue
        dumped = run_item(item).model_dump_json()
        for word in {w for w in raw.replace(",", " ").replace(".", " ").split() if len(w) >= 4}:
            assert word not in dumped, (item.id, word)
        seen += 1
    assert seen >= 60
    injected = next(item for item in SET.items if item.id == "V-F03")
    assert "무시" in (injected.position or {})["dest"] and "무시" not in run_item(injected).model_dump_json()


def test_a_ship_eta_counts_only_when_the_destination_is_this_port():
    # [왜] 목적지가 깨졌거나 비었는데 배 신호 ETA만 있으면 그 ETA로 순항과 여유 일수가 나왔다.
    #      그 ETA가 이 항만 도착 시각이라고 말해 주는 것이 없다 (11-13 덧붙임 2)
    by_id = {item.id: item for item in SET.items}
    for name in ("V-C11", "V-C12"):  # 목적지 깨짐 + 배 신호 ETA만 (판매 예정일 앞 / 뒤)
        want = by_id[name].expect
        assert (want.grade, want.schedule, want.eta_source, want.margin_days) == (None, None, None, None)
        assert want.confidence == "unknown" and want.notes == ["no_eta"] and want.dest_value == "broken"
    other = by_id["V-C13"].expect  # 목적지가 다른 항구: 경계는 그대로 내고 여유 일수는 세지 않는다
    assert (other.grade, other.eta_source, other.margin_days) == ("alert", None, None)
    same = by_id["V-C14"].expect  # 목적지가 양륙항: 지금까지처럼 센다
    assert (same.grade, same.eta_source, same.margin_days) == ("fine", "ais_eta", 4)
    assert not [name for name in ("V-C11", "V-C12", "V-C13", "V-C14") if mismatches(by_id[name])]
