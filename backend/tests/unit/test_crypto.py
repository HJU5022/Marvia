"""B/L 잠그기·열기 테스트 (backend/app/crypto.py). 열쇠는 테스트 안에서 새로 만든다. B/L은 가공값이다."""
import pytest
from cryptography.fernet import Fernet

from backend.app import crypto

BL = "TESTMBL0000001"  # 모의 B/L


@pytest.fixture(autouse=True)
def key(monkeypatch):
    k = Fernet.generate_key().decode()
    monkeypatch.setenv("BL_ENCRYPTION_KEY", k)
    return k


def test_round_trip():
    assert crypto.decrypt(crypto.encrypt(BL)) == BL


def test_locked_text_hides_original_and_differs_each_time():
    """잠긴 글자에 원본이 보이지 않고, 같은 값을 두 번 잠가도 결과가 다르다 (그래서 검색은 bl_masked로)."""
    first, second = crypto.encrypt(BL), crypto.encrypt(BL)
    assert BL not in first and first != second


def test_other_key_cannot_open(monkeypatch):
    locked = crypto.encrypt(BL)
    monkeypatch.setenv("BL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert crypto.decrypt(locked) is None


def test_tampered_text_is_rejected():
    locked = crypto.encrypt(BL)
    # 가운데 한 글자를 바꾼다. 끝 글자는 base64 채움 비트라 바꿔도 내용이 안 바뀔 수 있다
    i = len(locked) // 2
    tampered = locked[:i] + ("A" if locked[i] != "A" else "B") + locked[i + 1:]
    assert crypto.decrypt(tampered) is None


def test_no_key_means_nothing_stored(monkeypatch):
    """열쇠가 없으면(채점용 compose) 잠그지도 열지도 않는다. 예외 없이 None."""
    locked = crypto.encrypt(BL)
    monkeypatch.delenv("BL_ENCRYPTION_KEY")
    assert crypto.encrypt(BL) is None and crypto.decrypt(locked) is None


def test_malformed_key_is_treated_as_missing(monkeypatch):
    monkeypatch.setenv("BL_ENCRYPTION_KEY", "my-password-1234")  # 사람이 정한 비밀번호 같은 값은 열쇠로 못 쓴다
    assert crypto.encrypt(BL) is None
