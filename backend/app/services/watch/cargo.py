"""화물 표(user_cargo) 읽기·쓰기 (docs/specs/memory.md "화물 표 컬럼", 마이그레이션 014·015).

책임: 로그인한 사용자의 화물 한 건 = 한 줄을 코드가 관리한다. LLM은 이 표를 직접 고치지 않는다.
  cargo_key()          화물 지문. 원본 B/L에 BL_ENCRYPTION_KEY에서 파생한 열쇠를 섞은 HMAC (crypto.fingerprint 재사용)
  upsert_assessment()  조회가 끝난 뒤 이번 입력·확정된 배·판정 요약을 적는다. 반출이면 done (Spec 쓰기 흐름 2)
  active_rows()        진행 중 화물 최대 MAX_ACTIVE건. 판정·후속 LLM의 <user_cargo> 블록 재료 (Spec 읽기 흐름 1)
  previous_line()      "지난 조회(10.01)에서는 '주의'였고, 판매 예정일까지 여유가 3일이었어요." 코드가 쓰는 한 줄
  add_pending()        대화에서 나온 화물 값 변경(set_cargo)을 확인 대상으로만 둔다 (Spec 쓰기 흐름 4)
  apply_document_facts() 서류 사진에서 사용자가 확인한 B/L 조건을 적는다
  find_by_container()  컨테이너 번호로 그 사용자의 화물 한 건을 찾는다 (채팅 "(컨테이너 번호) 어디쯤이야?")
  delete_all()         탈퇴·내 기록 삭제 때 화물 표와 신용장 줄을 지운다 (Spec "개인정보")
  stage_date()         이력에서 입항·입고 날짜를 뽑는다 (내 화물 현황 표, 019). 표 읽기·쓰기는 services/watch/cargo_sheet.py

저장 기준 (Spec "저장 기준"): 다시 조회하면 또 나오는 값(선명, 입항일 원본, 통관 이력)은 저장하지 않는다.
B/L 원본은 잠근 값(bl_encrypted, crypto.encrypt)과 가린 값(bl_masked, schemas.customs.mask_bl)으로만 둔다 (SDD 3.5).
UNI-PASS 품명·중량·화주는 받지도 넣지도 않는다 (CLAUDE.md). last_stage는 통관 단계 이름뿐이다.
B/L 조건 세 칸(original_bl, to_order_bank, freight_term + incoterm)은 판정 등급에 쓰지 않는다.

DB 연결은 부르는 쪽이 연다 (with connect() as conn). 여기 함수는 conn만 받아 SQL을 보낸다. 실패는 부르는 쪽이 로그만 남긴다.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from backend.app import crypto
from backend.app.schemas.agent import AgentRequest, AgentResponse
from backend.app.schemas.customs import mask_bl
from backend.app.services.judge import guard
from backend.app.services.judge.evidence import KST
from backend.app.services.llm_config import STAGE_SUSPECT  # 주입 모양 단계명 대신 쓰는 글자 (llm._clean_customs와 같다)
from backend.app.services.judge.rules import stage_key
from backend.app.services.judge.verdict import VERDICT_LABEL

# 판정에 넣는 진행 중 화물 상한 (Spec "보관과 크기" 상한 설정값 30건). 부르는 쪽이 limit으로 바꿀 수 있다
MAX_ACTIVE = 30
# 이름표 글자 수 상한. Spec에 숫자가 없어 화면 한 줄에 들어가는 길이로 정했다 (memory.md 결정 기록)
LABEL_MAX = 20
# 대화로 바꿀 수 있는 화물 칸 (Spec 쓰기 흐름 4 set_cargo). 판정은 이번 입력으로만 한다
PENDING_FIELDS = ("sale_due_date", "forwarder_eta", "label")

COLUMNS = (
    "cargo_key", "bl_masked", "bl_type", "label", "status", "sale_due_date", "sale_due_asked",
    "forwarder_eta", "forwarder_eta_noted_at", "vessel_mmsi", "voyage_no", "vessel_source",
    "last_verdict", "last_checked_at", "last_days_margin", "last_eta", "last_stage", "done_at",
    "original_bl", "to_order_bank", "freight_term", "incoterm", "pending", "goods_name",
)


def cargo_key(bl_no: str) -> str | None:
    """화물 지문. 가린 번호가 겹치는 두 화물도 정확히 가른다 (Spec EC-05).

    열쇠는 BL_ENCRYPTION_KEY에서 용도 이름을 붙여 파생한다 (crypto.fingerprint). 원본으로 되돌릴 수 없다.
    열쇠가 없으면 None이고, 부르는 쪽은 화물 표를 만들지도 읽지도 않는다 (채점용 환경처럼).
    """
    return crypto.fingerprint(bl_no.strip().upper(), crypto.BL_KEY_ENV)


def _row(values) -> dict:
    """SELECT 결과 한 줄을 칸 이름 dict로."""
    return dict(zip(COLUMNS, values))


def get_row(conn, user_id: str, key: str) -> dict | None:
    """화물 한 건. 끝난 화물도 돌려준다. 없으면 None."""
    found = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM user_cargo WHERE user_id = %s AND cargo_key = %s",
                         [user_id, key]).fetchone()
    return _row(found) if found else None


def find_by_container(conn, user_id: str, container: str) -> dict | None:
    """그 사용자의 화물 중 container_no에 이 컨테이너 번호가 들어 있는 한 건. 없으면 None.

    container_no는 UNI-PASS 값 그대로라 한 칸에 번호 하나("ABCU1234560") 또는 여럿을 ", "로 이어 붙인 글이다 (019).
    "ABCU123456" 같은 앞부분이 다른 번호 안에 걸려 잘못 찾지 않게, SQL은 후보만 좁히고(ILIKE) 코드가 ", "로 나눈
    항목 하나와 통째로 같은지(대소문자 무시) 다시 본다. 진행 중 화물을 먼저, 그다음 최근 조회 순으로 첫 줄을 쓴다.
    돌려주는 dict는 COLUMNS 칸에 container_no와 bl_encrypted(잠근 원본 B/L)를 더한 것이다.
    bl_encrypted는 채팅이 B/L을 열어 기존 B/L 흐름에 넘기려는 용도뿐이다. 화면 응답이나 LLM에는 주지 않는다 (SDD 3.5).
    """
    want = container.strip().upper()
    if not want:
        return None
    rows = conn.execute(
        f"""SELECT {', '.join(COLUMNS)}, container_no, bl_encrypted FROM user_cargo
            WHERE user_id = %s AND container_no ILIKE %s
            ORDER BY status = 'done', last_checked_at DESC NULLS LAST, updated_at DESC""",
        [user_id, f"%{want}%"],
    ).fetchall()
    for values in rows:
        row = dict(zip((*COLUMNS, "container_no", "bl_encrypted"), values))
        items = [item.strip().upper() for item in (row["container_no"] or "").split(",")]
        if want in items:
            return row
    return None


def active_rows(conn, user_id: str, limit: int = MAX_ACTIVE) -> list[dict]:
    """진행 중 화물을 최근 조회 순으로 최대 limit건. 판정·후속 LLM의 <user_cargo> 재료다 (Spec 읽기 흐름 1).
    줄이는 기준은 상태와 날짜뿐이다. 질문 내용으로 고르지 않는다 (Spec "RAG 판정" 규칙 2)."""
    rows = conn.execute(
        f"""SELECT {', '.join(COLUMNS)} FROM user_cargo WHERE user_id = %s AND status = 'active'
            ORDER BY last_checked_at DESC NULLS LAST, updated_at DESC LIMIT %s""",
        [user_id, limit],
    ).fetchall()
    return [_row(r) for r in rows]


def all_rows(conn, user_id: str, limit: int = 100) -> list[dict]:
    """GET /api/memory 화면용. 진행 중 먼저, 그다음 끝난 화물."""
    rows = conn.execute(
        f"""SELECT {', '.join(COLUMNS)} FROM user_cargo WHERE user_id = %s
            ORDER BY status = 'done', last_checked_at DESC NULLS LAST, updated_at DESC LIMIT %s""",
        [user_id, limit],
    ).fetchall()
    return [_row(r) for r in rows]


def found_cargo(response: AgentResponse) -> bool:
    """화물 표에 줄을 만들 만한 조회인가. 세관에 없는 번호(오타일 수 있다), 통관 조회 실패, 부산 밖 화물은 만들지 않는다."""
    if response.status in ("failed", "unsupported"):
        return False
    # bl_not_found: 구분을 말하지 않아 하우스·마스터를 둘 다 본 조회가 둘 다 없음 (services/chat/chat.NOT_FOUND_BOTH)
    return not (response.status == "insufficient" and ("bl_type" in response.missing_inputs or "bl_not_found" in response.missing_inputs))


def clean_stage(name: str | None) -> str | None:
    """통관 단계 이름(UNI-PASS 외부 글자)이 주입 모양이면 STAGE_SUSPECT로 바꾼다.
    판정 LLM 입력에서 llm._clean_customs가 하는 것과 같은 기준이다. 화물 표에 저장할 때와 <user_cargo>에 넣을 때 둘 다 건다
    (SDD 7절 신뢰 경계, 검증 지적: 저장한 단계명이 기억 블록으로 그 길을 다시 열면 안 된다)."""
    return STAGE_SUSPECT if guard.looks_like_injection(name) else name


def _vessel(request: AgentRequest, response: AgentResponse) -> tuple[int | None, str | None]:
    """확정된 배와 확정 방법 (Spec 화물 표 vessel_source: mrn / user).

    - 사용자가 되묻기에서 고른 배, 또는 사용자가 준 항차·포워더 입항일로 고른 배: user
    - MRN 입항 신고의 호출부호로 코드가 확정한 배: mrn (routers/agent._identify 후보 이유 문구)
    이름만으로 1척 찾은 경우는 두 방법 어느 것도 아니라 적지 않는다. 덜 적는 쪽이 틀린 배를 기억하는 것보다 낫다.
    """
    if request.resolved_mmsi:
        return request.resolved_mmsi, "user"
    if response.vessel_match != "confirmed" or not response.vessel_candidates:
        return None, None
    first = response.vessel_candidates[0]
    if any("MRN" in reason for reason in first.match_reasons):
        return first.mmsi, "mrn"
    if request.voyage_no or request.forwarder_eta:
        return first.mmsi, "user"
    return None, None


# 내 화물 현황 표의 입항·입고 날짜를 뽑는 UNI-PASS 이력 단계 (019 마이그레이션, 아버지 관리표 기준).
# 이름은 skills/customs-stages/rules.md customs_stages의 name 그대로다. 띄어쓰기는 rules.stage_key로 무시한다
ARRIVED_STAGE = "입항보고 수리"  # 실제 입항 신고된 날 (예정일 etprDt가 아니다)
WAREHOUSED_STAGE = "반입신고"  # 화물이 터미널·보세창고에 들어간 날


def stage_date(history: list[dict], stage: str) -> date | None:
    """이력에서 그 단계가 처음 처리된 날짜. 없으면 None (아직 그 단계 전).

    UNI-PASS 처리일시(prcsDttm)는 시간대 없이 한국 시각으로 온다(services/judge/customs._dt). 그래서 시간대가 없으면
    그 날짜를 그대로 쓰고, 시간대가 있으면 한국 날짜로 바꾼다. _kst_date처럼 UTC로 보면 하루가 밀릴 수 있다.
    """
    want = stage_key(stage)
    days = []
    for item in history or []:
        if stage_key(item.get("name") or "") != want or not item.get("at"):
            continue
        try:
            moment = datetime.fromisoformat(str(item["at"]))
        except ValueError:
            continue
        days.append(moment.date() if moment.tzinfo is None else moment.astimezone(KST).date())
    return min(days) if days else None


def _kst_date(moment: datetime | None) -> date | None:
    """시각을 한국 날짜로. 근거 카드와 같은 기준이다 (services/judge/evidence.KST)."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KST).date()


# 서류 사진에서 읽은 출항일을 화물 줄에 적는 SQL 조각. upsert_assessment의 DO UPDATE SET 안에 들어간다.
# 규칙: 사용자가 직접 적은 날짜(departed_source = 'manual')는 절대 덮지 않는다. 서류 값끼리는 새 값이 옛 값을 바꾼다.
# 이번 조회에 서류 출항일이 없으면(EXCLUDED가 NULL) 저장된 값을 그대로 둔다. 날짜와 출처는 항상 같은 쪽 값을 같이 고른다
# (둘이 어긋나면 표가 "직접 입력한 날짜"로 잘못 보인다). 테스트가 이 조각을 그대로 SQLite에 돌려 규칙을 확인한다
DEPARTED_UPSERT_SQL = """departed_on = CASE WHEN user_cargo.departed_source = 'manual' THEN user_cargo.departed_on
                                ELSE COALESCE(EXCLUDED.departed_on, user_cargo.departed_on) END,
              departed_source = CASE WHEN user_cargo.departed_source = 'manual' THEN user_cargo.departed_source
                                     ELSE COALESCE(EXCLUDED.departed_source, user_cargo.departed_source) END"""


def upsert_assessment(conn, user_id: str, request: AgentRequest, response: AgentResponse, *, released: bool,
                      now: datetime | None = None) -> bool:
    """조회 한 번이 끝난 뒤 화물 표 한 줄을 쓴다 (Spec 쓰기 흐름 2). 썼으면 True.

    - 이번 입력이 저장 값보다 우선한다 (Spec EC-02). 판매일·포워더 입항일은 이번에 들어왔을 때만 덮고, 안 들어왔으면 둔다
    - 이번 입력으로 받은 칸의 확인 대기(pending)는 지운다. 사용자가 직접 넣은 값이 확인이다
    - 마지막 판정 요약(last_*)은 조회마다 덮어쓴다. "지난번엔 ○○" 줄은 덮기 전에 읽은 값으로 만든다 (previous_line)
    - released(통관 단계가 반출신고, routers/agent.RELEASED_STAGE)면 done. 완료 시각은 처음 done이 된 때를 지킨다
    """
    key = cargo_key(request.bl_no)
    if not key or not found_cargo(response):
        return False
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(KST).date()
    mmsi, source = _vessel(request, response)
    customs = response.customs
    confirmed = response.vessel if response.vessel_match == "confirmed" else None
    entered =[f for f in ("sale_due_date", "forwarder_eta") if getattr(request, f)]
    values = {
        "user_id": user_id, "cargo_key": key, "bl_masked": mask_bl(request.bl_no),
        "bl_encrypted": crypto.encrypt(request.bl_no), "bl_type": request.bl_type,
        "status": "done" if released else "active",
        "sale_due_date": request.sale_due_date,
        "forwarder_eta": request.forwarder_eta, "forwarder_eta_noted_at": today if request.forwarder_eta else None,
        "vessel_mmsi": mmsi, "voyage_no": request.voyage_no, "vessel_source": source,
        "last_verdict": response.verdict, "last_checked_at": now, "last_days_margin": response.days_margin,
        "last_eta": _kst_date(response.eta.trusted_eta) if response.eta else None,
        "last_stage": clean_stage(response.customs.stage_name) if response.customs else None,
        "done_at": now if released else None,
        # 내 화물 현황 표 (019). 날짜는 실제 신고된 날만, 회사 이름·컨테이너는 UNI-PASS 값 그대로. 이번에 없으면 저장 값을 둔다
        "arrived_on": stage_date(customs.history, ARRIVED_STAGE) if customs else None,
        "warehoused_on": stage_date(customs.history, WAREHOUSED_STAGE) if customs else None,
        "forwarder_name": customs.forwarder_name if customs else None,
        "carrier_name": customs.carrier_name if customs else None,
        "container_no": customs.container_no if customs else None,
        # 품명 (020). 외부 글자라 주입 모양이면 저장하지 않는다: <user_cargo> 블록으로 LLM에 다시 간다
        "goods_name": (None if guard.looks_like_injection(customs.goods_name) else customs.goods_name) if customs else None,
        # 선명·국적 (021, 감시 목록 한 줄). 배가 확정된 조회에서만 적는다: 되묻기 중인 후보 이름을 내 화물의 배로 남기지 않는다
        "vessel_name": confirmed.name if confirmed else None,
        "vessel_flag": confirmed.flag if confirmed else None,
        # 출항일 (019). 서류 사진에서 사용자가 확인한 값이 요청에 실려 왔을 때만 적는다. 출처는 늘 'document'.
        # 판정에는 쓰지 않는다(요청에서 여기로만 온다). manual을 지키는 규칙은 DEPARTED_UPSERT_SQL
        "departed_on": request.departed_on,
        "departed_source": "document" if request.departed_on else None,
    }
    names = list(values)
    conn.execute(
        f"""INSERT INTO user_cargo ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))})
            ON CONFLICT (user_id, cargo_key) DO UPDATE SET
              bl_masked = EXCLUDED.bl_masked,
              bl_encrypted = COALESCE(EXCLUDED.bl_encrypted, user_cargo.bl_encrypted),
              bl_type = EXCLUDED.bl_type,
              status = EXCLUDED.status,
              sale_due_date = COALESCE(EXCLUDED.sale_due_date, user_cargo.sale_due_date),
              forwarder_eta = COALESCE(EXCLUDED.forwarder_eta, user_cargo.forwarder_eta),
              forwarder_eta_noted_at = COALESCE(EXCLUDED.forwarder_eta_noted_at, user_cargo.forwarder_eta_noted_at),
              vessel_mmsi = COALESCE(EXCLUDED.vessel_mmsi, user_cargo.vessel_mmsi),
              voyage_no = COALESCE(EXCLUDED.voyage_no, user_cargo.voyage_no),
              vessel_source = COALESCE(EXCLUDED.vessel_source, user_cargo.vessel_source),
              last_verdict = EXCLUDED.last_verdict,
              last_checked_at = EXCLUDED.last_checked_at,
              last_days_margin = EXCLUDED.last_days_margin,
              last_eta = EXCLUDED.last_eta,
              last_stage = EXCLUDED.last_stage,
              done_at = CASE WHEN EXCLUDED.status = 'done' THEN COALESCE(user_cargo.done_at, EXCLUDED.done_at) END,
              arrived_on = COALESCE(EXCLUDED.arrived_on, user_cargo.arrived_on),
              warehoused_on = COALESCE(EXCLUDED.warehoused_on, user_cargo.warehoused_on),
              forwarder_name = COALESCE(EXCLUDED.forwarder_name, user_cargo.forwarder_name),
              carrier_name = COALESCE(EXCLUDED.carrier_name, user_cargo.carrier_name),
              container_no = COALESCE(EXCLUDED.container_no, user_cargo.container_no),
              goods_name = COALESCE(EXCLUDED.goods_name, user_cargo.goods_name),
              vessel_name = COALESCE(EXCLUDED.vessel_name, user_cargo.vessel_name),
              vessel_flag = COALESCE(EXCLUDED.vessel_flag, user_cargo.vessel_flag),
              {DEPARTED_UPSERT_SQL},
              pending = COALESCE((SELECT jsonb_agg(p) FROM jsonb_array_elements(user_cargo.pending) p
                                  WHERE NOT (p->>'field' = ANY(%s::text[]))), '[]'::jsonb),
              updated_at = now()""",
        [*values.values(), entered],
    )
    _keep_position(conn, mmsi, response)
    return True


def _keep_position(conn, mmsi: int | None, response: AgentResponse) -> None:
    """이번 조회에서 받은 배 위치를 감시·지도 위치 이력(watch_positions, 017)에 한 점 쌓는다 (감시 목록).

    왜: 그 테이블은 원래 worker가 6시간마다 채우는데 스케줄러가 꺼져 있어(ShipFinder 호출 한도) 비어 있다.
    조회·재판정은 어차피 위치를 받으므로 그 값을 버리지 않고 남기면, 수집 없이도 감시 목록 지도에 마지막 위치와
    지나온 길(조회할 때마다 한 점)이 생긴다. 같은 보고 시각은 한 줄만 남는다(UNIQUE (mmsi, ts), worker/collector.py와 같다).
    배가 확정돼 화물 표에 배 번호를 적은 경우(mmsi)만 쌓는다. 위치가 없으면 아무것도 하지 않는다."""
    pos = response.position
    if not mmsi or pos is None:
        return
    conn.execute(
        """INSERT INTO watch_positions (mmsi, ts, fetched_at, lat, lng, sog, cog, navistat)
           VALUES (%s, %s, now(), %s, %s, %s, %s, %s) ON CONFLICT (mmsi, ts) DO NOTHING""",
        [mmsi, pos.last_time, pos.lat, pos.lng, pos.sog, pos.cog, pos.navistat],
    )


def add_pending(conn, user_id: str, key: str, changes: list[dict]) -> int:
    """확인 대기 값을 더한다 (Spec 쓰기 흐름 4: set_cargo는 바로 적용하지 않는다). 같은 칸은 새 값으로 바꾼다.
    읽고 고쳐 쓰지 않고 UPDATE 한 문장으로 한다. 두 요청이 같이 고쳐도 한쪽 값이 사라지지 않는다 (EC-04와 같은 이유).
    화물 줄이 없으면 아무것도 하지 않는다. 더한 개수를 돌려준다."""
    if not changes:
        return 0
    fields = [c["field"] for c in changes]
    cur = conn.execute(
        """UPDATE user_cargo SET
             pending = COALESCE((SELECT jsonb_agg(p) FROM jsonb_array_elements(user_cargo.pending) p
                                 WHERE NOT (p->>'field' = ANY(%s::text[]))), '[]'::jsonb) || %s::jsonb,
             updated_at = now()
           WHERE user_id = %s AND cargo_key = %s""",
        [fields, json.dumps(changes, ensure_ascii=False), user_id, key])
    return len(changes) if cur.rowcount else 0


def apply_document_facts(conn, user_id: str, bl_no: str, bl_type: str, facts: dict) -> str | None:
    """서류 사진에서 사용자가 확인한 B/L 조건을 화물 줄에 적는다. 화물 지문을 돌려준다(열쇠 없으면 None).

    facts: original_bl, to_order_bank, freight_term, incoterm. None인 칸은 "모름"이라 기존 값을 지우지 않는다.
    줄이 없으면 만든다(아직 조회 전인 화물). 이때 마지막 판정 칸은 비어 있다.
    허용 값 검사는 계약(schemas/memory.py)이 이미 했다. DB CHECK(마이그레이션 015)가 한 번 더 막는다.
    """
    key = cargo_key(bl_no)
    if not key:
        return None
    cols = ("original_bl", "to_order_bank", "freight_term", "incoterm")
    values = [facts.get(c) for c in cols]
    conn.execute(
        f"""INSERT INTO user_cargo (user_id, cargo_key, bl_masked, bl_encrypted, bl_type, {', '.join(cols)})
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, cargo_key) DO UPDATE SET
              {', '.join(f'{c} = COALESCE(EXCLUDED.{c}, user_cargo.{c})' for c in cols)},
              bl_encrypted = COALESCE(user_cargo.bl_encrypted, EXCLUDED.bl_encrypted),
              updated_at = now()""",
        [user_id, key, mask_bl(bl_no), crypto.encrypt(bl_no), bl_type, *values],
    )
    return key


def delete_all(conn, user_id: str) -> int:
    """그 사용자의 화물 표 줄과 신용장(user_lc)을 전부 지운다 (탈퇴·내 기록 삭제, Spec "개인정보"). 지운 화물 줄 수.
    신용장 번호도 사용자가 넣은 거래 정보라 같이 지운다 (019). 화물 줄을 먼저 지워 신용장이 가리키는 줄이 없게 한다.
    신용장 줄 수는 세지 않는다. 알리는 숫자는 지금처럼 화물 줄 수다 (응답 모양을 바꾸지 않는다)."""
    rows = conn.execute("DELETE FROM user_cargo WHERE user_id = %s", [user_id]).rowcount
    conn.execute("DELETE FROM user_lc WHERE user_id = %s", [user_id])
    return rows


# ── 글로 옮기기 (코드가 쓴다. LLM은 쓰지 않는다) ──

def _md(value: date | datetime | None) -> str | None:
    """날짜를 "10.01" 모양으로. 시각이면 한국 날짜로 바꾼다."""
    if value is None:
        return None
    day = _kst_date(value) if isinstance(value, datetime) else value
    return f"{day.month:02d}.{day.day:02d}"


def margin_text(margin: int | None) -> str | None:
    """여유 일수를 사람 말로. 음수는 판매 예정일보다 늦는다는 뜻이다 (marvia-judge 프롬프트 days_margin 설명과 같다)."""
    if margin is None:
        return None
    return f"여유 {margin}일" if margin >= 0 else f"판매 예정일보다 {abs(margin)}일 늦음"


# 등급 이름 뒤 "이었/였" (받침 있으면 이었, 없으면 였). 순항·긴급은 받침, 주의는 받침 없음 (검증: "지금 조치이었어요", 이름을 바꿔 다시 맞춤)
_PAST = {"fine": "이었", "watch": "였", "act": "이었"}


def previous_line(row: dict | None) -> str | None:
    """덮어쓰기 전 화물 줄로 지난 조회 한 줄을 만든다. LLM을 부르지 않는다.
    예: "지난 조회(10.01)에서는 '주의'였고, 판매 예정일까지 여유가 3일이었어요."
        "지난 조회(10.01)에서는 '긴급'이었고, 판매 예정일보다 2일 늦게 도착할 예정이었어요."
        "지난 조회(10.01)에서는 '순항'이었어요." (여유 일수 없음)
    지난 판정이 없으면(처음 조회, 판정 보류) None."""
    if not row or not row.get("last_verdict") or not row.get("last_checked_at"):
        return None
    verdict = row["last_verdict"]
    head = f"지난 조회({_md(row['last_checked_at'])})에서는 '{VERDICT_LABEL.get(verdict, verdict)}'{_PAST.get(verdict, '이었')}"
    margin = row.get("last_days_margin")
    if margin is None:
        return f"{head}어요."
    if margin >= 0:
        return f"{head}고, 판매 예정일까지 여유가 {margin}일이었어요."
    return f"{head}고, 판매 예정일보다 {abs(margin)}일 늦게 도착할 예정이었어요."


CONDITION_TEXT = {
    "original_bl": {"required": "원본 B/L 필요", "surrendered": "서렌더(원본 B/L 불필요)"},
    "freight_term": {"prepaid": "운임 선불", "collect": "운임 착불"},
}


def conditions_text(row: dict) -> list[str]:
    """B/L 조건 세 칸을 사람 말로. 모르는 칸은 말하지 않는다 (Spec EC-12)."""
    out = []
    if row.get("original_bl"):
        out.append(CONDITION_TEXT["original_bl"][row["original_bl"]])
    if row.get("to_order_bank") is not None:
        out.append("수하인 은행 지시식" if row["to_order_bank"] else "수하인 은행 지시식 아님")
    if row.get("freight_term"):
        term = CONDITION_TEXT["freight_term"][row["freight_term"]]
        out.append(f"{term} ({row['incoterm']})" if row.get("incoterm") else term)
    elif row.get("incoterm"):
        out.append(row["incoterm"])
    return out


def cargo_line(row: dict) -> str:
    """<user_cargo> 블록의 한 줄. 가린 번호만 쓴다. 내부 번호(id)는 넣지 않는다 (Spec "번호를 보여 주는 LLM은 기억 뽑기 하나뿐")."""
    name = f"{row['label']} ({row['bl_masked']})" if row.get("label") else row["bl_masked"]
    parts = [name, "하우스 B/L" if row.get("bl_type") == "HOUSE" else "마스터 B/L"]
    if row.get("goods_name"):
        # 세관 품명 (020). "고추 화물 어디야?"처럼 품명으로 물을 때 어느 줄인지 LLM이 알게. 저장할 때 주입 모양은 걸렀다
        parts.append(f"품명 {row['goods_name']}")
    if row.get("sale_due_date"):
        parts.append(f"받아야 하는 날 {row['sale_due_date'].isoformat()}")
    if row.get("forwarder_eta"):
        heard = f", {_md(row['forwarder_eta_noted_at'])}에 들음" if row.get("forwarder_eta_noted_at") else ""
        parts.append(f"포워더가 알려 준 입항일 {row['forwarder_eta'].isoformat()}{heard}")
    parts += conditions_text(row)
    if row.get("last_checked_at"):
        last = [VERDICT_LABEL.get(row["last_verdict"], "판정 없음") if row.get("last_verdict") else "판정 없음"]
        if margin_text(row.get("last_days_margin")):
            last.append(margin_text(row["last_days_margin"]))
        if row.get("last_eta"):
            last.append(f"도착 예정 {row['last_eta'].isoformat()}")
        if row.get("last_stage"):
            last.append(f"통관 {clean_stage(row['last_stage'])}")  # 저장 전 값일 수도 있어 넣을 때 한 번 더 거른다
        parts.append(f"지난 조회 {_md(row['last_checked_at'])}: {', '.join(last)}")
    return "- " + " · ".join(parts)


def render_block(rows: list[dict]) -> str:
    """판정·후속 LLM에 넣는 화물 표 블록 본문. 비었으면 빈 글자."""
    return "\n".join(cargo_line(r) for r in rows)


def done_summary(row: dict) -> str:
    """끝난 화물 한 줄 요약 ("09.22 고추 반출 완료"). 코드가 판정 기록으로 만든다 (Spec "보관과 크기").
    끝난 화물 줄은 반출 후 3년 뒤 통째로 지워진다 (마이그레이션 015 purge_done_cargo)."""
    name = row.get("label") or row["bl_masked"]
    day = _md(row.get("done_at")) or _md(row.get("last_checked_at")) or ""
    return f"{day} {name} 반출 완료".strip()
