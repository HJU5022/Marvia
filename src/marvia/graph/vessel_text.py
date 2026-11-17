"""모델에 주는 배 판정 글: 판정 블록과 읽기 도구의 줄 (계획 8c, 결정 C2, C3, C6).

글은 화물 카드와 같은 함수(view._ship, view._verdict)에서 온다. 함수가 둘이면 카드와 답이 어긋난다.
[주의] 배 이름·호출부호·배 번호는 줄에 싣지 않는다. 카드가 쓰는 칸에서 그 셋을 뺀 칸만 쓴다.
하지 않는 일: 판정 계산(tools/judge.py), 날짜 받기(graph/tools.py).
"""

from __future__ import annotations

from datetime import datetime

from marvia.tools.deadlines import KST
from marvia.tools.rules import load_rules
from marvia.view import _ship, _verdict  # pyright: ignore[reportPrivateUsage]


def _when(eta: str) -> str:
    """믿을 도착 시각을 한국 날짜와 시각(YYYY-MM-DD HH:MM)으로 쓴다. UTC 글 그대로 쓰지 않는다."""
    moment = datetime.fromisoformat(eta).astimezone(KST)
    return f"{moment:%Y-%m-%d} {moment:%H:%M}"


def _line(token: str, ship_row: dict | None, verdict_row: dict | None) -> str:
    cfg = load_rules("vessel")["block"]
    if verdict_row is None:
        return f"{token}: {cfg['none']}"
    ship, verdict = _ship(ship_row), _verdict(verdict_row)
    ship_text = ship["reason"] + (f" ({ship['check']})" if ship["check"] else "")
    parts = [
        cfg["ship"].format(text=ship_text),
        cfg["grade"].format(text=verdict["grade_label"]),
        cfg["confidence"].format(text=verdict["confidence"]),
        cfg["schedule"].format(text=verdict["schedule"]),
    ]
    if verdict["eta"]:
        source = verdict["eta_source"]
        parts.append(
            cfg["eta"].format(when=_when(verdict["eta"]), source=source)
            if source
            else cfg["eta_no_source"].format(when=_when(verdict["eta"]))
        )
    if verdict["margin_days"] is not None:
        parts.append(cfg["margin"].format(days=verdict["margin_days"]))
    for key in ("signals", "notes", "info"):
        if verdict[key]:
            parts.append(cfg[key].format(items=", ".join(verdict[key])))
    return f"{token}: " + cfg["join"].join(parts)


def vessel_lines(cargos: list[dict], vessels: list[dict], verdicts: list[dict]) -> list[str]:
    """화물마다 한 줄: 토큰, 배 확인 글, 등급·확신·일정, 믿을 도착 예정, 켜진 신호, 까닭과 참고."""
    ships = {row["token"]: row for row in vessels}
    cells = {row["token"]: row for row in verdicts}
    return [_line(c["token"], ships.get(c["token"]), cells.get(c["token"])) for c in cargos]


def vessel_block(cargos: list[dict], vessels: list[dict], verdicts: list[dict]) -> str:
    """차례 메시지와 작성자 입력에 붙이는 판정 블록. 줄이 없으면 빈 글이다."""
    lines = vessel_lines(cargos, vessels, verdicts)
    if not lines:
        return ""
    head = load_rules("vessel")["block"]["head"]
    return f"{head}\n<vessel_lines>\n" + "\n".join(lines) + "\n</vessel_lines>"


def read_lines(tokens: list[str], state: dict) -> list[str]:
    """읽기 도구의 결과 줄. 공책을 바꾸지 않는다."""
    cfg = load_rules("vessel")["block"]
    mask_map = state.get("mask_map", {})
    ships = {row["token"]: row for row in state.get("vessels", [])}
    cells = {row["token"]: row for row in state.get("verdicts", [])}
    out = []
    for token in tokens:
        if token not in mask_map:
            out.append(cfg["unknown_token"].format(token=token))
        elif token not in ships:
            out.append(cfg["not_looked"].format(token=token))  # 이번 차례에 루프가 새로 찾은 화물이다
        elif ships[token]["reason"] == "another_question":
            out.append(cfg["waiting"].format(token=token))
        else:
            out.append(_line(token, ships[token], cells.get(token)))
    return out
