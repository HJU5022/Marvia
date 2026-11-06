"""감시 목록 표와 다시 조회 (계획 3d). 로컬 DB의 marvia_test 스키마에서 돈다."""

from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet

from marvia.identify.models import CargoFacts, ToolError
from marvia.watch import (
    ENCRYPT_INFO,
    HASH_INFO,
    add_watch,
    derive_key,
    forget_user,
    number_hash,
    recheck,
    take_news,
    watch_keys,
)


def make_keys():
    """시험마다 새로 만든 키. 저장소에는 키를 두지 않는다."""
    return watch_keys(Fernet.generate_key().decode())


@pytest.fixture
def keys():
    return make_keys()


def cleared(number: str) -> CargoFacts:
    """수입신고 수리 단계로 바뀐 가짜 조회 결과."""
    return CargoFacts(number=number, stage="수입신고수리", fetched_at=datetime.now(UTC))


def test_recheck_records_a_stage_change_once(db, keys):
    add_watch(db, keys, "u1", "DEMO0001", "반입신고")
    add_watch(db, keys, "u1", "DEMO0001", "반입신고")  # 두 번 넣어도 한 줄
    assert db.execute("SELECT count(*) FROM watches").fetchone()[0] == 1
    assert recheck(db, keys, cleared) == 1
    assert recheck(db, keys, cleared) == 0  # 이미 기록한 단계는 다시 기록하지 않는다
    change = {"number": "DEMO0001", "old_stage": "반입신고", "new_stage": "수입신고수리"}
    assert take_news(db, keys, "u1") == [change]
    assert take_news(db, keys, "u1") == []  # 한 번 보인 변화는 다시 보이지 않는다


def test_news_is_kept_per_user(db, keys):
    add_watch(db, keys, "u1", "DEMO0001", "반입신고")
    recheck(db, keys, cleared)
    assert take_news(db, keys, "u2") == []  # 남의 감시 목록 변화는 보이지 않는다
    assert len(take_news(db, keys, "u1")) == 1


def test_failed_lookup_is_not_a_change(db, keys):
    add_watch(db, keys, "u1", "NOPE0001", "")
    missing = ToolError(code="not_found", message="재생 데이터에 없는 번호입니다", retryable=False)
    assert recheck(db, keys, lambda number: missing) == 0


def test_one_raising_lookup_does_not_stop_the_other_rows(db, keys):
    add_watch(db, keys, "u1", "DEMO0001", "반입신고")
    add_watch(db, keys, "u1", "DEMO0002", "반입신고")

    def lookup(number: str):
        if number == "DEMO0001":
            raise ValueError("깨진 재생 데이터")
        return cleared(number)

    assert recheck(db, keys, lookup) == 1  # 첫 줄은 건너뛰고 둘째 줄의 변화는 기록한다
    change = {"number": "DEMO0002", "old_stage": "반입신고", "new_stage": "수입신고수리"}
    assert take_news(db, keys, "u1") == [change]


def test_real_number_is_not_stored_in_plain_text(db, keys):
    add_watch(db, keys, "u1", "DEMO0001", "반입신고")
    row = db.execute("SELECT * FROM watches").fetchone()
    assert all("DEMO0001" not in str(value) for value in row)  # 어느 칸에도 실제 번호가 없다
    assert recheck(db, keys, cleared) == 1  # 그래도 복호화해 다시 조회한다
    assert take_news(db, keys, "u1")[0]["number"] == "DEMO0001"


def test_hash_depends_on_key():
    a, b = make_keys(), make_keys()
    assert number_hash(a, "DEMO0001") == number_hash(a, "DEMO0001")
    assert number_hash(a, "DEMO0001") != number_hash(b, "DEMO0001")


def test_watch_keys_are_two_separate_keys():
    secret = Fernet.generate_key().decode()
    assert derive_key(secret, ENCRYPT_INFO) != derive_key(
        secret, HASH_INFO
    )  # 한 비밀에서 용도별로 다른 키를 뽑는다
    assert watch_keys(secret).hash_key == derive_key(secret, HASH_INFO)
    with pytest.raises(ValueError):
        watch_keys("")


def test_row_with_another_key_is_skipped(db, keys):
    other = make_keys()
    add_watch(db, other, "u1", "DEMO0001", "반입신고")  # 다른 키로 암호화된 줄(키를 바꾼 뒤 남은 줄)
    add_watch(db, keys, "u1", "DEMO0002", "반입신고")
    assert recheck(db, keys, cleared) == 1  # 못 푸는 줄은 건너뛰고 나머지는 바뀐다
    change = {"number": "DEMO0002", "old_stage": "반입신고", "new_stage": "수입신고수리"}
    assert take_news(db, keys, "u1") == [change]


def test_forget_user_deletes_only_that_users_watches_and_events(db, keys):
    add_watch(db, keys, "u1", "DEMO0001", "반입신고")
    add_watch(db, keys, "u2", "DEMO0002", "반입신고")
    recheck(db, keys, cleared)  # 두 사용자 모두 변화가 기록된다
    assert forget_user(db, "u1") == 1  # 지운 감시 수
    assert take_news(db, keys, "u1") == []
    assert db.execute("SELECT count(*) FROM watch_events").fetchone()[0] == 1  # u1의 기록은 함께 사라졌다
    assert [n["number"] for n in take_news(db, keys, "u2")] == ["DEMO0002"]  # u2는 그대로
    assert forget_user(db, "nobody") == 0
