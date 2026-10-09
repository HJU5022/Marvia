"""B/L 원본 잠그기·열기 (작업 G3 뒤 ② 암호화).

메모리("이 B/L 다시 볼까요?")는 원본 B/L이 있어야 다시 조회할 수 있다. 가린 번호(bl_masked)로는 못 한다.
그래서 로그인한 사용자의 B/L만 잠가서 저장하고, 다시 조회할 때만 서버가 연다. 로그인 기능이 꺼진 채점 환경에서는 저장하지 않는다.

왜 이렇게 했나:
- 대칭키 방식이다. 잠그는 열쇠와 여는 열쇠가 같다 (로그인 출입증의 공개키 방식과 반대, auth.py)
- 서버(파이썬)에서 잠그고 DB에는 잠긴 글자만 보낸다. DB의 pgcrypto를 쓰면 열쇠가 SQL에 실려 DB 로그에 남을 수 있다.
  열쇠는 .env의 BL_ENCRYPTION_KEY(배포는 Railway 서비스 환경변수)에만 둔다. DB가 새도 열쇠는 따로 있다
- Fernet(cryptography 라이브러리)은 AES 암호화와 위조 검사를 묶은 표준 레시피다. 암호 조합을 직접 짜지 않는다
- 같은 값을 두 번 잠가도 결과가 매번 다르다. 그래서 잠긴 글자로는 검색할 수 없고, 찾기는 bl_masked로 한다

실패하면 예외 대신 None을 돌려준다. 열쇠가 없거나 틀려도 판정은 돌아야 하기 때문이다 (채점용 compose는 열쇠 없이 돈다).
열쇠를 잃어버리면 저장된 B/L은 다시 열 수 없다. 메모리의 "다시 조회"만 안 되고 판정은 영향이 없다.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

from backend.app.observability.logging import log_failure


BL_KEY_ENV = "BL_ENCRYPTION_KEY"
# 회원 정보(이름·전화·주소)와 운영자 이메일 전용 열쇠. B/L 열쇠와 따로 두어 한쪽이 새도 다른 쪽은 안전하다.
# 없으면 B/L 열쇠로 대신하지 않는다(나눈 의미가 없어진다). 부르는 쪽은 저장·비교를 하지 않는다
PII_KEY_ENV = "PII_ENCRYPTION_KEY"


def _fernet(key_env: str = BL_KEY_ENV) -> Fernet | None:
    """.env의 열쇠로 자물쇠를 만든다. 열쇠가 없거나 모양이 틀리면 None."""
    key = os.environ.get(key_env, "").strip()
    if not key:
        return None
    try:
        return Fernet(key)
    except ValueError:  # 44자 base64가 아니면 Fernet이 거절한다. 열쇠 값은 로그에 넣지 않는다
        log_failure("crypto", "bad_key")
        return None


def encrypt(text: str, key_env: str = BL_KEY_ENV) -> str | None:
    """원본을 잠근 글자를 돌려준다. 열쇠가 없으면 None(부르는 쪽은 저장하지 않는다)."""
    fernet = _fernet(key_env)
    if fernet is None:
        log_failure("crypto_encrypt", "no_key")
        return None
    return fernet.encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token: str, key_env: str = BL_KEY_ENV) -> str | None:
    """잠긴 글자를 원본으로 연다. 열쇠가 없거나, 다른 열쇠로 잠갔거나, 글자가 바뀌었으면 None."""
    fernet = _fernet(key_env)
    if fernet is None:
        log_failure("crypto_decrypt", "no_key")
        return None
    try:
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:  # 열쇠가 다르거나 누가 글자를 고쳤다. 위조 검사가 여기서 잡는다
        log_failure("crypto_decrypt", "invalid_token")
        return None


# ── 찾기용 지문 (docs/specs/operator-admin.md "이메일 암호화") ──
# Fernet은 같은 값도 매번 다르게 잠가서 WHERE 비교를 할 수 없다. 운영자 이메일처럼 "같은지"만 알면 되는 값은
# HMAC-SHA256 지문으로 찾고, 화면에 보여 줄 원문은 encrypt()로 따로 잠근다.
# 지문 열쇠는 PII_ENCRYPTION_KEY에서 용도 이름을 붙여 갈라 쓴다. 같은 열쇠를 두 용도에 그대로 쓰지 않으려는 것이다.
# 원문으로 되돌릴 수 없다. 열쇠가 없으면 None (부르는 쪽은 저장·비교를 하지 않는다).

def fingerprint(text: str, key_env: str = PII_KEY_ENV) -> str | None:
    """같은 글자면 늘 같은 64자 16진수. 소문자·앞뒤 공백 정리는 부르는 쪽이 한다."""
    import hashlib
    import hmac

    key = os.environ.get(key_env, "").strip()
    if not key:
        log_failure("crypto_fingerprint", "no_key")
        return None
    sub_key = hashlib.sha256(b"marvia-fingerprint:" + key.encode("utf-8")).digest()
    return hmac.new(sub_key, text.encode("utf-8"), hashlib.sha256).hexdigest()



def encrypt_pii(text: str) -> str | None:
    """개인정보(회원 정보·운영자 이메일)를 PII 열쇠로 잠근다. 열쇠가 없으면 None."""
    return encrypt(text, PII_KEY_ENV)


def decrypt_pii(token: str) -> str | None:
    """PII 열쇠로 연다. 열쇠가 없거나 다른 열쇠로 잠갔으면 None."""
    return decrypt(token, PII_KEY_ENV)
