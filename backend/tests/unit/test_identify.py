"""services/judge/identify.py 테스트. 해수부는 가짜 클라이언트로 바꿔 끼워 키 없이 돈다."""
from datetime import date, datetime, timezone

from backend.app.clients.mof import MofError
from backend.app.schemas.customs import CustomsRecord
from backend.app.services.judge import identify

NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)


def _customs(mrn="26TEST0011I", entry=datetime(2026, 9, 24)) -> CustomsRecord:
    return CustomsRecord(ship_name="TEST STAR", mrn=mrn, entry_date=entry, bl_masked="TEST****0001", fetched_at=NOW)


class FakeMof:
    """find_plan_by_mrn만 흉내 낸다. 받은 기간을 기록해 두고, 정해 둔 결과를 돌려준다."""

    def __init__(self, result=None, error: MofError | None = None):
        self.result, self.error, self.calls = result, error, []

    def find_plan_by_mrn(self, mrn, start, end):
        self.calls.append((mrn, start, end))
        if self.error:
            raise self.error
        return self.result


class Plan:
    call_sign = "TEST11"


def test_call_sign_found_by_mrn_around_entry_date():
    mof = FakeMof(result=Plan())
    assert identify.call_sign_from_mrn(_customs(), mof) == "TEST11"
    # UNI-PASS 입항(예정)일 앞뒤 하루만 훑는다 (실제 B/L 1건이 이 범위에서 찾아짐)
    assert mof.calls == [("26TEST0011I", date(2026, 9, 23), date(2026, 9, 25))]


def test_no_plan_returns_none():
    assert identify.call_sign_from_mrn(_customs(), FakeMof(result=None)) is None


def test_mof_failure_returns_none_not_error():
    """해수부가 실패해도 식별을 막지 않는다. None이면 라우터가 이름 검색으로 간다."""
    mof = FakeMof(error=MofError("timeout", "테스트"))
    assert identify.call_sign_from_mrn(_customs(), mof) is None


def test_missing_mrn_or_entry_date_skips_lookup():
    mof = FakeMof(result=Plan())
    assert identify.call_sign_from_mrn(_customs(mrn=None), mof) is None
    assert identify.call_sign_from_mrn(_customs(entry=None), mof) is None
    assert mof.calls == []  # 찾을 근거가 없으면 해수부를 부르지 않는다


def _failures(caplog) -> list[tuple[str, str]]:
    return [(r.stage, r.error) for r in caplog.records if r.name == "marvia.failure"]


def test_mrn_not_found_and_mof_error_are_logged_apart(caplog):
    """입항 신고 전이라 없는 것(not_found)과 해수부 오류는 다르다. 둘 다 이름 검색으로 넘어가지만 이유를 남긴다."""
    with caplog.at_level("WARNING", logger="marvia.failure"):
        identify.call_sign_from_mrn(_customs(), FakeMof(result=None))
        identify.call_sign_from_mrn(_customs(), FakeMof(error=MofError("timeout", "테스트")))
    assert _failures(caplog) == [("identify_mrn", "not_found"), ("identify_mrn", "timeout")]
