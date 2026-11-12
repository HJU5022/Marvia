"""평가셋 v1 시험 (done 3.1). 키와 DB 없이 돈다."""

from collections import Counter

import pytest
import yaml

from marvia.eval.dataset import SET_PATH, SET_V2_PATH, corpus_unit_ids, file_sha256, load_set
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
