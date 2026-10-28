"""rules/*.yaml을 읽는다. 임계값과 목록은 코드에 숫자로 적지 않고 여기서 읽는다 (설계 7.1)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

# src/marvia/tools/rules.py → 저장소 루트의 rules/
RULES_DIR = Path(__file__).resolve().parents[3] / "rules"


@cache
def load_rules(name: str) -> dict:
    """rules/{name}.yaml을 한 번만 읽어 둔다."""
    return yaml.safe_load((RULES_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
