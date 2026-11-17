"""화면에 보낼 값만 고르는 허용 목록 (설계 10절 화면 구성, 12절 신뢰 경계, 계획 4b Task 5).

공책(state)의 어느 칸이 브라우저로 가는지는 이 파일만 정한다.
카드와 화물 카드의 토큰을 실제 번호로 되돌리는 일은 여기서 한다. 답 글은 답 노드(graph/main.py)가
되돌려 이미 번호로 나온다. 가림 표(mask_map)는 dict로 보내지 않고 "이렇게 읽었어요" 목록
(토큰, 번호, 종류)으로만 보인다. 메시지, 원문(text), 조회할 번호(numbers)도 보내지 않는다.
배 식별 스위치가 켜진 서버(screen_view의 vessel)는 화물 카드에 배(ship)와 판정(verdict) 칸을 더한다(계획 8b).
그 값은 코드가 낸 것이고 화면의 글은 rules/vessel.yaml, rules/verdict.yaml이 정한 글이다.
선택 카드의 후보 이름·호출부호·배 번호는 끼어들기 값에 없고(자리표), 여기서 공책의 후보로 바꿔 채운다.
하지 않는 일: 답 글 만들기(graph/answer.py), 판정 계산(tools/judge.py).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from marvia.identify.mask import unmask
from marvia.tools.rules import load_rules
from marvia.tools.verdict import CONFIDENCE_LABEL, GRADE_LABEL, SCHEDULE_LABEL

# 토큰 이름표 → 화면에 보일 이름 ("이렇게 읽었어요")
KIND_NAMES = {"BL": "B/L", "CARGO": "화물관리번호", "CNTR": "컨테이너 번호", "NUM": "읽지 못한 덩어리"}


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


def _ship(row: dict | None) -> dict:
    """화물 카드의 배 칸. [주의] 배 이름·호출부호·배 번호는 화면에만 보인다. 모델에는 가지 않는다."""
    reasons = load_rules("vessel")["reasons"]
    if row is None:  # 이번 차례에 배 식별 단계를 지나지 않은 화물(루프 안에서 새로 찾은 화물)
        return {
            "status": "unknown",
            "reason": reasons["not_looked"],
            "detail": None,
            "check": None,
            "name": None,
            "call_sign": None,
            "mmsi": None,
        }
    # [왜] 화면 글은 status가 아니라 reason과 basis로 만든다. 사용자가 고른 배(status user_choice)는 "고르신
    #      배로
    #      봤어요"에 그 검사의 reason 글(맞춘 칸이나 맞추지 못한 까닭)을 서류로 본 결과로 덧붙인다
    picked = row["status"] == "user_choice"
    reason = reasons["user_choice"] if picked else reasons[row["reason"]]
    if row.get("redo_capped"):  # 다시 찾기 횟수에 닿은 요청이 있었다 (계획 8c)
        limit = load_rules("vessel")["redo_limit"]
        reason += ". " + load_rules("vessel")["redo"]["capped_note"].format(limit=limit)
    return {
        "status": row["status"],
        "reason": reason,
        "detail": row.get("detail"),  # 조회 클라이언트의 정한 오류 글. 한도 소진과 일시 실패가 갈린다
        "check": reasons[row["reason"]] if picked else None,
        "name": row.get("name"),
        "call_sign": row.get("call_sign"),
        "mmsi": row.get("mmsi"),
    }


def _verdict(row: dict) -> dict:
    """화물 카드의 판정 칸. 등급이 없으면 "등급 없음"과 그 까닭(notes)을 보인다."""
    labels, texts, reasons = (
        load_rules("vessel")["labels"],
        load_rules("verdict"),
        load_rules("vessel")["reasons"],
    )
    return {
        "grade": row["grade"],  # 색을 고르는 이름(fine·watch·alert·act). 없으면 None
        "grade_label": GRADE_LABEL.get(row["grade"], labels["no_grade"]),
        "confidence": CONFIDENCE_LABEL[row["confidence"]],
        "schedule": SCHEDULE_LABEL.get(row["schedule"], labels["no_schedule"]),
        "eta": row["trusted_eta"],
        "eta_source": labels["eta_sources"].get(row["eta_source"]),
        "margin_days": row["margin_days"],
        "signals": [labels["signals"][s["id"]] for s in row["signals"] if s["state"] == "triggered"],
        # 판정 함수의 이유는 verdict.yaml에, 배 식별 단계가 더한 이유(over_cap 등)는 vessel.yaml에 있다
        "notes": [texts["notes"].get(name) or reasons[name] for name in row["notes"]],
        "info": [texts["info"][name] for name in row["info"]],
        # [왜] 내린 화물은 도착 예정을 보지 않은 것이다. 화면이 "도착 예정 모름"을 그리지 않게 알려 준다
        "landed": "landed" in row["info"],
    }


def ship_texts(candidates: list[dict]) -> dict[str, str]:
    """선택 카드의 자리표({ship1}, {ship1_info}) → 후보의 이름과 설명. 번호는 후보 순서(1부터)다."""
    cfg = load_rules("vessel")
    out: dict[str, str] = {}
    for i, ship in enumerate(candidates, 1):
        info = cfg["candidate"].format(call_sign=ship["call_sign"] or cfg["no_call_sign"], mmsi=ship["mmsi"])
        if ship.get("check"):
            info += " · " + cfg["candidate_check"].format(check=cfg["reasons"][ship["check"]])
        out[f"{{ship{i}}}"] = ship["name"] or cfg["no_name"]
        out[f"{{ship{i}_info}}"] = info
    return out


def screen_view(values: dict, vessel: bool = False) -> dict:
    """STATE_SNAPSHOT에 실을 값: 할 일, "이렇게 읽었어요", 화물 카드, 근거 패널."""
    mask_map = values.get("mask_map", {})
    reading = [
        {"token": token, "number": number, "kind": KIND_NAMES[token.strip("[]").rstrip("0123456789")]}
        for token, number in mask_map.items()
    ]
    cargos = []
    # [왜] 칸을 붙일지는 공책이 아니라 서버의 스위치가 정한다. 켰다가 끈 대화의 옛 값은 보이지 않는다
    ships = {row["token"]: row for row in values.get("vessels", [])}
    verdicts = {row["token"]: row for row in values.get("verdicts", [])}
    for cargo in values.get("cargos", []):
        facts, error = cargo.get("facts") or {}, cargo.get("error") or {}
        cell = verdicts.get(cargo["token"])
        more = (
            {"ship": _ship(ships.get(cargo["token"])), "verdict": cell and _verdict(cell)}
            if vessel and facts
            else ({"ship": None, "verdict": None} if vessel else {})
        )
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
                **more,
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


def _fill(text: str, texts: dict[str, str]) -> str:
    """선택 카드 글의 자리표를 후보의 이름과 설명으로 바꾼다."""
    for key, value in texts.items():
        text = text.replace(key, value)
    return text


def interrupt_card(value: dict, mask_map: dict[str, str], candidates: list[dict] | None = None) -> dict:
    """멈춘 이유(interrupt 값)를 화면 카드로 바꾼다: 선택지 카드 또는 승인 카드 (설계 6.3)."""
    if "action_requests" in value:
        # [왜] review_configs는 도구 이름마다 하나다(요청 순서가 아니다). 모르는 도구는 승인·거절만 연다
        allowed = {c["action_name"]: c["allowed_decisions"] for c in value.get("review_configs", [])}
        labels = load_rules("agent")["approval"]["labels"]
        # [왜] 고르는 칸의 값 목록은 규칙이 정한다. 화면이 따로 들고 있지 않게 카드에 싣는다
        choices = {"save_preference": load_rules("agent")["memory"]["depths"]}
        return {
            "kind": "approval",
            "actions": [
                {
                    "name": request["name"],
                    "label": labels.get(request["name"], request["name"]),
                    "choices": choices.get(request["name"]),
                    "args": _unmask_all(request["args"], mask_map),
                    "description": unmask(request.get("description", ""), mask_map),
                    "allowed": allowed.get(request["name"], ["approve", "reject"]),
                }
                for request in value["action_requests"]
            ],
        }
    texts = ship_texts(candidates or [])
    return {
        "kind": "choice",
        "question": unmask(value["question"], mask_map),
        "options": [
            {
                "label": unmask(_fill(o["label"], texts), mask_map),
                "description": unmask(_fill(o["description"], texts), mask_map),
            }
            for o in value["options"]
        ],
        "recommended": value["recommended"],
        "timeout_s": load_rules("server")["question"]["timeout_s"],
    }


def vessel_choice(typed: str, candidates: list[dict]) -> int:
    """배 선택 카드에 직접 적은 글 → 선택 번호.

    호출부호나 배 번호가 후보 한 척에만 들어 있으면 그 번호(1부터)다.

    그 밖(맞는 후보가 없거나 둘 이상)은 0(모르겠어요)이다.
    """
    text = "".join(typed.split()).upper()
    named = [
        i
        for i, ship in enumerate(candidates, 1)
        if (ship["call_sign"] and "".join(ship["call_sign"].split()).upper() in text) or ship["mmsi"] in text
    ]
    return named[0] if len(named) == 1 else 0
