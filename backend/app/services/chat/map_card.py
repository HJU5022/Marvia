"""도구 결과에서 지도 좌표 카드를 뽑는 순수 함수 (services/chat/chat.py에서 옮김). 좌표는 도구 결과에서만 읽는다."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from backend.app.services.judge import validate
from backend.app.services.chat.limits import MAP_CARD_SLACK_SEC
from backend.app.services.chat.models import ChatResult

def _number(value) -> float | None:
    """숫자(또는 숫자 글자)면 float, 아니면 None. bool은 숫자로 치지 않는다."""
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _card_time(card) -> datetime | None:
    """근거 카드의 조회 시각을 시간대 있는 값으로."""
    at = card.fetched_at
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)

def _map_payload(ran: list[dict], done: list[ChatResult], started: datetime) -> dict | None:
    """이번 문장에서 선박 실시간 위치를 실제로 가져왔을 때만 미니 지도 자료를 만든다. 좌표는 도구 결과에서만 읽는다 (LLM 글은 안 읽는다).

    세 길뿐이다:
    (a) 에이전트가 get_live_position을 직접 불렀고 결과에 error가 없다 (ran)
    (b) ask_cargo의 후속 답이 get_live_position을 써서 근거 카드 "get_live_position.lat/lng"가 붙었다 (routers/agent._tool_evidence).
        판정 근거 카드의 칸 이름은 "position"이라 겹치지 않는다. 다만 지난 후속 답의 카드가 저장돼 다시 올 수 있어,
        조회 시각이 이번 문장 시작 이후인 카드만 쓴다.
    (c) 후속 답이 지난 결과의 위치를 그대로 말했다: 답 문장에 그 위치의 위도·경도 숫자가 둘 다 있다 (좌표는 응답의 position 칸에서)
    check_cargo만 돌았거나 조회가 실패했으면 None이다.
    거리: 같은 문장의 estimate_distance → 화물 응답 eta.distance_nm 순. 배 이름: 같은 배일 때만 화물 응답의 선명 (a는 MMSI가 같아야 한다).
    """
    lat = lng = None
    received, mmsi, cargo_follow_up = None, None, False
    for call in ran:  # 같은 문장에서 여러 번 불렀으면 마지막 성공 결과
        result = call["result"] if isinstance(call["result"], dict) else {}
        if call["name"] == "get_live_position" and "error" not in result and _number(result.get("lat")) is not None \
                and _number(result.get("lng")) is not None:
            lat, lng, mmsi = _number(result["lat"]), _number(result["lng"]), result.get("mmsi")
            received = result.get("last_time") or result.get("fetched_at")
    follow_cards: dict[str, object] = {}
    if lat is None:
        floor = started - timedelta(seconds=MAP_CARD_SLACK_SEC)
        for r in done:
            cards = [c for c in (r.agent.evidence if r.agent else []) if c.field.startswith(("get_live_position.", "estimate_distance."))
                     and _card_time(c) >= floor]
            for c in cards:
                follow_cards[c.field] = c  # 같은 칸이 여럿이면 뒤의 것
        lat, lng = (_number(follow_cards[f].value) if f in follow_cards else None for f in ("get_live_position.lat", "get_live_position.lng"))
        if lat is not None and lng is not None:
            cargo_follow_up = True
            last = follow_cards.get("get_live_position.last_time")
            received = last.value if last else follow_cards["get_live_position.lat"].fetched_at.isoformat()
        else:
            # (c) 후속 답이 도구를 새로 부르지 않고 지난 결과의 위치로 답했다 (지난 결과에 위치가 이미 있으면 후속 프롬프트가
            # 도구를 부르지 말라고 한다). 답 문장에 그 위치의 위도·경도 숫자가 둘 다 들어 있을 때만 지도를 붙인다.
            # 숫자 대조는 검증 V7과 같은 방식이다. 배포본에서 "배가 어디쯤이야?"에 좌표로 답했는데 지도가 안 나올 뻔한 경우
            for r in reversed(done):
                pos = r.agent.position if r.agent else None
                said = set(validate._numbers(r.reply))
                if pos and validate._normal(str(pos.lat)) in said and validate._normal(str(pos.lng)) in said:
                    lat, lng, received, cargo_follow_up = pos.lat, pos.lng, pos.last_time.isoformat(), True
                    break
            if lat is None or lng is None:
                return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None

    vessel = next((r.agent.vessel for r in reversed(done) if r.agent and r.agent.vessel), None)
    same_ship = vessel is not None and (cargo_follow_up or (mmsi is not None and vessel.mmsi == mmsi))
    distance = next((_number(c["result"].get("distance_nm")) for c in reversed(ran)
                     if c["name"] == "estimate_distance" and isinstance(c["result"], dict) and "error" not in c["result"]), None)
    if distance is None and "estimate_distance.distance_nm" in follow_cards:
        distance = _number(follow_cards["estimate_distance.distance_nm"].value)
    if distance is None and same_ship:
        eta = next((r.agent.eta for r in reversed(done) if r.agent and r.agent.eta), None)
        distance = eta.distance_nm if eta else None
    return {"lat": lat, "lng": lng, "ship_name": vessel.name if same_ship else None, "distance_nm": distance,
            "received_at": str(received) if received else None, "source": "shipfinder"}
