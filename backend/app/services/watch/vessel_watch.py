"""B/L 없이 배(MMSI)만 지켜보기의 업무 규칙.

하는 일:
  add_vessel()     채팅에서 본 배를 지켜보기에 올린다 (같은 배를 다시 올리면 보인 값만 갱신)
  remove_vessel()  지켜보기를 푼다
  list_vessels()   내가 지켜보는 배와 마지막 위치·지나온 길 (GET /api/watch/vessels)
HTTP는 routers/watch.py가, 위치 수집은 worker/collector.py(SELECT_WATCHED)가 맡는다. 여기는 DB와 규칙만 안다.

왜 이렇게 했나:
- 판정·통관·카카오톡 알림이 없다: B/L이 없어 판정 재료(통관, 판매 예정일)가 없고, "도착 예정이 바뀌었다" 같은 사건을
  기록하는 곳도 아직 없다. 알림은 판정 변화(services/watch/watch._notify)만 보낸다. 배만 지켜보는 줄은 화면에서 마지막 위치를 보여 줄 뿐이다
- 위치는 새로 받는 코드를 만들지 않는다: 수집 워커가 화물 배와 같은 길(watch_positions, 017)로 받고, 여기서는 읽기만 한다
- 최대 MAX_WATCH척(화물 지켜보기와 같은 값, 따로 세는 상한): 배 한 척마다 워커가 ShipFinder를 한 번 부른다 (하루 한도 예산)
- name·flag·dest·eta는 사용자가 채팅에서 본 글이다. 검증이 아니라 길이만 자르고 그대로 저장한다. 판정 값이 아니라 표시용이고,
  LLM이 정하는 값이 아니다. 목적지 글 안의 문장은 데이터일 뿐 지시로 읽지 않는다 (CLAUDE.md "하지 말 것")
B/L은 이 경로에 아예 없다. DB 연결은 부르는 쪽이 연다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from backend.app.clients.replay import replay_enabled
from backend.app.clients.shipfinder import ShipFinderClient, ShipFinderError, quota_blocked
from backend.app.observability.langfuse import tool_span
from backend.app.observability.logging import log_failure
from backend.app.services.watch import vessel_detail
from backend.app.services.judge.rules import rule
from backend.app.services.watch.vessel_pick import as_datetime, normalize_call_sign, rank
from backend.app.services.watch.watch import MAX_WATCH, _track

make_client = ShipFinderClient  # 테스트가 가짜 클라이언트로 바꿔 끼우는 자리 (mcp_server/tools/vessel_candidates.py와 같은 방식)

TEXT_MAX = 120  # 표시용 글(이름·국적·목적지·도착 예정) 길이 상한. 화면 말풍선이 깨지지 않게 자르는 값이다


class VesselWatchError(Exception):
    """kind: limit(이미 MAX_WATCH척) / invalid(MMSI나 이름이 비었다) /
    unknown_vessel(호출부호로 검색된 배가 한 척도 없다) / lookup_failed(ShipFinder 검색이 실패했다) /
    quota_exhausted(오늘 ShipFinder 하루 한도를 다 썼다. 내일까지 다시 불러도 같아 lookup_failed와 안내가 다르다)."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def _clean(value: str | None) -> str | None:
    """앞뒤 공백을 떼고 TEXT_MAX로 자른다. 비면 None."""
    text = (value or "").strip()[:TEXT_MAX]
    return text or None


def resolve_mmsi(call_sign: str, ship_name: str | None = None) -> int:
    """입항 예정 목록(해수부 신고)의 호출부호로 MMSI를 찾는다 (64번).

    왜 호출부호인가: 해수부 신고에는 MMSI가 없고, 선명은 같은 이름의 다른 배가 많다.
    호출부호는 양쪽 모두 대문자로 하고 공백·하이픈을 지워 비교한다 (표기 차이로 놓치지 않게).
    여러 MMSI가 나오면 고른다 (64번): ShipFinder 검색은 예전에 같은 호출부호를 쓴 배도 돌려줘서 한 호출부호에 MMSI가
    여러 개인 배가 대부분이었다(운영 로그 many_match). 이름이 같은 배 먼저, 그다음 마지막 신호가 가장 최근인 배.
    자세히 보기(services/watch/vessel_detail.detail)도 같은 규칙(services/watch/vessel_pick.py)이라 두 화면이 같은 배를 가리킨다.
    한 척도 없을 때만 unknown_vessel (엉뚱한 배를 지켜보게 하면 안 된다).
    실패 구분: 하루 한도 소진은 quota_exhausted, 그 밖의 검색 실패는 lookup_failed. 클라이언트가 이미 시간 제한·재시도를 한 뒤의 결과다.
    클라이언트가 한도·시간 초과로 지난 캐시 값을 대신 줬으면 새 결과로 받지 않는다: 지난 검색 결과로 배를 정하면
    예전 정보로 잘못 정할 수 있고, 한도 소진을 unknown_vessel로 잘못 알리던 문제(64번)도 여기서 막는다.
    Langfuse span에는 endpoint·캐시 여부·건수·오류 코드·replay 여부만 남긴다 (호출부호·키·URL은 넣지 않는다).
    """
    sign = normalize_call_sign(call_sign)
    if not sign:
        raise VesselWatchError("invalid")
    with tool_span("vessel_watch.resolve_mmsi", {"endpoint": "VesselSearch"}) as span:
        span.metadata.update(endpoint="VesselSearch", served_from_cache=False, result_count=None,
                             replay_mode=replay_enabled())
        client = None
        try:
            client = make_client()
            # 검색어는 원문 호출부호 대신 정규화한 값. 하이픈·공백이 낀 표기는 검색에 걸리지 않는 일이 있다
            hits = client.search(sign, max=10).hits
            if client.last_cached_at is not None:
                span.metadata["served_from_cache"] = True
                kind = "quota_exhausted" if quota_blocked() else "lookup_failed"
                span.error = "cache_fallback"
                log_failure("vessel_watch_resolve", f"cache_fallback {kind}")
                raise VesselWatchError(kind)
        except VesselWatchError:
            raise
        except ShipFinderError as e:
            span.error = e.code
            log_failure("vessel_watch_resolve", e.code)
            raise VesselWatchError("quota_exhausted" if e.code == "quota_exhausted" else "lookup_failed")
        except Exception as e:  # 클라이언트 밖 예상 못 한 실패도 사용자에게 원문을 보이지 않는다
            span.error = type(e).__name__
            log_failure("vessel_watch_resolve", type(e).__name__)
            raise VesselWatchError("lookup_failed")
        finally:
            if client is not None:
                client.close()
        same = [h for h in hits if normalize_call_sign(h.call_sign) == sign]
        span.metadata["result_count"] = len({h.mmsi for h in same})
        if not same:
            span.error = "no_match"
            log_failure("vessel_watch_resolve", "no_match")
            raise VesselWatchError("unknown_vessel")
        best = rank(same, ship_name, lambda h: h.ship_name, lambda h: h.last_time)[0]
        if len({h.mmsi for h in same}) > 1:
            log_failure("vessel_watch_resolve", "many_match picked")  # 몇 번이나 고르는지 남긴다 (고른 값은 적지 않는다)
        return best.mmsi


# 위치 한 점을 watch_positions에 넣는 문장. worker/collector.py INSERT_WATCH_POSITION과 같은 표·열·충돌 규칙이다.
# 워커 파일을 import하지 않는 이유: api 이미지에는 worker/가 없다 (Dockerfile). 열이 바뀌면 둘을 같이 고친다
INSERT_POSITION = """
INSERT INTO watch_positions (mmsi, ts, fetched_at, lat, lng, sog, cog, navistat)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (mmsi, ts) DO NOTHING
"""


def _store_position(conn, mmsi: int, pos: dict | None) -> bool:
    """get_live_position 모양의 위치 한 점을 watch_positions에 넣는다. 넣었으면 True.
    언제 위치인지(last_time)나 좌표가 없으면 경로에 넣지 않는다(워커와 같다). 한도에 걸려 옛 값을 받은 것(cached_at)도 넣지 않는다:
    fetched_at이 실제 받은 시각처럼 보이게 되기 때문이다."""
    if not pos or pos.get("cached_at") or pos.get("lat") is None or pos.get("lng") is None or not pos.get("last_time"):
        return False
    fetched = as_datetime(pos.get("fetched_at"))
    conn.execute(INSERT_POSITION, (mmsi, as_datetime(pos["last_time"]), fetched, pos["lat"], pos["lng"],
                                   pos.get("sog"), pos.get("cog"), pos.get("navistat")))
    return True


def add_vessel(conn, user_id: str, mmsi: int, name: str, flag: str | None = None,
               dest: str | None = None, eta: str | None = None, call_sign: str | None = None) -> dict:
    """배를 지켜보기에 올린다. 이미 있으면 보인 값(이름·국적·목적지·도착 예정)만 갱신하고 한도를 다시 세지 않는다.

    call_sign은 자세히 보기 캐시를 찾는 데만 쓴다 (저장하지 않는다). 올릴 때 그 배의 위치가 10분 캐시에 있으면
    watch_positions에 바로 넣어 지켜보기 화면이 위치를 곧바로 보이게 한다.
    ShipFinder를 새로 부르지 않는다. 실패해도 지켜보기 켜기는 성공이다."""
    name = _clean(name)
    if not mmsi or mmsi <= 0 or not name:
        raise VesselWatchError("invalid")
    exists = conn.execute("SELECT 1 FROM vessel_watch WHERE user_id = %s AND mmsi = %s", [user_id, mmsi]).fetchone()
    if not exists:
        count = conn.execute("SELECT count(*) FROM vessel_watch WHERE user_id = %s", [user_id]).fetchone()[0]
        if count >= MAX_WATCH:
            raise VesselWatchError("limit")
    conn.execute(
        """INSERT INTO vessel_watch (user_id, mmsi, name, flag, dest, eta) VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (user_id, mmsi) DO UPDATE SET name = EXCLUDED.name, flag = EXCLUDED.flag,
             dest = EXCLUDED.dest, eta = EXCLUDED.eta, updated_at = now()""",
        [user_id, mmsi, name, _clean(flag), _clean(dest), _clean(eta)],
    )
    try:
        hit = vessel_detail.cached_result(call_sign, name)
        # 같은 MMSI의 위치일 때만 넣는다. 이름이 같은 다른 배의 위치를 이 배 것으로 저장하면 안 된다
        if hit and (hit.get("vessel") or {}).get("mmsi") == mmsi:
            _store_position(conn, mmsi, hit.get("position"))
    except Exception as e:  # 위치 미리 채우기는 덤이다. 이유만 남기고 켜기는 성공시킨다
        log_failure("vessel_watch_seed_position", type(e).__name__)
    return {"mmsi": mmsi, "watch": True}


def remove_vessel(conn, user_id: str, mmsi: int) -> dict:
    """지켜보기를 푼다. 없어도 오류가 아니다 (원하는 상태가 이미 그렇다)."""
    conn.execute("DELETE FROM vessel_watch WHERE user_id = %s AND mmsi = %s", [user_id, mmsi])
    return {"mmsi": mmsi, "watch": False}


def _is_stale(track: list[dict]) -> bool:
    """위치가 없거나, 마지막 점이 rules.md position_stale_hours보다 오래됐나 (자세히 보기의 stale 기준과 같은 값).
    지켜보기 목록을 열 때 새로 받아 올 대상을 가르는 기준이다. 새 임계값 키는 만들지 않았다:
    skills/*/rules.md 프론트매터는 계약 파일이라 작업 범위 밖이고, "위치가 오래됐다"는 이미 그 키의 뜻이다."""
    if not track:
        return True
    age = datetime.now(timezone.utc) - as_datetime(track[-1]["at"])
    return age > timedelta(hours=rule("position_stale_hours"))


def _refresh_stale(conn, user_id: str, rows: list, tracks: dict) -> None:
    """위치가 없거나 오래된 배의 현재 위치를 받아 watch_positions에 넣는다.

    워커가 6시간마다 도는 동안 새로 올린 배는 위치가 비어 있었다. 목록을 열면 바로 채운다.
    - 받는 길은 자세히 보기와 같다(vessel_detail.live_position, 10분 캐시 공유). 같은 배를 연달아 열어도 한 번만 부른다
    - 한 요청에 최대 MAX_WATCH척(사용자 한도와 같다). 동시에 받아 느린 한 척이 목록 전체를 늦추지 않게 한다
    - 오늘 하루 한도를 이미 다 썼으면(quota_blocked) 부르지 않는다
    - 한 척이 실패해도 옛 값을 그대로 두고 목록은 돌려준다 (실패는 로그에만)
    """
    stale = [(mmsi, name) for mmsi, name, *_ in rows if _is_stale(tracks[mmsi])][:MAX_WATCH]
    if not stale or quota_blocked():
        return

    def fetch(item):
        mmsi, name = item
        try:
            return mmsi, vessel_detail.live_position(mmsi, None, name)
        except Exception as e:
            log_failure("vessel_watch_refresh", type(e).__name__)
            return mmsi, None

    with ThreadPoolExecutor(max_workers=len(stale)) as pool:
        results = list(pool.map(fetch, stale))
    for mmsi, pos in results:
        try:
            if _store_position(conn, mmsi, pos):
                tracks[mmsi] = _track(conn, mmsi)
        except Exception as e:
            log_failure("vessel_watch_refresh", type(e).__name__)


def list_vessels(conn, user_id: str, refresh: bool = False) -> dict:
    """내가 지켜보는 배 목록. 위치는 watch_positions의 최근 점(마지막 점이 현재), 없으면 null (수집 전).
    refresh=True면 위치가 없거나 오래된 배를 먼저 새로 받아 채운다 (GET /api/watch/vessels만 켠다).
    판정·통관 칸은 일부러 없다 (B/L이 없다)."""
    rows = conn.execute(
        "SELECT mmsi, name, flag, dest, eta, created_at FROM vessel_watch WHERE user_id = %s ORDER BY created_at DESC",
        [user_id],
    ).fetchall()
    tracks = {mmsi: _track(conn, mmsi) for mmsi, *_ in rows}
    if refresh:
        _refresh_stale(conn, user_id, rows, tracks)
    items = []
    for mmsi, name, flag, dest, eta, created in rows:
        track = tracks[mmsi]
        last = track[-1] if track else None
        items.append({
            "mmsi": mmsi, "name": name, "flag": flag, "dest": dest, "eta": eta,
            "created_at": created.isoformat() if created else None,
            "lat": last["lat"] if last else None, "lng": last["lng"] if last else None,
            "cog": last["cog"] if last else None, "sog": last["sog"] if last else None,
            "position_at": last["at"] if last else None, "track": track,
        })
    return {"items": items}
