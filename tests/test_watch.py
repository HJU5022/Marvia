"""감시 목록 표와 다시 조회 (계획 3d). 로컬 DB의 시험용 스키마(실행마다 새 marvia_test_*)에서 돈다."""

import base64
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet, InvalidToken

from marvia.identify.models import CargoFacts, ToolError
from marvia.watch import (
    ENCRYPT_INFO,
    HASH_INFO,
    ack_news,
    add_watch,
    derive_key,
    forget_user,
    list_watched,
    number_hash,
    recheck,
    remove_watch,
    take_news,
    watch_keys,
)


def make_keys():
    """시험마다 새로 만든 키. 저장소에는 키를 두지 않는다."""
    return watch_keys(Fernet.generate_key().decode())


@pytest.fixture
def keys():
    return make_keys()


def changes(news: list[dict]) -> list[dict]:
    """꺼낸 변화에서 기록 id를 뺀 모양 (id는 DB가 매겨 시험마다 다르다)."""
    return [{k: v for k, v in n.items() if k != "id"} for n in news]


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
    news = take_news(db, keys, "u1")
    assert changes(news) == [change]
    # [왜] 꺼내기만 하고 답에 보이지 못한 차례(승인 대기 중 새 질문 등)가 있다. 그때 변화를 잃지 않는다
    assert changes(take_news(db, keys, "u1")) == [change]
    ack_news(db, "u1", [n["id"] for n in news])
    assert take_news(db, keys, "u1") == []  # 답에 보인 뒤에는 다시 보이지 않는다


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
    assert changes(take_news(db, keys, "u1")) == [change]


def test_real_number_is_not_stored_in_plain_text(db, keys):
    add_watch(db, keys, "u1", "DEMO0001", "반입신고")
    row = db.execute("SELECT * FROM watches").fetchone()
    assert all("DEMO0001" not in str(value) for value in row)  # 어느 칸에도 실제 번호가 없다
    assert recheck(db, keys, cleared) == 1  # 그래도 복호화해 다시 조회한다
    assert take_news(db, keys, "u1")[0]["number"] == "DEMO0001"


def test_ack_marks_only_that_users_events_as_seen(db, keys):
    add_watch(db, keys, "u1", "DEMO0001", "반입신고")
    add_watch(db, keys, "u2", "DEMO0001", "반입신고")
    recheck(db, keys, cleared)
    u1_ids = [n["id"] for n in take_news(db, keys, "u1")]
    u2_ids = [n["id"] for n in take_news(db, keys, "u2")]
    ack_news(db, "u2", u1_ids)  # 남의 기록 id로는 표시하지 못한다
    assert [n["id"] for n in take_news(db, keys, "u1")] == u1_ids
    ack_news(db, "u1", u1_ids)
    assert take_news(db, keys, "u1") == []
    assert [n["id"] for n in take_news(db, keys, "u2")] == u2_ids  # u2의 변화는 그대로 남는다


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
    with pytest.raises(ValueError, match="올바른") as err:
        watch_keys("short-typed-secret")  # 사람이 친 짧은 비밀은 받지 않는다
    assert "short-typed-secret" not in str(err.value)  # 오류 글에 비밀이 없다


def test_row_with_another_key_is_skipped(db, keys):
    other = make_keys()
    add_watch(db, other, "u1", "DEMO0001", "반입신고")  # 다른 키로 암호화된 줄(키를 바꾼 뒤 남은 줄)
    add_watch(db, keys, "u1", "DEMO0002", "반입신고")
    assert recheck(db, keys, cleared) == 1  # 못 푸는 줄은 건너뛰고 나머지는 바뀐다
    change = {"number": "DEMO0002", "old_stage": "반입신고", "new_stage": "수입신고수리"}
    assert changes(take_news(db, keys, "u1")) == [change]


def test_forget_user_deletes_only_that_users_watches_and_events(db, keys):
    add_watch(db, keys, "u1", "DEMO0001", "반입신고")
    add_watch(db, keys, "u2", "DEMO0001", "반입신고")  # 같은 번호라도 사용자마다 따로 한 줄이다
    recheck(db, keys, cleared)  # 두 사용자 모두 변화가 기록된다
    assert db.execute("SELECT count(*) FROM watches").fetchone()[0] == 2
    assert forget_user(db, "u1") == 1  # 지운 감시 수
    assert take_news(db, keys, "u1") == []
    assert db.execute("SELECT count(*) FROM watch_events").fetchone()[0] == 1  # u1의 기록은 함께 사라졌다
    assert [n["number"] for n in take_news(db, keys, "u2")] == ["DEMO0001"]  # u2는 그대로
    assert forget_user(db, "nobody") == 0


def test_remove_watch_deletes_one_cargo_and_its_events_for_that_user_only(db, keys):
    # [왜] R-033: 감시를 끄면 그 화물의 줄과 변화 기록이 남지 않는다. 같은 번호의 남의 감시는 그대로다
    add_watch(db, keys, "u1", "DEMO0001", "반입신고")
    add_watch(db, keys, "u1", "DEMO0002", "반입신고")
    add_watch(db, keys, "u2", "DEMO0001", "반입신고")
    recheck(db, keys, cleared)
    assert remove_watch(db, keys, "u1", "DEMO0001") == 1
    assert [n["number"] for n in take_news(db, keys, "u1")] == ["DEMO0002"]  # 지운 화물의 변화도 사라졌다
    assert [n["number"] for n in take_news(db, keys, "u2")] == ["DEMO0001"]
    assert remove_watch(db, keys, "u1", "DEMO0001") == 0  # 이미 지웠다


def test_list_watched_gives_that_users_numbers_in_order(db, keys):
    # [왜] 컨테이너 번호로 아는 화물을 찾을 때 감시 목록도 본다 (계획 6a). 남의 감시는 보이지 않는다
    add_watch(db, keys, "u1", "DEMO0002", "수입신고")
    add_watch(db, keys, "u1", "DEMO0003", "수입신고수리")
    add_watch(db, keys, "u2", "DEMO0001", "반입신고")
    add_watch(db, make_keys(), "u1", "DEMO0001", "반입신고")  # 다른 키로 넣은 줄은 풀지 못해 건너뛴다
    assert list_watched(db, keys, "u1") == ["DEMO0002", "DEMO0003"]
    assert list_watched(db, keys, "nobody") == []


def test_watch_keys_repr_hides_hash_key():
    secret = Fernet.generate_key().decode()
    assert repr(derive_key(secret, HASH_INFO)) not in repr(
        watch_keys(secret)
    )  # 로그에 해시 키가 찍히지 않는다


def test_fernet_uses_the_derived_encrypt_key():
    secret = Fernet.generate_key().decode()
    token = watch_keys(secret).fernet.encrypt(b"DEMO0001")
    derived = Fernet(base64.urlsafe_b64encode(derive_key(secret, ENCRYPT_INFO)))
    assert derived.decrypt(token) == b"DEMO0001"  # 파생한 암호화 키로 풀린다
    with pytest.raises(InvalidToken):
        Fernet(secret).decrypt(token)  # 비밀 그대로는 열리지 않는다
