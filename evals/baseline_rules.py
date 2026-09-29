"""베이스라인 (a) 규칙만 (D7, SDD 5.12, PRD 8절).

LLM 대신 if문으로 판정한다. 평가 때 llm.judge·llm.pick_vessel 자리에 바꿔 끼운다. 서버 코드는 고치지 않는다.
같은 30건을 (b) 규칙+LLM과 비교해 LLM이 보탠 몫을 잰다. 특히 신호 상충 5건은 규칙만으로는 틀리게 설계돼 있다 (PRD 8절).

판정 규칙은 skills/ais-reliability/SKILL.md 판정 표를 그대로 옮겼다 (09-28 결정. SDD 5.12의 옛 매핑이 아니라
09-27에 바뀐 Skill 표를 따른다. LLM도 같은 표를 보고 판정하므로 "같은 규칙, LLM 유무"의 비교가 된다).
"""
from backend.app.schemas.agent import Reason
from backend.app.services import llm
from backend.app.services.rules import rule
from backend.app.services.signals import DEST_BROKEN, DEST_EMPTY

# SKILL.md 판정 표: 이 셋 중 하나라도 triggered면 act
ACT_SIGNALS = {"anchor_wait", "customs_hold", "sales_date_exceeded"}
MODEL = "baseline/rules"  # 결과·트레이스에서 LLM 판정과 구분하는 이름


def verdict_for(signal_set, margin: int | None) -> str:
    """SKILL.md 판정 표.
    act: ACT_SIGNALS 중 하나라도 켜짐, 또는 다른 신호가 켜졌는데 여유 일수가 margin_act_days(rules.md) 미만
    watch: ACT_SIGNALS는 꺼져 있고 다른 신호가 하나라도 켜짐
    fine: 켜진 신호 없음. unknown(판단 불가)은 켜진 것으로 세지 않는다
    예외: 입력 오류로 설명되는 신호(깨진·빈 목적지, 항해상태 불일치)는 켜져도 세지 않는다 (SKILL.md 판정 표 예외, 09-29)
    """
    on = {s.id for s in signal_set.signals if s.state == "triggered" and not _input_error(s)}
    if not on:
        return "fine"
    if on & ACT_SIGNALS:
        return "act"
    # 여유 일수를 모르면(판매일·도착 예정 없음) 이 조건으로는 act를 내지 않는다
    if margin is not None and margin < rule("margin_act_days"):
        return "act"
    return "watch"


def judge(signal_set, customs, margin, **kwargs) -> llm.LLMAnswer:
    """llm.judge와 같은 모양으로 돌려준다. 라우터는 이 값을 LLM 판정처럼 받아 같은 검증(validate)을 거친다.

    reasons에는 켜진 신호를 그대로 넣는다 (V2: watch·act면 켜진 규칙 1개 이상, 이름은 신호 id).
    answer에는 숫자를 넣지 않는다 (V7: 답 속 숫자는 근거 카드에 있어야 한다).
    """
    output = llm.JudgeOutput(
        verdict=verdict_for(signal_set, margin),
        reasons=[Reason(rule=s.id, value=s.value, triggered=True)
                 for s in signal_set.signals if s.state == "triggered"],
        conflicts=[],
        actions=[],
        answer="규칙만으로 판정했습니다.",
        customs=None,
    )
    return llm.LLMAnswer(output=output, llm=llm.LLMResult(content="", model=MODEL), prompt_version="baseline")


def pick_vessel(candidates, customs, voyage_no=None, forwarder_eta=None, **kwargs) -> llm.LLMAnswer:
    """llm.pick_vessel과 같은 모양. 되묻지 않고 맨 앞 후보를 확정한다 (PRD 8절 "식별은 유사도 최고 후보").

    후보는 도구가 이미 선명 유사도 높은 순(같으면 최근 신호 순)으로 정렬해 준다 (mcp_server/tools/vessel_candidates.py).
    confidence를 high로 줘야 라우터가 되묻지 않고 확정한다. 동명 선박 문항에서 규칙만 쓰면 틀리는 게 정상이다.
    """
    output = llm.PickOutput(choice=candidates[0].mmsi, confidence="high", reasons_per_candidate=[])
    return llm.LLMAnswer(output=output, llm=llm.LLMResult(content="", model=MODEL), prompt_version="baseline")


def _input_error(signal) -> bool:
    """SKILL.md 판정 표 예외. 배의 실제 상태가 아니라 AIS 입력 오류일 수 있는 신호."""
    if signal.id == "navstat_mismatch":
        return True  # 항해상태는 손으로 넣는 값. 실제 상태는 속도·위치 신호(anchor_wait 등)가 따로 본다
    return signal.id == "dest_changed" and signal.value in (DEST_BROKEN, DEST_EMPTY)
