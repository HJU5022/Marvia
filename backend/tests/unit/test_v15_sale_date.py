"""V15: 판매 예정일 문장 검사 (services/judge/validate.py).

판정 LLM이 days_margin 음수를 "판매 예정일이 지난 상태입니다"로 옮기고(늦게 도착한다는 뜻이지 날짜가 지났다는 뜻이 아니다),
판매 예정일을 받지 않았는데 "예정보다 빠른 도착"이라고 썼다. 낱말은 cargo-verdict/rules.md sale_date_words 등. 키 없이 돈다.
"""
from datetime import datetime, timezone

from backend.app.schemas.agent import AgentResponse
from backend.app.services.judge.validate import check

NOW = datetime(2026, 10, 6, 3, 0, tzinfo=timezone.utc)
WITH_DATE = [{"source": "rule", "field": "days_margin", "value": "-2", "fetched_at": NOW},
             {"source": "rule", "field": "sale_due_date", "value": "2026-10-08", "fetched_at": NOW}]
NO_DATE = [{"source": "rule", "field": "trusted_eta", "value": "2026-10-10T09:00:00+09:00", "fetched_at": NOW}]


def _v15(evidence, **over) -> list[str]:
    base = dict(status="ok", verdict="act", vessel_match="confirmed", days_margin=-2, decided_by="rule",
                vessel=None, position=None, eta=None, customs=None, berth=None, evidence=evidence,
                answer="판매 예정일보다 2일 늦게 도착합니다.", trace_id="t", reasons=[{"rule": "sales_date_exceeded", "value": "-2", "triggered": True}])
    return [v.detail for v in check(AgentResponse(**{**base, **over})) if v.rule == "V15"]


def test_sale_date_passed_is_violation():
    assert _v15(WITH_DATE, answer="판매 예정일이 지난 상태입니다. 판매 예정일보다 2일 늦게 도착합니다.")
    assert _v15(WITH_DATE, answer="판매 예정일이 이미 지났으므로 일정을 다시 잡으세요.")
    assert _v15(WITH_DATE, actions=["판매 예정일이 지났으니 거래처에 알리세요."])


def test_late_arrival_sentence_passes():
    assert not _v15(WITH_DATE)
    assert not _v15(WITH_DATE, answer="판매 예정일보다 2일 늦게 도착할 것으로 보여 판매 일정을 조정해야 합니다.")


def test_no_sale_date_comparison_is_violation():
    assert _v15(NO_DATE, days_margin=None, verdict="fine", reasons=[], answer="예정보다 빠른 도착이 예상됩니다.")
    assert _v15(NO_DATE, days_margin=None, verdict="fine", reasons=[], answer="판매 예정일보다 일찍 도착합니다.")


def test_no_sale_date_plain_sentences_pass():
    assert not _v15(NO_DATE, days_margin=None, verdict="fine", reasons=[], answer="배는 10월 10일 부산 도착 예정입니다.")
    # 판매 예정일을 달라는 안내는 비교가 아니다
    assert not _v15(NO_DATE, days_margin=None, verdict="fine", reasons=[],
                    answer="판매 예정일을 알려 주시면 여유 일수를 계산해 드립니다.")
