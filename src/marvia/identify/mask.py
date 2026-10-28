"""LLM에 넘기기 전에 화물 번호를 [BL1]·[CARGO1]·[NUM1] 토큰으로 가린다.
실제 값은 mask_map에만 두고, 화면에 보낼 때 unmask로 되돌린다 (설계 4.2, 12)."""

from __future__ import annotations

from marvia.identify.parse import Kind, normalize, read_numbers

_LABEL: dict[str, str] = {"bl": "BL", "cargo_no": "CARGO", "unread": "NUM"}


def token_for(mask_map: dict[str, str], value: str, kind: Kind | str) -> str:
    """value의 토큰을 돌려준다. 없으면 새 토큰을 만들어 mask_map에 넣는다."""
    for token, existing in mask_map.items():
        if existing == value:
            return token
    label = _LABEL[kind]
    count = sum(1 for token in mask_map if token.startswith(f"[{label}"))
    token = f"[{label}{count + 1}]"
    mask_map[token] = value
    return token


def mask_text(text: str) -> tuple[str, dict[str, str]]:
    """글 속 번호 덩어리를 토큰으로 바꾼 글과 토큰 → 실제 값 표를 돌려준다."""
    mask_map: dict[str, str] = {}
    pieces: list[str] = []
    last = 0
    for span, read in read_numbers(text):
        if read.ambiguous:
            tokens = [token_for(mask_map, normalize(read.raw), "unread")]
        else:
            tokens = [token_for(mask_map, n.value, n.kind) for n in read.numbers]
        pieces.append(text[last:span.start])
        pieces.append("".join(tokens))
        last = span.end
    pieces.append(text[last:])
    return "".join(pieces), mask_map


def unmask(text: str, mask_map: dict[str, str]) -> str:
    """토큰을 실제 값으로 되돌린다. 화면에 보낼 때만 쓴다."""
    for token, value in mask_map.items():
        text = text.replace(token, value)
    return text
