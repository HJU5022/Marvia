"""B/L 없이 배(MMSI)만 지켜보기의 업무 규칙 (10-08 정운 실사용 57번).

하는 일:
  add_vessel()     채팅에서 본 배를 지켜보기에 올린다 (같은 배를 다시 올리면 보인 값만 갱신)
  remove_vessel()  지켜보기를 푼다
  list_vessels()   내가 지켜보는 배와 마지막 위치·지나온 길 (GET /api/watch/vessels)
HTTP는 routers/watch.py가, 위치 수집은 worker/collector.py(SELECT_WATCHED)가 맡는다. 여기는 DB와 규칙만 안다.

왜 이렇게 했나:
- 판정·통관·카카오톡 알림이 없다: B/L이 없어 판정 재료(통관, 판매 예정일)가 없고, "도착 예정이 바뀌었다" 같은 사건을
  기록하는 곳도 아직 없다. 알림은 판정 변화(services/watch._notify)만 보낸다. 배만 지켜보는 줄은 화면에서 마지막 위치를 보여 줄 뿐이다
- 위치는 새로 받는 코드를 만들지 않는다: 수집 워커가 화물 배와 같은 길(watch_positions, 017)로 받고, 여기서는 읽기만 한다
- 최대 MAX_WATCH척(화물 지켜보기와 같은 값, 따로 세는 상한): 배 한 척마다 워커가 ShipFinder를 한 번 부른다 (하루 한도 예산)
- name·flag·dest·eta는 사용자가 채팅에서 본 글이다. 검증이 아니라 길이만 자르고 그대로 저장한다. 판정 값이 아니라 표시용이고,
  LLM이 정하는 값이 아니다. 목적지 글 안의 문장은 데이터일 뿐 지시로 읽지 않는다 (CLAUDE.md "하지 말 것")
B/L은 이 경로에 아예 없다. DB 연결은 부르는 쪽이 연다.
"""
from __future__ import annotations

from backend.app.services.watch import MAX_WATCH, _track

TEXT_MAX = 120  # 표시용 글(이름·국적·목적지·도착 예정) 길이 상한. 화면 말풍선이 깨지지 않게 자르는 값이다


class VesselWatchError(Exception):
    """kind: limit(이미 MAX_WATCH척) / invalid(MMSI나 이름이 비었다)."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def _clean(value: str | None) -> str | None:
    """앞뒤 공백을 떼고 TEXT_MAX로 자른다. 비면 None."""
    text = (value or "").strip()[:TEXT_MAX]
    return text or None


def add_vessel(conn, user_id: str, mmsi: int, name: str, flag: str | None = None,
               dest: str | None = None, eta: str | None = None) -> dict:
    """배를 지켜보기에 올린다. 이미 있으면 보인 값(이름·국적·목적지·도착 예정)만 갱신하고 한도를 다시 세지 않는다."""
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
    return {"mmsi": mmsi, "watch": True}


def remove_vessel(conn, user_id: str, mmsi: int) -> dict:
    """지켜보기를 푼다. 없어도 오류가 아니다 (원하는 상태가 이미 그렇다)."""
    conn.execute("DELETE FROM vessel_watch WHERE user_id = %s AND mmsi = %s", [user_id, mmsi])
    return {"mmsi": mmsi, "watch": False}


def list_vessels(conn, user_id: str) -> dict:
    """내가 지켜보는 배 목록. 위치는 watch_positions의 최근 점(마지막 점이 현재), 없으면 null (수집 전).
    판정·통관 칸은 일부러 없다 (B/L이 없다)."""
    rows = conn.execute(
        "SELECT mmsi, name, flag, dest, eta, created_at FROM vessel_watch WHERE user_id = %s ORDER BY created_at DESC",
        [user_id],
    ).fetchall()
    items = []
    for mmsi, name, flag, dest, eta, created in rows:
        track = _track(conn, mmsi)
        last = track[-1] if track else None
        items.append({
            "mmsi": mmsi, "name": name, "flag": flag, "dest": dest, "eta": eta,
            "created_at": created.isoformat() if created else None,
            "lat": last["lat"] if last else None, "lng": last["lng"] if last else None,
            "cog": last["cog"] if last else None, "sog": last["sog"] if last else None,
            "position_at": last["at"] if last else None, "track": track,
        })
    return {"items": items}
