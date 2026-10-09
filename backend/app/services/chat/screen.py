"""화면이 보낸 대화 기록·화면 값을 믿지 않고 다시 가리는 함수와 화물 요약 (services/chat/chat.py에서 옮김, SDD 7절 신뢰 경계)."""
from __future__ import annotations

import re
from backend.app.observability.logging import log_failure
from backend.app.schemas.agent import AgentResponse
from backend.app.services.judge import guard
from backend.app.services.chat import citations as cite
from backend.app.services.chat.limits import HISTORY_TURNS, MESSAGE_MAX, SCREEN_ARRIVALS_MAX
from backend.app.services.chat.ids import mask_bls, mask_containers
from backend.app.services.chat.patterns import _MRN

def _masked_history(history: list[dict], refs: dict[str, str]) -> list[dict]:
    """화면이 보낸 최근 대화를 LLM에 넘길 모양으로 만든다. B/L·MRN·컨테이너 번호를 가리고 주입 모양 줄은 뺀다.
    화면이 보낸 값이라 assistant 줄도 우리가 쓴 글이라고 믿지 않는다 (SDD 7절 신뢰 경계). LLM에는 자료로만 간다."""
    turns = []
    for turn in history[-HISTORY_TURNS:]:
        role, text = turn.get("role"), (turn.get("text") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue
        # 지난 답 속 [E1] 근거 표시는 걷어 낸다: 화면이 보낸 글이라 믿지 않고, 표시가 LLM 맥락에 섞여 다음 답이 id를 따라 쓰지 않게 한다
        text = cite.strip_marks(text)
        if not text:
            continue
        # 가린 뒤에 자른다. 먼저 자르면 경계에 걸린 B/L 앞부분(8자 미만)이 가려지지 않고 LLM에 간다 (테스트에서 발견)
        # 컨테이너 번호도 가린다. B/L 가리기보다 먼저 해야 한다 (영숫자 11자라 B/L 모양에 걸린다)
        text, _ = mask_bls(_MRN.sub("[MRN]", mask_containers(text)[0]), refs)
        text = text[:MESSAGE_MAX]
        if guard.looks_like_injection(text):
            continue
        turns.append({"role": role, "text": text})
    return turns

def _screen_text(value, limit: int) -> str | None:
    """화면이 보낸 글자 하나를 LLM에 줄 수 있게 다듬는다. 번호(B/L·MRN·컨테이너)를 가리고 줄바꿈·제어 글자를 공백으로 바꾼다.
    주입 모양이면 None으로 돌려 호출한 쪽이 그 줄 전체를 뺀다. 비었으면 빈 글자 대신 None."""
    if value is None:
        return None
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value)).strip()
    text, _ = mask_bls(_MRN.sub("[MRN]", mask_containers(text)[0]), {})  # 가리기 순서는 _masked_history와 같다
    text = text[:limit]
    if guard.looks_like_injection(text):
        raise _ScreenInjection
    return text or None

class _ScreenInjection(Exception):
    """화면 자료의 글자가 주입 모양이다. 그 배 줄 전체를 LLM에 주지 않는다."""

def _masked_screen(on_screen: dict | None) -> dict | None:
    """화면이 보낸 "지금 떠 있는 배들"을 LLM에 넘길 모양으로. 화면이 보낸 값이라 믿지 않는다 (SDD 7절):
    글자는 _screen_text로 가리고 주입 모양 배는 줄째 뺀다. 목록은 SCREEN_ARRIVALS_MAX줄까지. LLM에는 자료로만 간다
    (프롬프트 Trust boundary). B/L·컨테이너 번호 칸은 요청 모양에 없다. 남은 것이 없으면 None."""
    if not on_screen:
        return None
    out: dict = {}
    vessel = on_screen.get("vessel")
    if vessel:
        try:
            item = {"ship_name": _screen_text(vessel.get("ship_name"), 80), "flag": _screen_text(vessel.get("flag"), 80),
                    "destination": _screen_text(vessel.get("destination"), 80),
                    "position_time": _screen_text(vessel.get("position_time"), 40)}
            for key in ("mmsi", "lat", "lng"):
                if isinstance(vessel.get(key), (int, float)):
                    item[key] = vessel[key]
            if item["ship_name"]:
                out["vessel"] = {k: v for k, v in item.items() if v is not None}
        except _ScreenInjection:
            log_failure("chat", "blocked prompt injection pattern in on_screen vessel")
    arrivals = []
    for row in (on_screen.get("arrivals") or [])[:SCREEN_ARRIVALS_MAX]:
        try:
            item = {"ship_name": _screen_text(row.get("ship_name"), 80), "flag": _screen_text(row.get("flag"), 80),
                    "eta": _screen_text(row.get("eta"), 40), "previous_port": _screen_text(row.get("previous_port"), 80),
                    "call_sign": _screen_text(row.get("call_sign"), 20)}  # 배를 지켜볼 때 MMSI를 찾는 열쇠
            if row.get("selected") is True:  # 사용자가 목록에서 고른 배 (지도에 보이는 배). 켜져 있을 때만 칸이 생긴다
                item["selected"] = True
        except _ScreenInjection:
            log_failure("chat", "blocked prompt injection pattern in on_screen arrival")
            continue
        if item["ship_name"]:
            arrivals.append({k: v for k, v in item.items() if v is not None})
    if arrivals:
        out["arrivals"] = arrivals
    return out or None

def _cargo_summary(resp: AgentResponse) -> dict:
    """화물 조회 결과 중 LLM에 돌려줄 부분. 다음 도구를 고르는 데 필요한 것만 준다 (배 이름·MMSI·호출부호, 도착 예정, 포워더·선사 이름, 품명).
    근거 카드와 통관 정보는 뺀다: 자세한 질문은 ask_cargo가 지난 결과 전체로 답한다. B/L은 응답에 없다.
    포워더·선사 이름만 통관 정보에서 꺼내 준다. "포워더가 어디예요" 같은 물음에 도구를 또 부르지 않고 답하게 하려는 것이다.
    품명(goods_name)도 준다. "고추 화물 어디야?"처럼 품명으로 화물을 가리키는 말을 알아듣게 하려는 것이다.
    컨테이너 번호(container_no)는 B/L처럼 화물을 특정하는 번호라 LLM에 주지 않는다: include에 없고 아래 customs에도 안 넣는다.
    세 값은 UNI-PASS 외부 글자라 주입 모양이면 뺀다 (SDD 7절, llm._clean_customs와 같은 예방 조치)."""
    summary = resp.model_dump(mode="json", include={"status", "verdict", "days_margin", "missing_inputs", "vessel", "eta", "answer"})
    if resp.customs is not None:
        names = {"forwarder_name": resp.customs.forwarder_name, "carrier_name": resp.customs.carrier_name,
                 "goods_name": resp.customs.goods_name}
        summary["customs"] = {key: (None if guard.looks_like_injection(value) else value) for key, value in names.items()}
    return summary

def _fmt_time(value) -> str | None:
    """도구 결과의 시각 글자를 분 단위까지만 보인다 (2026-10-07T01:02:03+00:00 → 2026-10-07 01:02). 없으면 None."""
    return str(value)[:16].replace("T", " ") if value else None
