"""승인 재개 값 정리: 화면에서 온 승인 응답을 라이브러리에 넘기기 전에 모양을 확인한다 (설계 6.3).

하지 않는 일: 승인 여부 판단, 승인 카드 만들기(graph/agent.py), 질문(ask_user) 응답 정리.
[주의] 읽지 못한 값은 승인으로 보지 않고 거절로 돌린다(실행하지 않는 쪽이 안전하다).
remask_reply는 화면 서버가 재개하기 전에 승인 결정의 글을 다시 가린다 (done 1.4, 계획 4b Task 6).
"""

from __future__ import annotations

from typing import Any

from marvia.identify.mask import mask_text

UNREADABLE = {"type": "reject", "message": "승인 값을 읽지 못해 실행하지 않았어요"}


def _valid(decision: Any, name: str | None) -> bool:
    """결정 하나가 정해진 모양인가. name이 있으면 edit이 도구 이름을 바꾸지 않았는지도 본다."""
    if not isinstance(decision, dict):
        return False
    kind = decision.get("type")
    if kind == "approve":
        return True
    if kind == "reject":
        return isinstance(decision.get("message"), str)
    if kind == "edit":
        action = decision.get("edited_action")
        return (
            isinstance(action, dict)
            and isinstance(action.get("name"), str)
            and isinstance(action.get("args"), dict)
            and (name is None or action["name"] == name)
        )
    return False


def approval_reply(raw: Any, count: int, names: list[str] | None = None) -> dict:
    """승인 응답을 {"decisions": [...]} (정확히 count개)로 만든다. 읽지 못한 결정은 거절로 바꾼다."""
    decisions = raw.get("decisions") if isinstance(raw, dict) else None
    # [왜] 이름 목록과 개수가 다르면 짝을 알 수 없다. 오류를 내지 않고 모두 거절한다
    if names is not None and len(names) != count:
        return {"decisions": [dict(UNREADABLE) for _ in range(count)]}
    # [왜] 개수가 다르면 어느 결정이 어느 도구의 것인지 알 수 없다. 모두 거절한다
    if not isinstance(decisions, list) or len(decisions) != count:
        return {"decisions": [dict(UNREADABLE) for _ in range(count)]}
    return {
        "decisions": [
            decision if _valid(decision, names[i] if names else None) else dict(UNREADABLE)
            for i, decision in enumerate(decisions)
        ]
    }


NEW_NUMBER = {"type": "reject", "message": "고친 값에 이 대화에 없던 화물 번호가 있어 실행하지 않았어요"}
REJECTED = "사용자가 거절했어요"


def _remask(value: Any, mask_map: dict[str, str]) -> tuple[Any, bool]:
    """값 안의 모든 글을 이 대화의 가림 표로 다시 가린다. 표에 없던 번호가 나왔는지도 돌려준다."""
    if isinstance(value, str):
        masked, grown = mask_text(value, mask_map)
        return masked, len(grown) > len(mask_map)
    if isinstance(value, dict):
        pairs = {key: _remask(item, mask_map) for key, item in value.items()}
        return {key: masked for key, (masked, _) in pairs.items()}, any(fresh for _, fresh in pairs.values())
    if isinstance(value, list):
        items = [_remask(item, mask_map) for item in value]
        return [masked for masked, _ in items], any(fresh for _, fresh in items)
    return value, False


def remask_reply(reply: dict, mask_map: dict[str, str]) -> dict:
    """approval_reply를 거친 승인 응답에서 고친 인자와 거절 글의 실제 번호를 이 대화의 토큰으로 바꾼다.

    [왜] 화면은 토큰을 실제 번호로 되돌려 보인다. 사람이 고친 인자와 거절 글은 실제 번호를 담아 돌아오고,
         승인 미들웨어는 고친 인자로 도구 호출 메시지를 바꾸고 거절 글을 도구 결과로 모델에 준다 (설계 12절).
    [주의] 이 대화의 가림 표에 없던 번호는 새 토큰을 만들지 않는다. 고치기는 거절로,
           거절 글은 정해 둔 글로 바꾼다.
    """
    decisions = []
    for decision in reply["decisions"]:
        if decision["type"] == "edit":
            args, fresh = _remask(decision["edited_action"]["args"], mask_map)
            edited = {**decision, "edited_action": {**decision["edited_action"], "args": args}}
            decisions.append(dict(NEW_NUMBER) if fresh else edited)
        elif decision["type"] == "reject":
            message, fresh = _remask(decision["message"], mask_map)
            decisions.append({**decision, "message": REJECTED if fresh else message})
        else:
            decisions.append(decision)
    return {"decisions": decisions}
