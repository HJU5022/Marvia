"""감시 목록 표와 다시 조회 (계획 3d). 로컬 DB의 marvia_test 스키마에서 돈다."""

from datetime import UTC, datetime

from marvia.identify.models import CargoFacts, ToolError
from marvia.watch import add_watch, recheck, take_news


def cleared(number: str) -> CargoFacts:
    """수입신고 수리 단계로 바뀐 가짜 조회 결과."""
    return CargoFacts(number=number, stage="수입신고수리", fetched_at=datetime.now(UTC))


def test_recheck_records_a_stage_change_once(db):
    add_watch(db, "u1", "DEMO0001", "반입신고")
    add_watch(db, "u1", "DEMO0001", "반입신고")  # 두 번 넣어도 한 줄
    assert recheck(db, cleared) == 1
    assert recheck(db, cleared) == 0  # 이미 기록한 단계는 다시 기록하지 않는다
    change = {"number": "DEMO0001", "old_stage": "반입신고", "new_stage": "수입신고수리"}
    assert take_news(db, "u1") == [change]
    assert take_news(db, "u1") == []  # 한 번 보인 변화는 다시 보이지 않는다


def test_news_is_kept_per_user(db):
    add_watch(db, "u1", "DEMO0001", "반입신고")
    recheck(db, cleared)
    assert take_news(db, "u2") == []  # 남의 감시 목록 변화는 보이지 않는다
    assert len(take_news(db, "u1")) == 1


def test_failed_lookup_is_not_a_change(db):
    add_watch(db, "u1", "NOPE0001", "")
    missing = ToolError(code="not_found", message="재생 데이터에 없는 번호입니다", retryable=False)
    assert recheck(db, lambda number: missing) == 0
