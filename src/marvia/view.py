"""화면에 보낼 값만 고르는 허용 목록 (설계 10절 화면 구성, 12절 신뢰 경계, 계획 4b Task 5).

공책(state)의 어느 칸이 브라우저로 가는지는 이 파일만 정한다. 토큰을 실제 번호로 되돌리는 일도 화면 길에서는
여기서만 한다. 가림 표(mask_map), 메시지, 원문(text), 조회할 번호(numbers)는 보내지 않는다.
하지 않는 일: 답 글 만들기(graph/answer.py), ETA·등급(선박 위치 조회와 함께 2차, 설계 10절 화물 카드).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from marvia.identify.mask import unmask
from marvia.tools.rules import load_rules

# 토큰 이름표 → 화면에 보일 이름 ("이렇게 읽었어요")
KIND_NAMES = {"BL": "B/L", "CARGO": "화물관리번호", "NUM": "읽지 못한 덩어리"}


def _unmask_all(value: Any, mask_map: dict[str, str]) -> Any:
    """값 안의 모든 글에서 토큰을 실제 번호로 되돌린다 (승인 카드의 인자)."""
    if isinstance(value, str):
        return unmask(value, mask_map)
    if isinstance(value, dict):
        return {key: _unmask_all(item, mask_map) for key, item in value.items()}
    if isinstance(value, list):
        return [_unmask_all(item, mask_map) for item in value]
    return value


def _link(url: str) -> str | None:
    """출처 링크는 허용한 공식 사이트(https)만 보낸다. 아니면 None(화면은 글자만 보인다)."""
    parsed = urlparse(url)
    allowed = load_rules("agent")["official"]["allowed_hosts"]
    return url if parsed.scheme == "https" and parsed.hostname in allowed else None


def _plan(values: dict) -> list[dict]:
    """할 일 목록. 에이전트 길은 todos, 계획자 길은 plan을 같은 모양({content, status})으로 바꾼다."""
    if values.get("todos"):
        return [{"content": t["content"], "status": t["status"]} for t in values["todos"]]
    status = {"in_progress": "in_progress", "done": "completed", "pending": "pending"}
    return [
        {"content": f"{s['action']}: {s['query']}".rstrip(": "), "status": status.get(s["status"], "pending")}
        for s in values.get("plan", [])
    ]


def screen_view(values: dict) -> dict:
    """STATE_SNAPSHOT에 실을 값: 할 일, "이렇게 읽었어요", 화물 카드, 근거 패널."""
    mask_map = values.get("mask_map", {})
    reading = [
        {"token": token, "number": number, "kind": KIND_NAMES[token.strip("[]").rstrip("0123456789")]}
        for token, number in mask_map.items()
    ]
    cargos = []
    for cargo in values.get("cargos", []):
        facts, error = cargo.get("facts") or {}, cargo.get("error") or {}
        cargos.append(
            {
                "number": unmask(cargo["token"], mask_map),
                "stage": facts.get("stage"),
                "stage_at": facts.get("stage_at"),
                "port": facts.get("port"),
                "vessel": facts.get("vessel_name"),
                "source": facts.get("source"),
                "fetched_at": facts.get("fetched_at"),
                "error": error.get("message"),
            }
        )
    evidence = [
        {
            "unit_id": e["unit_id"],
            "heading": e["heading"],
            "effective": e["effective"],
            "text": e["text"],
            "source_url": _link(e["source_url"]),
        }
        for e in values.get("evidence", [])
    ]
    return {"plan": _plan(values), "reading": reading, "cargos": cargos, "evidence": evidence}


def interrupt_card(value: dict, mask_map: dict[str, str]) -> dict:
    """멈춘 이유(interrupt 값)를 화면 카드로 바꾼다: 선택지 카드 또는 승인 카드 (설계 6.3)."""
    if "action_requests" in value:
        # [왜] review_configs는 도구 이름마다 하나다(요청 순서가 아니다). 모르는 도구는 승인·거절만 연다
        allowed = {c["action_name"]: c["allowed_decisions"] for c in value.get("review_configs", [])}
        return {
            "kind": "approval",
            "actions": [
                {
                    "name": request["name"],
                    "args": _unmask_all(request["args"], mask_map),
                    "description": unmask(request.get("description", ""), mask_map),
                    "allowed": allowed.get(request["name"], ["approve", "reject"]),
                }
                for request in value["action_requests"]
            ],
        }
    return {
        "kind": "choice",
        "question": unmask(value["question"], mask_map),
        "options": [
            {"label": unmask(o["label"], mask_map), "description": unmask(o["description"], mask_map)}
            for o in value["options"]
        ],
        "recommended": value["recommended"],
        "timeout_s": load_rules("server")["question"]["timeout_s"],
    }
