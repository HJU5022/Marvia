"""DB 접근은 이 파일 하나로 모은다. (SDD 1절: "Postgres 접근(asyncpg, DATABASE_URL), 암호화, expires_at 계산")

라우터·파이프라인은 SQL을 직접 쓰지 않고 여기 함수를 부른다. 그래서
  - 로컬 컨테이너 ↔ Supabase 전환은 DATABASE_URL 값만 바꾸면 되고,
  - 암호화 방식을 바꿔도 이 파일만 고치면 된다.

이 파일이 책임지는 것 세 가지:
  1. 연결 풀   — DATABASE_URL로 asyncpg 풀을 열고 재사용
  2. 암호화    — 참석자 이름·출발지·경로·API 응답을 AES-256-GCM으로 (테이블정의서 7절)
  3. expires_at — 세션 만료 시각 계산. DB 기본값이 없으므로 여기서 넣는다 (테이블정의서 1절, 규칙 session.md)

지금은 위 세 가지의 기반 함수만 있다. 표별 저장·조회 함수(create_session, save_result, ...)는
다음 조각에서 이 아래에 붙인다.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import asyncpg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.app.domain import rules  # 도커(/app)와 로컬 모두 저장소 루트 기준 경로

# ─────────────────────────────────────────────────────────────────────────────
# 1. 연결 풀
# ─────────────────────────────────────────────────────────────────────────────
# "풀"은 DB 연결을 미리 몇 개 열어 두고 요청마다 빌려 쓰는 것. 요청마다 새로 접속하면
# 매번 인증·핸드셰이크가 들어가 느리다. 앱이 뜰 때 한 번 만들고 내릴 때 닫는다.

_log = logging.getLogger(__name__)
_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """풀을 돌려준다. 처음 부르면 만들고, 그 뒤로는 만든 것을 재사용한다.

    DATABASE_URL 예)
      로컬: postgresql://app:app@db:5432/app          (.env.example 기본값. db = compose 서비스 이름)
      운영: postgresql://...supabase.com:6543/postgres (Supabase 대시보드 > Connect)
    접두사는 postgresql:// 이어야 한다. postgresql+asyncpg:// 는 SQLAlchemy용이라 asyncpg가 못 읽는다.
    """
    global _pool
    if _pool is None:
        url = os.environ["DATABASE_URL"]  # 없으면 KeyError. 조용히 기본값으로 붙는 것보다 낫다
        _pool = await _create_pool_with_retry(url)
    return _pool


# 첫 접속이 이름 풀이(DNS)에서 가끔 실패한다. Supabase pooler 는 IP 를 여러 개 돌려 쓰고 TTL 이 짧아,
# 캐시가 비는 순간 조회가 늦으면 리졸버가 실패로 처리한다 (Windows WSAHOST_NOT_FOUND, 09-18 실측).
# 바로 다시 하면 붙으므로 몇 번 기다렸다 다시 해 본다. 여기서 포기하면 앱이 기동조차 못 한다.
_RETRY_WAITS_SEC = (1, 2, 4)


async def _create_pool_with_retry(url: str) -> asyncpg.Pool:
    """풀을 만든다. 일시적인 접속 실패는 몇 번 다시 해 보고, 그래도 안 되면 그대로 올린다.

    다시 해 보는 것: OSError 계열 (DNS 실패, 연결 거절, 타임아웃)
    다시 하지 않는 것: 비밀번호가 틀렸거나 DB 이름이 없는 경우. 기다린다고 달라지지 않는다.
    """
    last: Exception | None = None
    for wait in (*_RETRY_WAITS_SEC, None):
        try:
            return await asyncpg.create_pool(url, min_size=1, max_size=5)
        except (OSError, asyncio.TimeoutError) as e:
            last = e
            if wait is None:
                break
            _log.warning("DB 접속 실패(%s). %s초 뒤 다시 시도합니다", type(e).__name__, wait)
            await asyncio.sleep(wait)
    raise last if last else RuntimeError("DB 접속에 실패했습니다")


async def close_pool() -> None:
    """앱 종료 시 호출. 열린 연결을 정리한다. (main.py의 shutdown 훅에서 부를 예정)"""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ─────────────────────────────────────────────────────────────────────────────
# 2. 암호화 (테이블정의서 7절)
# ─────────────────────────────────────────────────────────────────────────────
# 방식: 애플리케이션 단 AES-256-GCM. 키는 환경변수 ENCRYPTION_KEY(32바이트를 base64로 적은 것).
# 저장 형식: [nonce 12바이트][암호문]. nonce는 행마다 새로 뽑는 난수로, 같은 평문을 두 번
# 암호화해도 결과가 달라지게 한다. 복호화할 때 다시 필요하므로 값 앞에 붙여 한 컬럼에 넣는다.
#
# 대상 컬럼(_enc): sessions.participants_enc, rendezvous_enc / results.candidates_enc,
#                 per_participant_enc / route_cache.response_enc
# DB 관리자 화면(Supabase 대시보드)에서는 암호문만 보인다. 키는 서버에만 있다.

_NONCE_LEN = 12  # GCM 표준 nonce 길이. 테이블정의서 7절 "nonce 12바이트"


def _key() -> bytes:
    """ENCRYPTION_KEY를 base64에서 풀어 32바이트 키로. 길이가 틀리면 즉시 실패한다."""
    raw = base64.b64decode(os.environ["ENCRYPTION_KEY"])
    if len(raw) != 32:
        raise ValueError(f"ENCRYPTION_KEY는 32바이트여야 함 (지금 {len(raw)}바이트). AES-256")
    return raw


def encrypt(obj: dict | list) -> bytes:
    """dict/list → 암호문 bytes. DB의 bytea 컬럼에 그대로 넣는다.

    예) encrypt([{"name": "김철수", "origin_text": "진해"}]) -> b'\\x8a\\x3f...'
    """
    plain = json.dumps(obj, ensure_ascii=False).encode("utf-8")  # ensure_ascii=False: 한글을 \\uXXXX로 안 바꿈
    nonce = os.urandom(_NONCE_LEN)                               # 행마다 새 난수
    cipher = AESGCM(_key()).encrypt(nonce, plain, None)          # None: 추가 인증 데이터 없음
    return nonce + cipher


def decrypt(blob: bytes) -> dict | list:
    """암호문 bytes → 원래 dict/list. encrypt의 역.

    키가 다르거나 암호문이 1바이트라도 바뀌었으면 InvalidTag 예외가 난다(GCM의 변조 검사).
    """
    nonce, cipher = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    plain = AESGCM(_key()).decrypt(nonce, cipher, None)
    return json.loads(plain.decode("utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# 3. expires_at 계산 (테이블정의서 1절·6절, 규칙 skills/converge/rules/session.md)
# ─────────────────────────────────────────────────────────────────────────────
# sessions.expires_at은 DB 기본값이 없다. 원래 now()+7일이었는데 한 달 뒤 약속의 링크가
# 약속 전에 죽는 문제가 있어(09-17), 기준을 "생성"에서 "약속"으로 옮기고 코드가 계산하게 했다.
# 일수(30·7)는 코드에 적지 않고 session.md 프론트매터에서 읽는다 (SDD 7절 원칙).


def calc_expires_at(meet_at: datetime | None, created_at: datetime) -> datetime:
    """세션 만료 시각.

      meet_at 있음         → meet_at + retain_after_meet_days (30일)
      meet_at 없음(임시 세션) → created_at + draft_retain_days (7일)

    재질문으로 meet_at이 새로 들어오면 이 함수를 다시 불러 UPDATE한다 (SDD 5절 8단계).
    """
    r = rules.load_rule("session")
    if meet_at is not None:
        return meet_at + timedelta(days=r["retain_after_meet_days"])
    return created_at + timedelta(days=r["draft_retain_days"])


def is_locked(meet_at: datetime | None, now: datetime | None = None) -> bool:
    """수정 잠금 여부 (SDD 5절 재질문, session.md lock_after_meet: next_day).

    약속 다음날 0시(UTC 기준)가 지났으면 True → 라우터가 409를 돌려주고 LLM을 부르지 않는다.
    meet_at이 없는 임시 세션은 잠글 약속이 없으므로 항상 False.
    """
    if meet_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    next_day_start = (meet_at + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return now >= next_day_start


# ─────────────────────────────────────────────────────────────────────────────
# 4. sessions (테이블정의서 1절)
# ─────────────────────────────────────────────────────────────────────────────
# 대화 한 건. 공유 링크의 대상. 참석자 목록은 별도 표가 아니라 participants_enc 한 컬럼에
# JSON으로 넣는다 (원칙 1). 이 함수들은 평문 dict를 받아 암호화해서 넣고, 꺼낼 때 복호화한다.
# 호출하는 쪽(파이프라인·라우터)은 암호화를 모른다.

async def create_session(
    *,
    user_id: str,
    preset: str,
    participants: list[dict],
    meet_at: datetime | None = None,
    purpose: str | None = None,
    destination_name: str | None = None,
    destination_lng: float | None = None,
    destination_lat: float | None = None,
    rendezvous: dict | None = None,
    access: dict | None = None,
    schedule_confirmed: bool | None = None,
    constraints: list[str] | None = None,
) -> str:
    """세션 한 건 INSERT. 새 세션 id(uuid 문자열)를 돌려준다.

    user_id: services/auth.py가 토큰에서 꺼낸 주선자 id. 본문이 아니라 토큰에서 온다 (SDD 2절).
    participants: 평문 리스트. 여기서 암호화한다. 구조는 테이블정의서 1절 participants_enc 설명.
    expires_at: DB 기본값이 없으므로 calc_expires_at으로 계산해 넣는다.
    status: 처음은 'draft'. meet_at이 없으면 임시 세션이고 이 상태에 머문다 (테이블정의서 6절).
    """
    now = datetime.now(timezone.utc)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO sessions (
            preset, meet_at, purpose, destination_name, destination_lng, destination_lat,
            participants_enc, participant_count, rendezvous_enc, access, schedule_confirmed,
            constraints, status, user_id, created_at, updated_at, expires_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'draft', $13, $14, $14, $15)
        RETURNING id
        """,
        preset, meet_at, purpose, destination_name, destination_lng, destination_lat,
        encrypt(participants), len(participants),
        encrypt(rendezvous) if rendezvous is not None else None,
        json.dumps(access) if access is not None else None,          # jsonb 컬럼은 문자열로 넘긴다
        schedule_confirmed,
        json.dumps(constraints or []),
        user_id, now, calc_expires_at(meet_at, now),
    )
    return str(row["id"])


async def get_session(session_id: str) -> dict | None:
    """세션 한 건을 평문 dict로. 없거나 만료됐으면 None.

    공유 링크(GET /api/session/{id})와 재질문(POST /api/agent)이 쓴다.
    만료된 행은 배치가 지우기 전이라도 없는 것으로 친다 (SDD 2절: "만료 전이면 반환").
    _enc 컬럼은 복호화해서 participants / rendezvous 키로 돌려준다.
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM sessions WHERE id = $1 AND expires_at > now()", session_id
    )
    if row is None:
        return None
    d = dict(row)
    d["participants"] = decrypt(d.pop("participants_enc"))
    d["rendezvous"] = decrypt(d.pop("rendezvous_enc")) if d["rendezvous_enc"] is not None else None
    d.pop("rendezvous_enc", None)
    # jsonb는 asyncpg가 문자열로 주므로 파이썬 객체로 되돌린다
    d["access"] = json.loads(d["access"]) if d["access"] else None
    d["constraints"] = json.loads(d["constraints"]) if d["constraints"] else []
    d["id"] = str(d["id"])
    d["user_id"] = str(d["user_id"])
    return d


async def update_session(
    session_id: str,
    *,
    participants: list[dict] | None = None,
    meet_at: datetime | None = None,
    status: str | None = None,
    rendezvous: dict | None = None,
) -> None:
    """세션 일부 갱신. 넘긴 것만 바꾼다.

    쓰는 곳:
      - 핀 확인(SDD 5절 2-1): participants(좌표 수정본) + status='pins_confirmed'
      - 재질문으로 meet_at이 새로 들어옴: meet_at + expires_at 재계산 (임시 세션 → 보통 세션)
      - 계산 끝: status='computed' / 실패: 'failed'
      - 참석자 본인 출발지 수정(PATCH, 자리만): participants
    expires_at은 meet_at이 바뀔 때만 다시 계산한다. created_at은 기존 값을 읽어 쓴다.
    """
    sets: list[str] = ["updated_at = now()"]
    args: list = []

    def add(col: str, val) -> None:
        args.append(val)
        sets.append(f"{col} = ${len(args)}")

    if participants is not None:
        add("participants_enc", encrypt(participants))
        add("participant_count", len(participants))
    if status is not None:
        add("status", status)
    if rendezvous is not None:
        add("rendezvous_enc", encrypt(rendezvous))

    pool = await get_pool()
    if meet_at is not None:
        created = await pool.fetchval("SELECT created_at FROM sessions WHERE id = $1", session_id)
        add("meet_at", meet_at)
        add("expires_at", calc_expires_at(meet_at, created))

    args.append(session_id)
    await pool.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ${len(args)}", *args)


async def list_sessions(user_id: str, limit: int = 20) -> list[dict]:
    """내가 만든 세션 목록. 최근 순. 만료된 것은 뺀다 (SDD 2절 GET /api/sessions).

    암호화된 컬럼(participants_enc, rendezvous_enc)은 읽지 않는다. 목록 화면은 이름이 필요 없고,
    복호화는 비용이 들며 어깨너머로 보이기 쉬운 화면이기 때문이다 (테이블정의서 7절).
    인덱스 (user_id, created_at desc)를 그대로 탄다.
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, preset, status, purpose, destination_name, meet_at,
               participant_count, created_at, expires_at
        FROM sessions
        WHERE user_id = $1 AND expires_at > now()
        ORDER BY created_at DESC
        LIMIT $2
        """,
        user_id, limit,
    )
    return [dict(row) for row in rows]


async def delete_session(session_id: str, user_id: str) -> bool:
    """주선자 직접 삭제 (결정 7, SDD 2절 DELETE). 지웠으면 True, 본인 세션이 아니거나 없으면 False.

    user_id를 WHERE에 같이 걸어서 "본인만"을 SQL 한 줄로 보장한다. 라우터는 False면 403.
    results는 FK ON DELETE CASCADE로 같이 지워진다 (001_init.sql). request_logs·feedback은
    FK가 없어 남는다 — 집계용 (테이블정의서 6절).
    """
    pool = await get_pool()
    result = await pool.execute(
        "DELETE FROM sessions WHERE id = $1 AND user_id = $2", session_id, user_id
    )
    return result == "DELETE 1"  # asyncpg는 "DELETE <행 수>" 문자열을 돌려준다


# ─────────────────────────────────────────────────────────────────────────────
# 5. results (테이블정의서 2절)
# ─────────────────────────────────────────────────────────────────────────────
# 세션의 계산 결과. 재질문마다 새 행이 쌓이고, 공유 링크는 가장 최근 것을 보여준다.

async def save_result(
    *,
    session_id: str,
    candidates: list[dict],
    per_participant: list[dict],
    routed_to: str,
    model_small: str | None = None,
    model_large: str | None = None,
    prompt_version: str | None = None,
    rendezvous_departure: str | None = None,
    provisional: bool = False,
    trace_id: str | None = None,
    confidence: float | None = None,
) -> str:
    """결과 한 건 INSERT (SDD 5절 8단계 store.save). 새 result id를 돌려준다.

    candidates: 집결 후보 리스트(평문). 위병소·고객사 로비 좌표가 있어 암호화 (테이블정의서 7절).
    per_participant: 참석자별 경로·출발 시각(평문). 경로선이 곧 위치정보라 암호화.
    routed_to: 'small' / 'large'. 라우팅 전후 비용 집계에 쓴다 (SDD 5절 라우팅).
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO results (
            session_id, candidates_enc, per_participant_enc, model_small, model_large,
            prompt_version, routed_to, rendezvous_departure, provisional, trace_id, confidence
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        RETURNING id
        """,
        session_id, encrypt(candidates), encrypt(per_participant), model_small, model_large,
        prompt_version, routed_to, rendezvous_departure, provisional, trace_id, confidence,
    )
    return str(row["id"])


async def get_latest_result(session_id: str) -> dict | None:
    """세션의 가장 최근 결과를 평문 dict로. 없으면 None. 공유 링크가 쓴다 (SDD 2절 GET /api/session)."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM results WHERE session_id = $1 ORDER BY created_at DESC LIMIT 1", session_id
    )
    if row is None:
        return None
    d = dict(row)
    d["candidates"] = decrypt(d.pop("candidates_enc"))
    d["per_participant"] = decrypt(d.pop("per_participant_enc"))
    d["id"] = str(d["id"])
    d["session_id"] = str(d["session_id"])
    if d["confidence"] is not None:
        d["confidence"] = float(d["confidence"])  # numeric → Decimal로 오므로 float로
    return d


# ─────────────────────────────────────────────────────────────────────────────
# 6. request_logs (테이블정의서 3절, 가이드 8-2 구조화 로그)
# ─────────────────────────────────────────────────────────────────────────────
# 파이프라인 단계마다 한 줄. 이름·주소 같은 식별 정보는 넣지 않는다 (원칙 5).
# p95 지연·요청당 비용·라우팅 전후 비용이 전부 여기서 나온다 (채점 축 ③·④).

async def log_request(
    *,
    request_id: str,
    stage: str,
    provider: str,
    latency_ms: int,
    status: str,
    session_id: str | None = None,
    model_or_api: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_usd: float | None = None,
    error_type: str | None = None,
    retry_no: int = 0,
    cache_hit: bool = False,
    routed_to: str | None = None,
) -> None:
    """로그 한 줄 INSERT. 실패해도 서비스는 계속 가야 하므로 호출 쪽에서 예외를 삼킬지 정한다.

    stage:  slot_extract / vision / geocode / search_places / route_car / route_transit /
            vessel_schedule / first_last_train / judge / validate
    status: ok / retry / fallback / error
    session_id는 FK 없음 — 세션이 지워진 뒤에도 집계에 남아야 해서 (테이블정의서 6절).
    """
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO request_logs (
            request_id, session_id, stage, provider, model_or_api, tokens_in, tokens_out,
            cost_usd, latency_ms, status, error_type, retry_no, cache_hit, routed_to
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        """,
        request_id, session_id, stage, provider, model_or_api, tokens_in, tokens_out,
        cost_usd, latency_ms, status, error_type, retry_no, cache_hit, routed_to,
    )


async def daily_cost_usd() -> float:
    """오늘 request_logs cost_usd 합. 일일 상한(41번) 검사용. routers/agent.py 가 부른다."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM request_logs "
        "WHERE created_at >= date_trunc('day', now())"
    )
    return float(row["total"])


# ─────────────────────────────────────────────────────────────────────────────
# 7. route_cache (테이블정의서 4절)
# ─────────────────────────────────────────────────────────────────────────────
# 카카오·TMAP 같은 종량제 API 응답을 재사용한다. 평가셋 30건을 여러 번 재측정할 때(필수 4)
# 매번 API를 부르면 비용이 쌓이므로. 키는 좌표를 평문으로 두지 않으려고 sha256 해시만 저장한다.
# cache_key 만드는 규칙(provider, 좌표 소수 4자리, 이동수단, 시각 30분 단위)은 services/routes.py가
# 맡는다. 여기서는 받은 키로 넣고 꺼내기만.

async def cache_get(cache_key: str) -> dict | None:
    """캐시 적중이면 {"response": 복호화한 응답 원문, "summary": 요약} 을, 없거나 만료면 None.

    적중 시 hit_count를 1 올린다 — 캐시가 실제로 비용을 얼마나 아꼈는지 EVAL_REPORT에 적을 근거.
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        UPDATE route_cache SET hit_count = hit_count + 1
        WHERE cache_key = $1 AND expires_at > now()
        RETURNING response_enc, summary
        """,
        cache_key,
    )
    if row is None:
        return None
    return {
        "response": decrypt(row["response_enc"]),
        "summary": json.loads(row["summary"]) if row["summary"] else None,
    }


async def cache_put(
    *, cache_key: str, provider: str, response: dict, summary: dict | None, ttl_hours: int
) -> None:
    """캐시에 넣는다. 같은 키가 있으면 덮어쓴다(UPSERT).

    response: API 응답 원문. 출발·도착 좌표가 들어 있어 암호화 (테이블정의서 7절).
    summary:  판정에 필요한 숫자만 {duration_sec, distance_m, transfer_count, fare}. 좌표 없음. 평문 jsonb.
    ttl_hours: 경로 24, 지오코딩 720(30일). 값은 호출 쪽(routes.py)이 규칙 파일에서 읽어 넘긴다.
    """
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO route_cache (cache_key, provider, response_enc, summary, expires_at)
        VALUES ($1, $2, $3, $4, now() + ($5 || ' hours')::interval)
        ON CONFLICT (cache_key) DO UPDATE SET
            response_enc = EXCLUDED.response_enc,
            summary      = EXCLUDED.summary,
            expires_at   = EXCLUDED.expires_at,
            hit_count    = 0
        """,
        cache_key, provider, encrypt(response),
        json.dumps(summary) if summary is not None else None, str(ttl_hours),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 8. feedback (테이블정의서 5절)
# ─────────────────────────────────────────────────────────────────────────────
# 사용자가 후보 3개 중 무엇을 골랐나. chosen_rank가 1이 아니면 우리 판정이 틀렸다는 신호라
# 규칙 점검·평가셋 확장에 쓴다. 1순위 채택률(축 ④ 운영 지표)이 여기서 나온다.

async def save_feedback(
    *,
    session_id: str,
    result_id: str,
    chosen_rank: int | None,
    edited_pin_count: int = 0,
    re_ask_count: int = 0,
) -> None:
    """피드백 한 줄 INSERT. FK 없음 — 세션이 지워져도 집계에 남는다 (테이블정의서 6절)."""
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO feedback (session_id, result_id, chosen_rank, edited_pin_count, re_ask_count)
        VALUES ($1, $2, $3, $4, $5)
        """,
        session_id, result_id, chosen_rank, edited_pin_count, re_ask_count,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 9. 청소 (테이블정의서 6절 삭제·보관 정책)
# ─────────────────────────────────────────────────────────────────────────────
# Cloud Scheduler가 하루 1회 POST /internal/cleanup 을 부르고, 그 라우터가 이 함수를 부른다.
# 이 호출이 Supabase 무료 티어의 7일 미사용 정지도 막는다.

async def cleanup_expired() -> dict[str, int]:
    """만료된 행을 지우고 표별 삭제 건수를 돌려준다 (로그·응답에 남기기 위해).

      sessions      expires_at 지남 (약속+30일, 임시 세션은 생성+7일). results는 CASCADE
      route_cache   expires_at 지남 (경로 24시간, 지오코딩 30일)
      request_logs  90일
      feedback      90일
    90일은 테이블정의서 6절 값. 세션 일생과 달리 규칙 파일에 없어 여기 상수로 둔다.
    """
    _LOG_RETAIN_DAYS = 90  # 테이블정의서 6절 request_logs·feedback 보관 기간

    def count(tag: str) -> int:
        return int(tag.split()[-1])  # "DELETE 12" → 12

    pool = await get_pool()
    async with pool.acquire() as conn:
        return {
            "sessions": count(await conn.execute("DELETE FROM sessions WHERE expires_at <= now()")),
            "route_cache": count(await conn.execute("DELETE FROM route_cache WHERE expires_at <= now()")),
            "request_logs": count(await conn.execute(
                "DELETE FROM request_logs WHERE created_at <= now() - ($1 || ' days')::interval", str(_LOG_RETAIN_DAYS))),
            "feedback": count(await conn.execute(
                "DELETE FROM feedback WHERE created_at <= now() - ($1 || ' days')::interval", str(_LOG_RETAIN_DAYS))),
        }
