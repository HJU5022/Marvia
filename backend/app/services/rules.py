"""skills/ 문서에서 코드가 쓰는 값 읽기.

1. skills/ais-reliability/rules.md 프론트매터 (계약 C6, SDD 3.6)
   임계값 원본은 rules.md 하나다. 코드에 숫자를 적지 않는다 (CLAUDE.md "하지 말 것").
   임계값을 읽는 곳은 여기 하나다. 판정 코드(services/signals.py)와 MCP 도구가 같이 쓴다.
2. skills/customs-stages/SKILL.md 단계 목록 표의 단계 이름 (10-01)
   관세사 필요 여부를 코드가 정할 때 "표에 없는 단계"를 가리는 데 쓴다. 단계 목록 원본은 Skill 표 하나다.
"""
from functools import cache
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
RULES_PATH = SKILLS_DIR / "ais-reliability" / "rules.md"
CUSTOMS_SKILL_PATH = SKILLS_DIR / "customs-stages" / "SKILL.md"
CUSTOMS_TABLE_HEADING = "## 단계 목록"


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


def stage_key(name: str) -> str:
    """단계 이름 비교용. 띄어쓰기만 다른 이름("수입신고 수리"와 "수입신고수리")을 같게 본다."""
    return "".join(name.split())


@cache
def customs_stage_names(path: Path = CUSTOMS_SKILL_PATH) -> frozenset[str]:
    """customs-stages SKILL.md "단계 목록" 표의 첫 칸(단계 이름)들을 stage_key 모양으로 돌려준다.

    결정마다 권한자는 하나다 (10-01 강사 피드백). 관세사 필요 여부는 코드가 정하고,
    어떤 단계가 정상 목록에 있는지는 Skill 표가 원본이다. 그래서 코드가 목록을 따로 적지 않고 표를 읽는다.
    표가 비어 읽히면 모든 단계가 "표에 없음"이 되므로 바로 실패시킨다.
    """
    names, in_table = set(), False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_table = line.strip() == CUSTOMS_TABLE_HEADING
            continue
        if in_table and line.startswith("|"):
            first = line.strip().strip("|").split("|")[0].strip()
            # 머리줄("단계")과 구분줄("---")은 건너뛴다
            if first and first != "단계" and set(first) - set("-: "):
                names.add(stage_key(first))
    if not names:
        raise ValueError(f"{path}에서 '{CUSTOMS_TABLE_HEADING}' 표를 읽지 못했습니다")
    return frozenset(names)
