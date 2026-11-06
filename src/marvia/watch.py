"""감시 목록: 화물을 서버에 등록해 두고, 다시 조회해 단계가 바뀌면 기록했다가 다음 대화에서 알린다 (계획 3d).

하지 않는 일: 주기 실행(상주 프로그램 없이 scripts/recheck_watch.py를 cron 같은 바깥 도구가 부른다),
LLM 호출. [주의] 표에는 실제 번호가 있다. 이 파일의 함수만 읽고, 그래프에는 토큰으로 바꿔 보인다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import psycopg

from marvia.identify.models import CargoFacts, ToolError
from marvia.tools.unipass_replay import lookup_cargo


@dataclass(frozen=True)
class WatchDeps:
    """그래프가 쓰는 감시 목록 기능 묶음. 실제 값은 live_watch가 만들고, 시험은 가짜 함수를 넣는다."""

    add: Callable[[str, str, str], None]  # (사용자, 실제 번호, 지금 단계) → 감시 목록에 넣기
    news: Callable[[str], list[dict]]  # 사용자 → 아직 보이지 않은 변화 [{"number", "old_stage", "new_stage"}]


def add_watch(conn: psycopg.Connection, user: str, number: str, stage: str) -> None:
    """화물 하나를 사용자의 감시 목록에 넣는다. 이미 있으면 그대로 둔다."""
    try:
        conn.execute(
            "INSERT INTO watches (user_id, number, stage) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id, number) DO NOTHING",
            (user, number, stage),
        )
        conn.commit()
    except psycopg.Error:
        # [왜] 실패한 트랜잭션이 남으면 같은 연결의 다음 질의가 모두 죽는다. 되돌린 뒤 다시 던진다
        conn.rollback()
        raise


def recheck(conn: psycopg.Connection, lookup: Callable[[str], CargoFacts | ToolError] = lookup_cargo) -> int:
    """감시 중인 화물을 모두 다시 조회해 단계가 바뀐 것을 기록한다. 바뀐 화물 수를 돌려준다."""
    changed = 0
    watches = conn.execute("SELECT id, number, stage FROM watches ORDER BY id").fetchall()
    for watch_id, number, stage in watches:
        try:
            result = lookup(number)
        except (OSError, ValueError):
            # [왜] 한 줄의 조회 오류가 다른 줄까지 멈추지 않게 건너뛰고 다음 실행에서 다시 본다
            #      (graph/identify.py의 identify_number와 같은 규칙)
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


def take_news(conn: psycopg.Connection, user: str) -> list[dict]:
    """사용자의 아직 보이지 않은 변화를 꺼내고 본 것으로 표시한다. 기록된 순서대로 돌려준다."""
    try:
        rows = conn.execute(
            "UPDATE watch_events AS e SET seen = true FROM watches AS w "
            "WHERE e.watch_id = w.id AND w.user_id = %s AND NOT e.seen "
            "RETURNING e.id, w.number, e.old_stage, e.new_stage",
            (user,),
        ).fetchall()
        conn.commit()
    except psycopg.Error:
        # [왜] 실패한 트랜잭션이 남으면 같은 연결의 다음 질의가 모두 죽는다. 되돌려 seen 표시도 취소한다
        conn.rollback()
        raise
    # [왜] UPDATE ... RETURNING은 순서를 정해 주지 않는다. 기록 id 순서로 정렬한다
    return [{"number": n, "old_stage": old, "new_stage": new} for _, n, old, new in sorted(rows)]


def live_watch(conn: psycopg.Connection) -> WatchDeps:
    """로컬 DB 연결로 감시 목록 기능을 만든다."""
    return WatchDeps(
        add=lambda user, number, stage: add_watch(conn, user, number, stage),
        news=lambda user: take_news(conn, user),
    )
