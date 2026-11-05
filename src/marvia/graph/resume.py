"""승인 재개 값 정리: 화면에서 온 승인 응답을 라이브러리에 넘기기 전에 모양을 확인한다 (설계 6.3).

하지 않는 일: 승인 여부 판단, 승인 카드 만들기(graph/agent.py), 질문(ask_user) 응답 정리.
[주의] 읽지 못한 값은 승인으로 보지 않고 거절로 돌린다(실행하지 않는 쪽이 안전하다).
"""

from __future__ import annotations

from typing import Any

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
    # [왜] 개수가 다르면 어느 결정이 어느 도구의 것인지 알 수 없다. 모두 거절한다
    if not isinstance(decisions, list) or len(decisions) != count:
        return {"decisions": [dict(UNREADABLE) for _ in range(count)]}
    return {
        "decisions": [
            decision if _valid(decision, names[i] if names else None) else dict(UNREADABLE)
            for i, decision in enumerate(decisions)
        ]
    }
