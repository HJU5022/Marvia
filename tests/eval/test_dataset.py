"""평가셋 v1 시험 (done 3.1). 키와 DB 없이 돈다."""

from collections import Counter

import pytest
import yaml

from marvia.eval.dataset import SET_PATH, SET_V2_PATH, SET_V3_PATH, corpus_unit_ids, file_sha256, load_set
from marvia.identify.models import CargoFacts
from marvia.identify.parse import read_numbers
from marvia.tools.deadlines import import_deadlines, kst_date
from marvia.tools.rules import load_rules
from marvia.tools.unipass_replay import lookup_cargo


def test_set_has_the_design_split():
    items = load_set().items
    cfg = load_rules("eval")["set"]
    groups = {name: sum(item.group == name for item in items) for name in cfg["groups"]}
    assert groups == cfg["groups"]
    assert len({item.id for item in items}) == len(items)  # 문항 id가 겹치지 않는다
    assert sum(item.human for item in items) == cfg["human"]


def test_every_gold_unit_is_in_the_corpus():
    ids = corpus_unit_ids()
    for item in load_set().items:
        for gold in item.gold + item.also_ok:
            # [왜] 조·항까지만 적은 정답은 그 아래 호·목 단위가 하나라도 있어야 한다
            assert any(u == gold or u.startswith(gold + ".") for u in ids), (item.id, gold)


def test_cargo_numbers_use_fixture_prefixes_only():
    prefixes = tuple(load_rules("eval")["set"]["number_prefixes"])
    for item in load_set().items:
        numbers = [n.value for _, read in read_numbers(item.question) for n in read.numbers]
        numbers += [v for _, read in read_numbers(item.question) for alt in read.alternatives for v in alt]
        assert all(n.startswith(prefixes) for n in numbers), (item.id, numbers)


def test_expected_deadlines_are_what_the_code_computes():
    data = load_set()
    checked = 0
    for item in data.items:
        if not item.calc or not item.calc.deadlines:
            continue
        (number,) = [n.value for _, read in read_numbers(item.question) for n in read.numbers]
        facts = lookup_cargo(number)
        # [왜] 재생 데이터에 있는 번호여야 기한을 셀 수 있다
        assert isinstance(facts, CargoFacts) and facts.stage_at, (item.id, number)
        got = import_deadlines(facts.stage, kst_date(facts.stage_at.isoformat()), data.as_of)
        assert [(d.name, d.due) for d in got] == [(d.name, d.due) for d in item.calc.deadlines], item.id
        checked += 1
    assert checked == 3  # R12, R13, R14


def test_set_is_frozen_by_its_sha256():
    # [왜] 정답을 실행 결과를 보고 고치면 점수가 자를 바꿔 오른다. 고치려면 이유를 기록하고 해시를 다시 만든다
    #      (강의 IV 3주 04강: 점수가 바뀌면 "자도 바꿨나"부터 묻는다)
    recorded = (SET_PATH.parent / "set_v1.sha256").read_text(encoding="utf-8").split()[0]
    assert file_sha256(SET_PATH) == recorded


CHANGED = {"U05", "U06", "U07", "U08", "U09", "U10", "R09", "R10"}  # v2에서 채점 기준을 고친 문항
V2_ONLY = {"behaviour", "identify", "v2_change"}  # v1과 달라도 되는 칸


def test_v2_changes_only_the_scoring_standard_of_the_named_items():
    v1, v2 = load_set(SET_PATH), load_set(SET_V2_PATH)
    assert v2.version == "v2" and v2.as_of == v1.as_of
    assert [i.id for i in v2.items] == [i.id for i in v1.items]
    for old, new in zip(v1.items, v2.items, strict=True):
        # [왜] 질문·정답 근거·계산·궤적 같은 고정 칸은 그대로여야 v1과 v2 점수를 견줄 수 있다
        assert old.model_dump(exclude=V2_ONLY) == new.model_dump(exclude=V2_ONLY), old.id
        if old.id not in CHANGED:
            assert old.model_dump() == new.model_dump(), old.id
        else:
            assert new.v2_change.strip(), old.id  # 고친 이유를 적는다
    assert {i.id for i in v2.items if i.v2_change} == CHANGED
    assert not any(i.v2_change or i.identify for i in v1.items)


def test_v2_honest_not_found_replaces_unsupported_and_keeps_the_rest():
    by_id = {i.id: i for i in load_set(SET_V2_PATH).items}
    assert by_id["U05"].behaviour == ["not_found", "partial", "guide"]
    assert by_id["U06"].behaviour == ["not_found", "partial", "guide"]
    for id in ("U07", "U09", "U10"):
        assert by_id[id].behaviour == ["not_found", "partial"], id
    assert by_id["U08"].behaviour == ["not_found", "partial"]
    assert by_id["U08"].also_ok == ["L001556@20261002#제241조"]
    assert not any("unsupported" in i.behaviour for i in by_id.values() if i.id in CHANGED)


def test_v2_identify_gold_comes_from_the_replay_fixtures():
    by_id = {i.id: i for i in load_set(SET_V2_PATH).items}
    for id, want_cargos in (("R09", 2), ("R10", 1)):
        item = by_id[id]
        numbers = [n.value for _, read in read_numbers(item.question) for n in read.numbers]
        stages = sorted(lookup_cargo(n).stage for n in numbers)
        assert item.identify.cargos == want_cargos == len(numbers)
        assert sorted(item.identify.stages) == stages, id
    assert sum(bool(i.identify) for i in by_id.values()) == 2


def test_set_v2_is_frozen_by_its_sha256():
    # [왜] v2는 독립 대조(eval/gold_check_v2.md) 뒤 동결했다. 고치면 이유를 남기고 해시를 다시 만든다
    recorded = (SET_V2_PATH.parent / "set_v2.sha256").read_text(encoding="utf-8").split()[0]
    assert file_sha256(SET_V2_PATH) == recorded


def test_v1_file_hash_is_untouched_by_v2():
    recorded = (SET_PATH.parent / "set_v1.sha256").read_text(encoding="utf-8").split()[0]
    assert file_sha256(SET_PATH) == recorded
    assert file_sha256(SET_V2_PATH) != recorded


@pytest.mark.parametrize(
    ("name", "layers"),
    [
        ("rset_v1", {"a": 20, "b": 20, "c": 20}),
        ("rset_a2", {"a2": 20}),
        ("rset_a3", {"a3": 20}),
        ("rset_b2", {"b2": 20}),
        ("rset_a4", {"a4": 20}),
    ],
)
def test_retrieval_sets_are_frozen_by_their_sha256(name, layers):
    # [왜] 검색 전용 평가셋도 측정 뒤에 문항이나 정답을 고치면 앞뒤 값을 견줄 수 없다. 고치면 새 판을 만든다
    path = SET_PATH.parent / f"{name}.yaml"
    recorded = (SET_PATH.parent / f"{name}.sha256").read_text(encoding="utf-8").split()[0]
    assert file_sha256(path) == recorded
    items = yaml.safe_load(path.read_text(encoding="utf-8"))["items"]
    assert dict(Counter(i["layer"] for i in items)) == layers
    assert len({i["id"] for i in items}) == len(items) and all(i["query"] and i["gold"] for i in items)


# --- v3 (계획 7b): 기대 서브에이전트, R07 궤적 조건, R07·R08 정답 근거 ---

V3_CHANGED = {"R07", "R08", "R15"}  # v3에서 채점 칸(정답 근거, 인용해도 되는 단위, 궤적)을 고친 문항
V3_ONLY = {"route", "v3_change"}  # v2에 없던 칸
V3_SCORING = {"gold", "also_ok", "trajectory"}  # 고친 문항에서만 v2와 달라도 되는 칸
RULE = "L012500@20260930#"  # 수입식품안전관리 특별법 시행규칙


def test_v3_keeps_every_question_and_changes_scoring_only_in_the_named_items():
    v2, v3 = load_set(SET_V2_PATH), load_set(SET_V3_PATH)
    assert v3.version == "v3" and v3.as_of == v2.as_of
    assert [i.id for i in v3.items] == [i.id for i in v2.items]
    for old, new in zip(v2.items, v3.items, strict=True):
        assert old.question == new.question, old.id  # 질문 글은 한 글자도 바꾸지 않는다
        if old.id in V3_CHANGED:
            skip = V3_ONLY | V3_SCORING
            assert old.model_dump(exclude=skip) == new.model_dump(exclude=skip), old.id
            assert new.v3_change.strip(), old.id  # 고친 이유를 적는다
        else:
            assert old.model_dump(exclude=V3_ONLY) == new.model_dump(exclude=V3_ONLY), old.id
    assert {i.id for i in v3.items if i.v3_change} == V3_CHANGED
    assert not any(i.route or i.v3_change for i in v2.items)


def test_v3_gives_every_item_an_expected_route_of_known_subagents():
    names = set(load_rules("agent")["supervisor"]["subagents"])
    by_id = {i.id: i for i in load_set(SET_V3_PATH).items}
    for item in by_id.values():
        assert item.route is not None, item.id
        assert set(item.route.must) | set(item.route.may) <= names, item.id
        assert not set(item.route.must) & set(item.route.may), item.id
    # 도메인 밖 문항은 수퍼바이저가 혼자 거절한다. 서브에이전트를 들르면 틀린 길이다
    assert all(
        by_id[id].route.must == [] and by_id[id].route.may == [] for id in ("U01", "U02", "U03", "U04")
    )
    assert by_id["R13"].route.must == ["cargo", "law"] and by_id["R12"].route.may == ["law"]
    # [왜] 수퍼바이저는 식별 단계의 화물 줄을 첫 메시지로 받는다(brief 노드). 화물 상태만 묻는 문항은
    #      넘기지 않고 끝내도 맞는 길이다
    assert by_id["R09"].route.must == [] and by_id["R09"].route.may == ["cargo"]


def test_v3_moves_the_reimport_gold_to_the_annex_units_and_keeps_the_old_gold_as_also_ok():
    v2 = {i.id: i for i in load_set(SET_V2_PATH).items}
    v3 = {i.id: i for i in load_set(SET_V3_PATH).items}
    assert v3["R07"].gold == [RULE + "별표9.2호.가목.7)", RULE + "별표10.4호"]
    assert v3["R08"].gold == [RULE + "별표9.2호.가목.7)", RULE + "별표10.4호.다목"]
    for id in ("R07", "R08"):
        # 옛 정답은 인용해도 틀리지 않다. 그 뒤에 재수입 판정 도구가 단서로 이름을 대는 단위를 더했다
        kept = v2[id].also_ok + v2[id].gold
        assert v3[id].also_ok[: len(kept)] == kept, id
        assert RULE + "별표10.1호" in v3[id].also_ok and "A87721@20250901#제25조" in v3[id].also_ok, id
    # [왜] 5년을 어느 날부터 세는지는 가목에만 있다. 다른 품목의 목(나, 라~사)은 건고추의 근거가 아니다
    assert RULE + "별표10.4호.가목" in v3["R08"].also_ok and RULE + "별표10.4호.라목" not in v3["R08"].also_ok
    assert v3["R15"].gold == v2["R15"].gold and v3["R15"].trajectory == v2["R15"].trajectory
    assert v3["R15"].also_ok == v2["R15"].also_ok + ["A36852@20260224#제34조.1항.1호.라목"]
    # [왜] 수퍼바이저 길에는 조사 도구(research)가 없다. 법령 조사 서브에이전트로 넘기면 같은 조건을 채운다
    assert v3["R07"].trajectory.must == ["research|sub:law"]
    assert v3["R07"].trajectory.order == v2["R07"].trajectory.order
    assert v3["R08"].trajectory == v2["R08"].trajectory


def test_every_gold_unit_of_v3_is_in_the_corpus():
    ids = corpus_unit_ids()
    for item in load_set(SET_V3_PATH).items:
        for gold in item.gold + item.also_ok:
            assert any(u == gold or u.startswith(gold + ".") for u in ids), (item.id, gold)


def test_set_v3_is_frozen_by_its_sha256():
    # [왜] v3는 독립 대조(eval/gold_check_v3.md) 뒤 동결했다. 고치면 이유를 남기고 해시를 다시 만든다
    recorded = (SET_V3_PATH.parent / "set_v3.sha256").read_text(encoding="utf-8").split()[0]
    assert file_sha256(SET_V3_PATH) == recorded


def test_v1_and_v2_file_hashes_are_untouched_by_v3():
    for name, path in (("set_v1", SET_PATH), ("set_v2", SET_V2_PATH)):
        recorded = (path.parent / f"{name}.sha256").read_text(encoding="utf-8").split()[0]
        assert file_sha256(path) == recorded, name
