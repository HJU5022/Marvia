"""V11: 통관이 잘되는지·늦어질지 평가하지 않는다 (services/judge/validate.py).

Skill에 적어도 LLM이 "통관 절차도 원활하게 진행 중입니다"를 계속 써서 코드가 걸러 다시 쓰게 한다.
낱말은 customs-stages/rules.md customs_subject_words · customs_assessment_words.
"""
from datetime import datetime, timezone

from backend.app.schemas.agent import AgentResponse
from backend.app.services.judge.validate import check

NOW = datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)
EVIDENCE = [{"source": "rule", "field": "days_margin", "value": "4", "fetched_at": NOW}]
CUSTOMS = {"stage_code": "", "stage_name": "반입신고", "plain_explanation": "화물이 터미널·보세창고에 들어갔습니다.",
           "next_stage": "수입신고", "needs_broker": False, "history": []}


def _v9(**over) -> bool:
    base = dict(status="ok", verdict="fine", vessel_match="confirmed", days_margin=4, decided_by="rule",
                vessel=None, position=None, eta=None, customs=None, berth=None, evidence=EVIDENCE,
                answer="판매 예정일보다 4일 일찍 도착합니다.", trace_id="t")
    return any(v.rule == "V11" for v in check(AgentResponse(**{**base, **over})))


def test_customs_assessment_in_answer_is_violation():
    # 실제로 나온 문장들 (평가 N01 · B06 · B10)
    assert _v9(answer="판매 예정일보다 4일 일찍 도착합니다. 통관 절차도 원활하게 진행 중입니다.")
    assert _v9(answer="세관 심사도 원활하게 진행되고 있습니다.")
    assert _v9(answer="통관이 지연될 수 있으므로 즉시 조치해야 합니다.")
    assert _v9(answer="선박과 통관 모두 문제없이 진행되고 있습니다.")


def test_customs_assessment_in_actions_or_explanation_is_violation():
    assert _v9(actions=["통관이 순조롭게 진행 중이니 기다리세요."])
    assert _v9(customs={**CUSTOMS, "plain_explanation": "화물이 들어갔습니다. 통관이 순조롭게 진행되고 있습니다."})


def test_plain_facts_are_not_violation():
    assert not _v9()
    assert not _v9(customs=CUSTOMS)
    # 통관 낱말이 없는 지연 문장: 정박 대기 설명에 정상적으로 쓰인다
    assert not _v9(answer="배가 부산 앞에서 대기 중이라 입항이 지연되고 있습니다.")
    # 통관 낱말은 있지만 평가가 아닌 사실
    assert not _v9(answer="통관은 수입신고수리 단계로, 통관이 끝났습니다.")
    # 평가 낱말은 있지만 통관 이야기가 아닌 문장
    assert not _v9(answer="모든 신호가 정상이고 선박 운항도 원활합니다.")


# V11 보강: 수입신고수리 전 단계에서 통관이 끝났다고 말한 문장이 통과했다
MANIFEST = {**CUSTOMS, "stage_name": "입항적재화물목록 심사완료", "plain_explanation": "세관이 목록을 확인했습니다.",
            "next_stage": "하선신고 수리"}


def test_customs_done_claim_before_clearance_is_violation():
    # 점검에서 V11을 통과한 실제 문장들 (단계: 입항적재화물목록 심사완료)
    assert _v9(customs=MANIFEST, answer="현재 통관이 완료된 상태이며 배는 부산으로 오고 있습니다.")
    assert _v9(customs=MANIFEST, answer="통관이 완료되었고 하선만 남았습니다.")
    assert _v9(customs=MANIFEST, answer="세관 확인 결과 문제가 없습니다.")
    assert _v9(customs=MANIFEST, actions=["세관 절차는 끝났으니 운송사에 연락하세요."])


def test_stage_name_with_done_word_is_not_violation():
    # 단계 이름 속 "완료"는 걸리지 않는다. 바른 해설 문장 (marvia-judge 프롬프트 예시와 같은 모양)
    assert not _v9(customs=MANIFEST, answer="입항적재화물목록 심사완료 단계로, 세관이 목록을 확인했다는 뜻입니다.")
    assert not _v9(customs=MANIFEST, answer="입항적재화물목록 심사 완료 단계로, 세관이 목록을 확인했다는 뜻입니다.")
    # 앞으로의 일을 말하는 조건 문장
    assert not _v9(customs=MANIFEST, answer="세관 심사가 완료되면 하선신고 수리 단계로 넘어갑니다.")


def test_customs_done_claim_after_clearance_is_allowed():
    cleared = {**CUSTOMS, "stage_name": "수입신고수리", "plain_explanation": "통관이 끝났습니다.", "next_stage": "반출신고"}
    assert not _v9(customs=cleared, answer="수입신고수리 단계로, 통관이 완료되었습니다.")
