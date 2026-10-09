"""관세사 필요 여부(needs_broker)를 코드가 정한다 (강사 피드백: 결정마다 권한자 하나).

- 정상 단계 목록은 customs-stages/rules.md customs_stages에서 읽는다 (코드에 따로 적지 않는다)
- 검사·보류 같은 단계, 목록에 없는 단계는 true. 목록의 todo에 관세사가 나와도 정상 단계는 false
- LLM 출력에는 needs_broker 칸이 없고, 입력으로 코드 값을 받는다
"""
import json
from datetime import datetime, timezone

from backend.app.schemas.customs import CustomsRecord
from backend.app.schemas.signals import SignalSet
from backend.app.services import llm
from backend.app.services.judge.rules import customs_stage_names, stage_key
from backend.app.services.judge.signals import needs_broker


def test_stage_names_come_from_rules_yaml():
    names = customs_stage_names()
    # customs-stages/rules.md customs_stages의 10개 단계 (SKILL.md 표에서 YAML 목록으로 옮김)
    assert len(names) == 10
    assert stage_key("입항적재화물목록 제출") in names
    assert stage_key("반출신고") in names
    assert "단계" not in names


def test_normal_stage_is_false_even_if_todo_mentions_broker():
    # todo에 "관세사에게 ..."가 있는 정상 단계
    assert needs_broker("입항보고 수리") is False
    assert needs_broker("반입신고") is False


def test_spacing_difference_is_same_stage():
    assert needs_broker("수입신고 수리") is False
    assert needs_broker("수입신고수리") is False


def test_hold_words_are_true():
    assert needs_broker("검사대상 지정") is True
    assert needs_broker("통관보류") is True


def test_unknown_stage_is_true():
    assert needs_broker("처음 보는 단계") is True


def test_llm_output_has_no_needs_broker_and_input_has_code_value():
    customs_schema = llm.JUDGE_SCHEMA["properties"]["customs"]["anyOf"][0]
    assert "needs_broker" not in customs_schema["properties"]
    assert "needs_broker" not in customs_schema["required"]

    now = datetime.now(timezone.utc)
    customs = CustomsRecord(bl_masked="TEST****0001", stage_name="통관보류", fetched_at=now)
    signal_set = SignalSet(signals=[], freshness="fresh", distance_nm=None, calc_eta=None,
                           eta_gap_hours=None, computed_at=now)
    data = json.loads(llm._judge_input(signal_set, customs, None))
    assert data["needs_broker"] is True
    # 통관 정보가 없으면 null
    assert json.loads(llm._judge_input(signal_set, None, None))["needs_broker"] is None
