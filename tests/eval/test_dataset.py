"""평가셋 v1 시험 (done 3.1). 키와 DB 없이 돈다."""

from marvia.eval.dataset import SET_PATH, corpus_unit_ids, file_sha256, load_set
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
