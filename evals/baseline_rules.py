"""베이스라인 (a) 규칙만 (D7, SDD 5.12, PRD 8절).

LLM 대신 if문으로 판정한다. 평가 때 llm.judge·llm.pick_vessel 자리에 바꿔 끼운다. 서버 코드는 고치지 않는다.
같은 30건을 (b) 규칙+LLM과 비교해 LLM이 보탠 몫을 잰다. 특히 신호 상충 5건은 규칙만으로는 틀리게 설계돼 있다 (PRD 8절).

판정 규칙은 서비스와 같은 판정 표 코드(backend/app/services/judge/verdict.py)를 쓴다. 표의 재료는 skills/cargo-verdict/rules.md다
(SDD 5.12의 옛 매핑 대신 Skill 표를 따랐고, D7에서 표가 코드와 rules.md로 옮겨졌다.
LLM도 같은 표 등급을 받으므로 "같은 규칙, LLM 유무"의 비교가 된다).
"""
from backend.app.services import llm
from backend.app.services.judge.verdict import table_reasons, table_verdict

MODEL = "baseline/rules"  # 결과·트레이스에서 LLM 판정과 구분하는 이름

# 판정 표는 서비스와 같은 코드를 쓴다 (backend/app/services/judge/verdict.py, D7). 테스트가 이 이름으로 부른다
verdict_for = table_verdict


def judge(signal_set, customs, margin, **kwargs) -> llm.LLMAnswer:
    """llm.judge와 같은 모양으로 돌려준다. 라우터는 이 값을 LLM 판정처럼 받아 같은 검증(validate)을 거친다.

    reasons에는 켜진 신호를 그대로 넣는다 (V2: watch·act면 켜진 규칙 1개 이상, 이름은 신호 id).
    answer에는 숫자를 넣지 않는다 (V7: 답 속 숫자는 근거 카드에 있어야 한다).
    회색 지대에서도 올리지 않고 표 등급 그대로 낸다. "규칙만"이 LLM 판단 없이 어디까지 맞는지 재는 기준선이라서다.
    """
    output = llm.JudgeOutput(
        verdict=table_verdict(signal_set, margin),
        reasons=table_reasons(signal_set, margin),
        conflicts=[],
        actions=[],
        answer="규칙만으로 판정했습니다.",
        customs=None,
        table_disagree=None,
    )
    return llm.LLMAnswer(output=output, llm=llm.LLMResult(content="", model=MODEL), prompt_version="baseline")


def pick_vessel(candidates, customs, voyage_no=None, forwarder_eta=None, **kwargs) -> llm.LLMAnswer:
    """llm.pick_vessel과 같은 모양. 되묻지 않고 맨 앞 후보를 확정한다 (PRD 8절 "식별은 유사도 최고 후보").

    후보는 도구가 이미 선명 유사도 높은 순(같으면 최근 신호 순)으로 정렬해 준다 (mcp_server/tools/vessel_candidates.py).
    confidence를 high로 줘야 라우터가 되묻지 않고 확정한다. 동명 선박 문항에서 규칙만 쓰면 틀리는 게 정상이다.
    """
    output = llm.PickOutput(choice=candidates[0].mmsi, confidence="high", reasons_per_candidate=[])
    return llm.LLMAnswer(output=output, llm=llm.LLMResult(content="", model=MODEL), prompt_version="baseline")
