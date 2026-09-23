"""skills/ais-reliability/rules.md 프론트매터 읽기 (계약 C6, SDD 3.6).

임계값 원본은 rules.md 하나다. 코드에 숫자를 적지 않는다 (CLAUDE.md "하지 말 것").
임계값을 읽는 곳은 여기 하나다. 판정 코드(services/signals.py)와 MCP 도구가 같이 쓴다.
"""
from functools import cache
from pathlib import Path

import yaml

RULES_PATH = Path(__file__).resolve().parents[3] / "skills" / "ais-reliability" / "rules.md"


@cache
def load_rules(path: Path = RULES_PATH) -> dict:
    """rules.md 맨 앞 --- 로 둘러싸인 YAML 블록을 dict로 돌려준다."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path}에 프론트매터가 없습니다")
    front = text.split("---", 2)[1]
    return yaml.safe_load(front)


def rule(key: str):
    """임계값 하나를 읽는다. 없으면 바로 실패시켜 오타를 조용히 넘기지 않는다."""
    rules = load_rules()
    if key not in rules:
        raise KeyError(f"rules.md에 {key}가 없습니다")
    return rules[key]
