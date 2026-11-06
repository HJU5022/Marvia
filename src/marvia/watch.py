"""감시 목록: 화물을 서버에 등록해 두고, 다시 조회해 단계가 바뀌면 기록했다가 다음 대화에서 알린다 (계획 3d).

하지 않는 일: 주기 실행(상주 프로그램 없이 scripts/recheck_watch.py를 cron 같은 바깥 도구가 부른다),
LLM 호출. [주의] 표에는 실제 번호가 암호화(Fernet)된 채로만 있다. 이 파일의 함수만 풀어 읽고,
그래프에는 토큰으로 바꿔 보인다. 같은 번호 검사는 키가 있는 해시(HMAC)로 한다 (설계 8절, R-033).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass, field

import psycopg
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from marvia.identify.models import CargoFacts, ToolError
from marvia.tools.unipass_replay import lookup_cargo

ENCRYPT_INFO = b"marvia-watch-encrypt"
HASH_INFO = b"marvia-watch-hash"


@dataclass(frozen=True)
class WatchKeys:
    """감시 표의 번호를 암호화하는 Fernet과 같은 번호 검사용 해시 키."""

    fernet: Fernet
    # [주의] 기본 repr는 바이트를 그대로 찍는다. 로그나 예외 글에 해시 키가 새지 않게 repr에서 뺀다
    hash_key: bytes = field(repr=False)


def derive_key(secret: str, info: bytes) -> bytes:
    """비밀 하나에서 용도(info)별 32바이트 키를 뽑는다 (HKDF-SHA256)."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(secret.encode())


def watch_keys(secret: str) -> WatchKeys:
    """MARVIA_WATCH_KEY 하나에서 암호화 키와 해시 키를 따로 뽑는다."""
    # [왜] HKDF는 비밀번호용 느린 해시가 아니다. 사람이 친 짧은 비밀은 DB를 훔친 쪽이 대입으로 풀 수 있어,
    #      Fernet.generate_key()로 만든 무작위 키만 받는다(틀린 모양이면 Fernet이 ValueError를 낸다)
    # [주의] 오류 글에 비밀을 넣지 않는다. from None으로 원래 오류의 이어짐도 끊는다
    try:
        Fernet(secret)
    except ValueError:
        raise ValueError("MARVIA_WATCH_KEY가 비어 있거나 올바른 Fernet 키가 아닙니다") from None
    # [왜] 한 비밀에서 키 둘을 따로 뽑아, 한 쪽 쓰임이 새도 다른 쪽이 열리지 않게 한다
    fernet = Fernet(base64.urlsafe_b64encode(derive_key(secret, ENCRYPT_INFO)))  # Fernet은 base64 키를 받는다
    return WatchKeys(fernet=fernet, hash_key=derive_key(secret, HASH_INFO))


def number_hash(keys: WatchKeys, number: str) -> str:
    """같은 번호 검사용 해시. [왜] 암호문은 넣을 때마다 달라서 유일성 검사에 쓸 수 없다"""
    return hmac.new(keys.hash_key, number.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class WatchDeps:
    """그래프가 쓰는 감시 목록 기능 묶음. 실제 값은 live_watch가 만들고, 시험은 가짜 함수를 넣는다."""

    add: Callable[[str, str, str], None]  # (사용자, 실제 번호, 지금 단계) → 감시 목록에 넣기
    news: Callable[[str], list[dict]]  # 사용자 → 아직 보이지 않은 변화 [{"number", "old_stage", "new_stage"}]


def add_watch(conn: psycopg.Connection, keys: WatchKeys, user: str, number: str, stage: str) -> None:
    """화물 하나를 사용자의 감시 목록에 암호화해 넣는다. 이미 있으면 그대로 둔다."""
    try:
        conn.execute(
            "INSERT INTO watches (user_id, number_enc, number_hash, stage) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (user_id, number_hash) DO NOTHING",
            (user, keys.fernet.encrypt(number.encode()).decode(), number_hash(keys, number), stage),
        )
        conn.commit()
    except psycopg.Error:
        # [왜] 실패한 트랜잭션이 남으면 같은 연결의 다음 질의가 모두 죽는다. 되돌린 뒤 다시 던진다
        conn.rollback()
        raise


def recheck(
    conn: psycopg.Connection,
    keys: WatchKeys,
    lookup: Callable[[str], CargoFacts | ToolError] = lookup_cargo,
) -> int:
    """감시 중인 화물을 모두 다시 조회해 단계가 바뀐 것을 기록한다. 바뀐 화물 수를 돌려준다."""
    changed = 0
    watches = conn.execute("SELECT id, number_enc, stage FROM watches ORDER BY id").fetchall()
    for watch_id, number_enc, stage in watches:
        try:
            result = lookup(keys.fernet.decrypt(number_enc.encode()).decode())
        except (OSError, ValueError, InvalidToken):
            # [왜] 한 줄의 조회 오류가 다른 줄까지 멈추지 않게 건너뛰고 다음 실행에서 다시 본다
            #      (graph/identify.py의 identify_number와 같은 규칙).
            #      다른 키로 암호화된 줄(InvalidToken)도 같다
            continue
        # [왜] 조회 실패는 단계 변화가 아니다. 기록하지 않고 다음 실행에서 다시 본다
        if not isinstance(result, CargoFacts) or result.stage == stage:
            continue
        conn.execute(
            "INSERT INTO watch_events (watch_id, old_stage, new_stage) VALUES (%s, %s, %s)",
            (watch_id, stage, result.stage),
        )
        conn.execute("UPDATE watches SET stage = %s WHERE id = %s", (result.stage, watch_id))
        conn.commit()  # [왜] 줄마다 확정한다. 뒤 줄에서 죽어도 앞에서 찾은 변화는 남는다
        changed += 1
    conn.commit()  # 바뀐 줄이 없어도 읽기 트랜잭션을 닫는다
    return changed


def take_news(conn: psycopg.Connection, keys: WatchKeys, user: str) -> list[dict]:
    """사용자의 아직 보이지 않은 변화를 꺼내고 본 것으로 표시한다. 기록된 순서대로 돌려준다."""
    try:
        rows = conn.execute(
            "UPDATE watch_events AS e SET seen = true FROM watches AS w "
            "WHERE e.watch_id = w.id AND w.user_id = %s AND NOT e.seen "
            "RETURNING e.id, w.number_enc, e.old_stage, e.new_stage",
            (user,),
        ).fetchall()
        conn.commit()
    except psycopg.Error:
        # [왜] 실패한 트랜잭션이 남으면 같은 연결의 다음 질의가 모두 죽는다. 되돌려 seen 표시도 취소한다
        conn.rollback()
        raise
    # [왜] UPDATE ... RETURNING은 순서를 정해 주지 않는다. 기록 id 순서로 정렬한다
    news = []
    for _, enc, old, new in sorted(rows):
        try:
            number = keys.fernet.decrypt(enc.encode()).decode()
        except InvalidToken:
            # [왜] 키를 바꾼 뒤 남은 줄은 번호를 알 수 없어 알릴 수 없다. 나머지 소식은 그대로 보인다
            continue
        news.append({"number": number, "old_stage": old, "new_stage": new})
    return news


def forget_user(conn: psycopg.Connection, user: str) -> int:
    """사용자의 감시 목록과 변화 기록을 모두 지우고 지운 감시 수를 돌려준다.

    계정 삭제용이다 (설계 8절). 화물 하나만 감시를 끄는 기능은 화면과 함께 온다 (done.md 4.1).
    """
    try:
        # [왜] watch_events는 ON DELETE CASCADE라 감시 줄을 지우면 변화 기록도 함께 지워진다
        deleted = conn.execute("DELETE FROM watches WHERE user_id = %s", (user,)).rowcount
        conn.commit()
    except psycopg.Error:
        # [왜] 실패한 트랜잭션이 남으면 같은 연결의 다음 질의가 모두 죽는다. 되돌린 뒤 다시 던진다
        conn.rollback()
        raise
    return deleted


def live_watch(conn: psycopg.Connection, keys: WatchKeys) -> WatchDeps:
    """로컬 DB 연결과 키로 감시 목록 기능을 만든다."""
    return WatchDeps(
        add=lambda user, number, stage: add_watch(conn, keys, user, number, stage),
        news=lambda user: take_news(conn, keys, user),
    )
