"""B/L 원본 잠그기·열기 (작업 G3 뒤 ② 암호화, 09-30 결정).

메모리("이 B/L 다시 볼까요?")는 원본 B/L이 있어야 다시 조회할 수 있다. 가린 번호(bl_masked)로는 못 한다.
그래서 로그인한 사용자의 B/L만 잠가서 저장하고, 다시 조회할 때만 서버가 연다. 손님 B/L은 지금처럼 저장하지 않는다.

왜 이렇게 했나:
- 대칭키 방식이다. 잠그는 열쇠와 여는 열쇠가 같다 (로그인 출입증의 공개키 방식과 반대, auth.py)
- 서버(파이썬)에서 잠그고 DB에는 잠긴 글자만 보낸다. DB의 pgcrypto를 쓰면 열쇠가 SQL에 실려 DB 로그에 남을 수 있다.
  열쇠는 .env의 BL_ENCRYPTION_KEY(배포는 Cloud Run Secret Manager)에만 둔다. DB가 새도 열쇠는 따로 있다
- Fernet(cryptography 라이브러리)은 AES 암호화와 위조 검사를 묶은 표준 레시피다. 암호 조합을 직접 짜지 않는다
- 같은 값을 두 번 잠가도 결과가 매번 다르다. 그래서 잠긴 글자로는 검색할 수 없고, 찾기는 bl_masked로 한다

실패하면 예외 대신 None을 돌려준다. 열쇠가 없거나 틀려도 판정은 돌아야 하기 때문이다 (채점용 compose는 열쇠 없이 돈다).
열쇠를 잃어버리면 저장된 B/L은 다시 열 수 없다. 메모리의 "다시 조회"만 안 되고 판정은 영향이 없다.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

from backend.app.observability.logging import log_failure


def _fernet() -> Fernet | None:
    """.env의 열쇠로 자물쇠를 만든다. 열쇠가 없거나 모양이 틀리면 None."""
    key = os.environ.get("BL_ENCRYPTION_KEY", "").strip()
    if not key:
        return None
    try:
        return Fernet(key)
    except ValueError:  # 44자 base64가 아니면 Fernet이 거절한다. 열쇠 값은 로그에 넣지 않는다
        log_failure("crypto", "bad_key")
        return None


def encrypt(text: str) -> str | None:
    """원본을 잠근 글자를 돌려준다. 열쇠가 없으면 None(부르는 쪽은 저장하지 않는다)."""
    fernet = _fernet()
    if fernet is None:
        log_failure("crypto_encrypt", "no_key")
        return None
    return fernet.encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str | None:
    """잠긴 글자를 원본으로 연다. 열쇠가 없거나, 다른 열쇠로 잠갔거나, 글자가 바뀌었으면 None."""
    fernet = _fernet()
    if fernet is None:
        log_failure("crypto_decrypt", "no_key")
        return None
    try:
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:  # 열쇠가 다르거나 누가 글자를 고쳤다. 위조 검사가 여기서 잡는다
        log_failure("crypto_decrypt", "invalid_token")
        return None
