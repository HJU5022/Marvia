"""회원 정보(이름, 전화번호, 주소) 검사, 암호화 저장, 마스킹 (docs/specs/user-profile.md).

- 저장: 형식 검사 → crypto.encrypt_pii(PII_ENCRYPTION_KEY)로 잠금 → DB에는 잠긴 글자만. 열쇠가 없으면 원문을 저장하지 않고 ProfileError(no_key)
- 읽기: 본인 화면에만 원문(decrypt). 운영자 고객 관리에는 mask_*로 가린 값만
- 지우기: 탈퇴(services/account/account.py)가 부른다
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app import crypto

NAME_MAX = 30
ADDRESS_MIN, ADDRESS_MAX = 5, 200
# 휴대전화: 010, 011, 016~019 + 7~8자리 (Spec EC-02). 하이픈·공백은 빼고 본다
_PHONE = re.compile(r"^01[016789]\d{7,8}$")


class ProfileError(Exception):
    """저장할 수 없다. kind: consent / name / phone / address / no_key."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True)
class Profile:
    name: str
    phone: str     # 숫자만, 화면에 보일 때 format_phone으로 하이픈
    address: str


def clean(name: str, phone: str, address: str, consent: bool) -> Profile:
    """입력을 다듬고 검사한다. 동의가 없으면 다른 칸보다 먼저 거절한다 (EC-01)."""
    if not consent:
        raise ProfileError("consent")
    name = " ".join((name or "").split())
    if not 1 <= len(name) <= NAME_MAX:
        raise ProfileError("name")
    digits = re.sub(r"\D", "", phone or "")
    if not _PHONE.match(digits):
        raise ProfileError("phone")
    address = " ".join((address or "").split())
    if not ADDRESS_MIN <= len(address) <= ADDRESS_MAX:
        raise ProfileError("address")
    return Profile(name=name, phone=digits, address=address)


def format_phone(digits: str) -> str:
    """01012345678 -> 010-1234-5678, 0111234567 -> 011-123-4567."""
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return digits


def mask_name(name: str | None) -> str | None:
    """첫 글자만 남긴다. operators.mask_name과 같은 규칙."""
    if not name or not name.strip():
        return None
    name = name.strip()
    return name[0] + "*" * (len(name) - 1)


def mask_phone(digits: str | None) -> str | None:
    """010-****-5678. 앞 3자리와 뒤 4자리만."""
    if not digits or len(digits) < 7:
        return None
    return f"{digits[:3]}-****-{digits[-4:]}"


def mask_address(address: str | None) -> str | None:
    """앞 두 마디(시·도, 시·군·구)만 남긴다. 서울특별시 강남구 테헤란로 1 -> 서울특별시 강남구 ***."""
    if not address or not address.strip():
        return None
    parts = address.split()
    return " ".join(parts[:2]) + " ***" if len(parts) > 2 else parts[0] + " ***"


def save(conn, user_id: str, profile: Profile, *, by_operator: bool = False) -> None:
    """잠가서 저장한다. 하나라도 못 잠그면(열쇠 없음) 아무것도 저장하지 않는다 (EC-04).
    by_operator: 운영자가 고친 경우. 본인 동의 시각(consent_at)은 그대로 둔다 (operator-admin 추가 절)."""
    sealed = [crypto.encrypt_pii(v) for v in (profile.name, profile.phone, profile.address)]  # PII 열쇠 (분리)
    if any(s is None for s in sealed):
        raise ProfileError("no_key")
    consent = "user_profiles.consent_at" if by_operator else "now()"
    conn.execute(
        f"""
        INSERT INTO user_profiles (user_id, name_enc, phone_enc, address_enc, consent_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (user_id) DO UPDATE SET name_enc = EXCLUDED.name_enc, phone_enc = EXCLUDED.phone_enc,
          address_enc = EXCLUDED.address_enc, consent_at = {consent}, updated_at = now()
        """,
        [user_id, *sealed],
    )


def _open(row) -> Profile | None:
    """잠긴 세 칸을 연다. 하나라도 못 열면(열쇠 바뀜) None (EC-07)."""
    values = [crypto.decrypt_pii(v) for v in row]
    return None if any(v is None for v in values) else Profile(*values)


def load(conn, user_id: str) -> Profile | None:
    """본인 정보 원문. 없거나 열 수 없으면 None."""
    row = conn.execute("SELECT name_enc, phone_enc, address_enc FROM user_profiles WHERE user_id = %s",
                       [user_id]).fetchone()
    return _open(row) if row else None


def exists(conn, user_id: str) -> bool:
    """입력을 마쳤는가. 열 수 있는지까지는 보지 않는다 (/api/me를 가볍게)."""
    return conn.execute("SELECT 1 FROM user_profiles WHERE user_id = %s", [user_id]).fetchone() is not None


def masked_by_user(conn) -> dict[str, dict]:
    """운영자 고객 관리용. user_id별로 가린 값만 돌려준다. 원문은 이 함수 밖으로 나가지 않는다."""
    out = {}
    for user_id, *sealed in conn.execute(
            "SELECT user_id, name_enc, phone_enc, address_enc FROM user_profiles").fetchall():
        p = _open(sealed)
        out[user_id] = ({"name": mask_name(p.name), "phone": mask_phone(p.phone), "address": mask_address(p.address)}
                        if p else {"name": None, "phone": None, "address": None, "unreadable": True})
    return out


def delete(conn, user_id: str) -> int:
    """탈퇴 때 지운다 (EC-08). 지운 줄 수."""
    return conn.execute("DELETE FROM user_profiles WHERE user_id = %s", [user_id]).rowcount
