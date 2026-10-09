"""화물 지켜보기: 등록·감시·알림의 업무 규칙 (G5, docs/Marvia_개발_작업_리스트.md "G5 등록·감시·알림").

하는 일:
  set_watch()        결과 화면의 "지켜보기" 켜기·끄기. 사용자당 최대 MAX_WATCH건
  watch_state()      그 화물이 저장됐는지, 지켜보는 중인지 (버튼 상태)
  pending_changes()  아직 안 본 판정 변화 목록 ("다음 접속 때 표시" 띠)
  mark_seen()        화면에 보여 줬으니 "봤음"으로 바꾸기
  run_watch()        지켜보는 화물을 다시 판정하고, 등급이 바뀌었으면 기록하고 카카오톡으로 알린다 (워커가 부른다)
HTTP는 라우터(routers/watch.py)가, 주기 실행은 worker/watch.py·worker/run.py가 맡는다. 여기는 DB와 규칙만 안다.
표는 새로 만들지 않고 화물 표(user_cargo)에 칸 네 개를 더했다 (마이그레이션 017).

왜 이렇게 했나:
- 사용자가 직접 켠 화물만 본다: 조회한 화물을 전부 감시하면 ShipFinder 하루 한도(50회)와 LLM 비용이 사용자 모르게 나간다.
  그래서 최대 5건으로 제한한다
- 다시 판정은 사용자가 조회할 때와 같은 길(routers/agent._assess, LLM 포함)로 한다: 감시가 따로 만든 판정 규칙이 있으면
  "조회 화면에서는 순항인데 알림은 긴급"처럼 두 답이 어긋난다. 저장된 값으로 같은 AgentRequest를 만들어 그대로 부른다
- 한 번에 5건만: ShipFinder 호출을 아끼려는 상한이다. 마지막 확인이 가장 오래된 화물부터 돌려서 한 화물만 계속 도는 일이 없다
- 조회 기록(query_log)은 남기지 않는다: 사용자가 한 조회가 아니라서 "내 조회 기록" 화면과 90일 보관 대상에 섞이면 안 된다.
  그 대신 화물 표의 마지막 판정(last_*)은 갱신한다. 다음 번 비교의 기준이 그 값이다
- 판정이 없는 결과(되묻기·일시 실패, verdict 없음)는 화물 표를 덮지 않는다: 덮으면 기준 등급이 사라져서 다음에 진짜로
  바뀌어도 "이전 등급이 없음"이라 변화를 못 잡는다
- 연결 안 된 사용자(not_linked)는 조용히 넘어간다: 카카오톡은 선택 기능이다. 안 쓰는 사람에게 오류를 남기면 로그만 시끄럽다.
  알림을 못 보내도 변화 기록은 이미 화물 표에 있어서 다음 접속 때 화면 띠로 보인다
- 화물 한 건이 실패해도 나머지는 계속한다: 한 건 때문에 다른 사람의 알림이 막히면 안 된다

B/L 원문은 메시지·로그·반환값 어디에도 넣지 않는다. 가린 번호나 이름표만 쓴다. 로그에는 오류 종류만 남긴다 (log_failure 규칙).
DB 연결은 부르는 쪽이 연다. 여기 함수는 conn만 받아 SQL을 보낸다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.app import crypto
from backend.app.clients.kakao import KakaoError
from backend.app.observability.langfuse import session_scope
from backend.app.observability.logging import log_failure
from backend.app.schemas.agent import AgentRequest
from backend.app.services.watch import cargo
from backend.app.services.watch import kakao
from backend.app.services.account import quota
from backend.app.services.watch.kakao import KakaoLinkError
from backend.app.services.judge.verdict import VERDICT_LABEL

MAX_WATCH = 5      # 사용자당 지켜볼 수 있는 화물 수
RUN_LIMIT = 5      # 워커 한 번에 다시 판정하는 화물 수. ShipFinder 하루 한도 50회를 지키려는 상한이다
# 배(vessel_mmsi)를 아는 화물 한 건을 다시 판정할 때 ShipFinder를 부르는 횟수 (routers/agent.py에서 확인).
# resolved_mmsi가 있으면 _identify가 후보 검색을 건너뛰고(확정), _after_customs가 get_live_position 한 번만 부른다.
# 규칙이 아니라 코드 경로를 센 값이라 rules.md가 아니라 여기 둔다. 판정 경로가 ShipFinder를 더 부르게 바뀌면 같이 고친다.
# 배를 모르는 화물은 후보 검색(검색 1 + 후보 5척 x 위치·국적 = 최대 11회, mcp_server/tools/vessel_candidates.py)이라
# 워커가 예산 안에서 돌릴 때는 아예 다시 판정하지 않는다 (run_watch known_vessel_only)
SHIPFINDER_CALLS_PER_KNOWN_VESSEL = 1


class WatchError(Exception):
    """우리 쪽 규칙 때문에 못 했다. kind: not_saved(화물 줄이 아직 없음) / done(반출이 끝난 화물)
    / limit(이미 MAX_WATCH건) / no_key(B/L 지문 열쇠 없음) / quota(그 사용자가 오늘 LLM 토큰 한도를 다 씀)."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


# ── 켜기·끄기·상태 ──

def _find(conn, user_id: str, key: str) -> tuple[str, bool] | None:
    """화물 줄의 (status, watch). 줄이 없으면 None."""
    row = conn.execute("SELECT status, watch FROM user_cargo WHERE user_id = %s AND cargo_key = %s",
                       [user_id, key]).fetchone()
    return (row[0], bool(row[1])) if row else None


def set_watch(conn, user_id: str, bl_no: str, on: bool) -> bool:
    """지켜보기를 켜거나 끈다. 바뀐 뒤 상태(on)를 돌려준다. 못 하면 WatchError.

    끄기는 늘 된다: 줄이 없거나 이미 꺼져 있어도 오류가 아니다 (사용자가 원하는 상태가 이미 그렇다).
    켜기는 화물 줄이 있어야 한다. 줄은 조회가 끝난 뒤 뒤에서 쓰므로(services/account/memory.remember_later) 조회 직후에는
    아직 없을 수 있다. 그때는 not_saved로 알려 사용자가 잠시 뒤 다시 누르게 한다 (여기서 줄을 만들지 않는다).
    """
    key = cargo.cargo_key(bl_no)
    if not on:
        if key:
            conn.execute("UPDATE user_cargo SET watch = false, updated_at = now() WHERE user_id = %s AND cargo_key = %s",
                         [user_id, key])
        return False
    if not key:
        raise WatchError("no_key")
    found = _find(conn, user_id, key)
    if found is None:
        raise WatchError("not_saved")
    status, watching = found
    if status == "done":
        raise WatchError("done")
    if not watching:  # 이미 켜져 있으면 한도를 다시 세지 않는다
        count = conn.execute("SELECT count(*) FROM user_cargo WHERE user_id = %s AND watch AND status = 'active'",
                             [user_id]).fetchone()[0]
        if count >= MAX_WATCH:
            raise WatchError("limit")
        conn.execute("UPDATE user_cargo SET watch = true, updated_at = now() WHERE user_id = %s AND cargo_key = %s",
                     [user_id, key])
    return True


def watch_state(conn, user_id: str, bl_no: str) -> dict:
    """결과 화면 버튼용. saved: 화물 줄이 있나, watch: 지금 지켜보는 중인가.
    반출이 끝난 화물은 더 볼 게 없어 watch를 false로 말한다 (워커도 active만 본다)."""
    key = cargo.cargo_key(bl_no)
    found = _find(conn, user_id, key) if key else None
    if found is None:
        return {"saved": False, "watch": False}
    status, watching = found
    return {"saved": True, "watch": watching and status == "active"}


# ── 바뀐 판정 띠 ──

# 감시 목록 지도에 잇는 지나온 길 점 수. worker 수집 간격 6시간이면 3일치다. 화면이 그리기 무겁지 않을 만큼만
TRACK_POINTS = 12


def watch_list(conn, user_id: str) -> dict:
    """지켜보는 화물 목록과 배의 마지막 위치·지나온 길 (GET /api/watch). 화면 web/lib/api.ts WatchItem 모양이다.

    - 줄 재료는 화물 표(user_cargo)의 마지막 조회 값이다: 등급·통관 단계·도착 예정·여유 일수·품명·선명·국적
    - 위치는 watch_positions(017)에서 그 배의 최근 TRACK_POINTS개를 오래된 순으로. 마지막 점이 현재 위치다
      (worker 수집 또는 조회할 때 쌓인 점, services/watch/cargo._keep_position). 점이 없으면 위치 칸은 null이고 화면은 지도에 안 그린다
    - B/L은 가린 번호만, 화물을 가리키는 값은 지문(cargo_key)만 준다. 반출 끝난 화물(done)도 목록 뒤에 남는다(화면이 개수만 알린다)
    - updated_at: 줄들 중 가장 최근 조회 시각. 없으면 null"""
    rows = conn.execute(
        """SELECT cargo_key, bl_masked, label, goods_name, vessel_name, vessel_flag, vessel_mmsi, status,
                  last_verdict, last_stage, last_eta, last_days_margin, last_checked_at
           FROM user_cargo WHERE user_id = %s AND watch
           ORDER BY status = 'done', last_checked_at DESC NULLS LAST""",
        [user_id],
    ).fetchall()
    items = []
    for (key, masked, label, goods, ship, flag, mmsi, status,
         verdict, stage, eta, margin, checked) in rows:
        track = _track(conn, mmsi) if mmsi else []
        last = track[-1] if track else None
        items.append({
            "cargo_key": key, "bl_masked": masked, "label": label, "goods_name": goods,
            "ship_name": ship, "ship_flag": flag, "status": status, "verdict": verdict,
            "stage": cargo.clean_stage(stage) if stage else None,
            "eta": eta.isoformat() if eta else None, "days_margin": margin,
            "lat": last["lat"] if last else None, "lng": last["lng"] if last else None,
            "cog": last["cog"] if last else None, "sog": last["sog"] if last else None,
            "position_at": last["at"] if last else None, "track": track,
        })
    checked_at = [r[12] for r in rows if r[12]]
    return {"items": items, "updated_at": max(checked_at).isoformat() if checked_at else None, "sample": False}


def _track(conn, mmsi: int) -> list[dict]:
    """그 배의 최근 위치 TRACK_POINTS개를 오래된 순으로. 최신부터 잘라 온 뒤 뒤집는다."""
    found = conn.execute(
        "SELECT ts, lat, lng, sog, cog FROM watch_positions WHERE mmsi = %s ORDER BY ts DESC LIMIT %s",
        [mmsi, TRACK_POINTS],
    ).fetchall()
    return [{"at": ts.isoformat(), "lat": lat, "lng": lng, "sog": sog, "cog": cog} for ts, lat, lng, sog, cog in reversed(found)]


def pending_changes(conn, user_id: str) -> list[dict]:
    """사용자가 아직 못 본 판정 변화. 최근 것부터. 가린 번호만 담는다.
    to_verdict는 화물 표의 마지막 판정(last_verdict)이다.
    reason: 마지막 확인 때의 여유 일수·통관 단계를 코드가 한 줄로 쓴 것 (접속하면 먼저 말 걸기용). 판정이 왜 바뀌었는지의 원인이
    아니라 그 시점의 상태다: 화물 표에는 원인을 따로 저장하지 않는다. 둘 다 없으면 None."""
    rows = conn.execute(
        """SELECT bl_masked, label, changed_from, last_verdict, changed_at, last_days_margin, last_stage FROM user_cargo
           WHERE user_id = %s AND change_seen = false ORDER BY changed_at DESC NULLS LAST""",
        [user_id],
    ).fetchall()
    return [{"bl_masked": r[0], "label": r[1], "from_verdict": r[2], "to_verdict": r[3],
             "changed_at": r[4].isoformat() if r[4] else None, "reason": _change_reason(r[5], r[6])} for r in rows]


def _change_reason(margin: int | None, stage: str | None) -> str | None:
    """마지막 확인 기준 여유 일수·통관 단계를 사람 말 한 줄로. 있는 것만 쓴다 (없는 이유를 지어내지 않는다)."""
    parts = [p for p in (cargo.margin_text(margin), f"통관 {cargo.clean_stage(stage)}" if stage else None) if p]
    return f"마지막 확인 기준 {', '.join(parts)}" if parts else None


def mark_seen(conn, user_id: str) -> int:
    """안 본 변화를 모두 "봤음"으로. 바꾼 줄 수."""
    return conn.execute("UPDATE user_cargo SET change_seen = true WHERE user_id = %s AND change_seen = false",
                        [user_id]).rowcount


# ── 주기 재판정 (워커) ──

def _due_rows(conn, limit: int, known_vessel_only: bool = False) -> list[tuple]:
    """지켜보는 중이고 진행 중인 화물을 마지막 확인이 오래된 순으로 limit건. 한 번도 안 본 줄이 먼저다.
    known_vessel_only면 배(vessel_mmsi)를 아는 화물만 고른다 (워커 예산, SHIPFINDER_CALLS_PER_KNOWN_VESSEL 설명)."""
    vessel = " AND vessel_mmsi IS NOT NULL" if known_vessel_only else ""
    return conn.execute(
        f"""SELECT user_id, cargo_key, bl_encrypted, bl_masked, label, bl_type, sale_due_date, forwarder_eta,
                  voyage_no, vessel_mmsi, last_verdict
           FROM user_cargo WHERE watch AND status = 'active'{vessel}
           ORDER BY last_checked_at ASC NULLS FIRST LIMIT %s""",
        [limit],
    ).fetchall()


def known_vessel_due_count(conn) -> int:
    """배를 아는, 지켜보는 진행 중 화물 수. 워커가 재판정 몫의 ShipFinder 예산을 이만큼만 떼어 두려고 쓴다 (worker/run.py)."""
    return conn.execute(
        "SELECT count(*) FROM user_cargo WHERE watch AND status = 'active' AND vessel_mmsi IS NOT NULL").fetchone()[0]


def _no_vessel_count(conn) -> int:
    """배를 모르는(vessel_mmsi 없음), 지켜보는 진행 중 화물 수. known_vessel_only로 건너뛴 건수로 알린다."""
    return conn.execute(
        "SELECT count(*) FROM user_cargo WHERE watch AND status = 'active' AND vessel_mmsi IS NULL").fetchone()[0]


def _notify(conn, user_id: str, name: str, old: str, new: str) -> bool:
    """카카오톡으로 알린다. 보냈으면 True. 연결 안 됨은 조용히, 그 밖의 실패는 종류만 남기고 False."""
    from backend.app.routers.kakao import _web  # 화면 주소 규칙을 한 곳에 둔다 (순환을 피하려고 안에서 부른다)

    text = (f"[Marvia] {name} 화물 판정이 '{VERDICT_LABEL[old]}'에서 '{VERDICT_LABEL[new]}'(으)로 바뀌었습니다. "
            "Marvia에서 이유와 할 일을 확인하세요.")
    try:
        kakao.send_to_user(conn, user_id, text, f"{_web()}/")
    except KakaoLinkError as e:
        if e.kind != "not_linked":
            log_failure("watch_notify", e.kind)
        return False
    except KakaoError as e:
        log_failure("watch_notify", e.kind)
        return False
    return True


def _check_one(conn, row: tuple, now: datetime, assess) -> tuple[bool, bool, bool]:
    """화물 한 건을 다시 판정한다. (판정이 나왔나, 바뀌었나, 알렸나)를 돌려준다. 실패는 예외로 올려 부르는 쪽이 센다."""
    user_id, key, bl_encrypted, bl_masked, label, bl_type, sale_due, forwarder_eta, voyage_no, mmsi, old = row
    bl_no = crypto.decrypt(bl_encrypted) if bl_encrypted else None
    if bl_no is None:  # 잠근 값이 비었거나 열쇠가 바뀌어 못 연다. 원문 없이는 조회할 수 없다
        raise WatchError("no_bl")
    request = AgentRequest(bl_no=bl_no, bl_type=bl_type, sale_due_date=sale_due, forwarder_eta=forwarder_eta,
                           voyage_no=voyage_no, resolved_mmsi=mmsi, session_id=f"watch-{now:%Y%m%d}")
    from backend.app.routers.agent import is_released, trusted_vessel  # 맨 위에서 부르면 라우터와 서비스가 서로 불러오는 순환이 된다

    # 지켜보기 재판정도 그 사용자의 LLM 사용량이다 (docs/specs/token-quota.md).
    # user_id를 넘겨야 토큰이 그 사람 몫으로 쌓이고 Langfuse 트레이스에도 user_id가 붙는다 (SDD 5.11).
    # 오늘 한도를 다 쓴 사람의 화물은 재판정하지 않는다. 화면 조회를 막는 것과 같은 한도다
    try:
        quota.ensure_allowed(None, user_id)
    except quota.QuotaExceeded as e:
        raise WatchError("quota") from e
    # 저장된 확정 배(vessel_mmsi)는 후보 확인 검색 없이 쓴다. 워커 예산은 화물당 ShipFinder 1회라서다 (routers/agent.py trusted_vessel)
    trust = trusted_vessel.set(mmsi)
    try:
        with session_scope(request.session_id, user_id):
            response = assess(request, None)
    finally:
        trusted_vessel.reset(trust)
    new = response.verdict
    if new is None:  # 판정이 없는 결과로 기준 등급을 지우지 않는다 (위 "왜 이렇게 했나")
        return False, False, False
    cargo.upsert_assessment(conn, user_id, request, response, released=is_released(response), now=now)
    if old is None or old == new:
        return True, False, False
    conn.execute("UPDATE user_cargo SET changed_from = %s, changed_at = %s, change_seen = false "
                 "WHERE user_id = %s AND cargo_key = %s", [old, now, user_id, key])
    return True, True, _notify(conn, user_id, label or bl_masked, old, new)


def run_watch(conn, *, limit: int = RUN_LIMIT, now: datetime | None = None, assess=None,
              known_vessel_only: bool = False) -> dict:
    """지켜보는 화물을 다시 판정하고 결과 개수를 돌려준다: checked / changed / notified / failed / unjudged.

    known_vessel_only: 배(vessel_mmsi)를 아는 화물만 다시 판정한다. 수집 워커(worker/run.py)가 ShipFinder 예산을
    화물당 SHIPFINDER_CALLS_PER_KNOWN_VESSEL회로 떼어 두고 부를 때 쓴다. 배를 모르는 화물은 후보 검색으로
    최대 11회를 써서 예산을 깬다. 그 화물은 skipped_no_vessel로 센다 (이 값일 때만 결과에 들어간다).
    사용자가 화면에서 다시 조회하면 배가 정해져 vessel_mmsi가 채워지고, 그다음부터 워커가 다시 판정한다.

    assess: 판정 함수 (request, memory) -> AgentResponse. 기본은 조회 화면과 같은 routers.agent._assess다.
    테스트가 가짜를 끼운다. 한 건이 어디서 실패하든 나머지는 계속하고, 로그에는 오류 종류만 남긴다.
    unjudged: 판정이 비어 돌아와 화물 표를 건드리지 않은 건수 (checked에도 센다).
    """
    if assess is None:
        from backend.app.routers.agent import _assess as assess
    now = now or datetime.now(timezone.utc)
    summary = {"checked": 0, "changed": 0, "notified": 0, "failed": 0, "unjudged": 0}
    if known_vessel_only:
        summary["skipped_no_vessel"] = _no_vessel_count(conn)
    for row in _due_rows(conn, limit, known_vessel_only):
        try:
            judged, changed, notified = _check_one(conn, row, now, assess)
        except Exception as e:  # 한 건 실패가 다른 사람의 감시를 막지 않는다. 종류만 남긴다
            log_failure("watch_cargo", e.kind if isinstance(e, WatchError) else type(e).__name__)
            summary["failed"] += 1
            continue
        summary["checked"] += 1
        summary["unjudged"] += not judged
        summary["changed"] += changed
        summary["notified"] += notified
    return summary
