"""skills/*/rules.md 프론트매터에서 코드가 쓰는 값 읽기 (계약 C6, SDD 3.6).

결정마다 권한자는 하나다 (강사 피드백: Prompt·Skill·코드에 같은 판정 규칙이 있어 서로 어긋났다).
결정은 backend/ 코드가 하고, 그 재료(임계값·목록·표)는 Skill 폴더마다 rules.md 프론트매터에 둔다.
  - ais-reliability/rules.md  AIS 신호 기준값, 출처 우선순위
  - customs-stages/rules.md   통관 보류 낱말, 정상 단계 목록
  - port-busan/rules.md       부산 기준점·반경·항구 코드
  - cargo-verdict/rules.md    2층 등급 판정 표 재료
코드에 숫자를 적지 않는다 (CLAUDE.md "하지 말 것"). 값을 읽는 곳은 이 파일 하나다.
판정 코드(services/judge/signals.py, services/judge/verdict.py)와 MCP 도구가 같이 쓴다.

여러 파일을 한 dict로 합친다. 같은 키가 두 파일에 있으면 어느 값이 이기는지 숨겨지므로 바로 실패시킨다.
부르는 쪽은 키가 어느 파일에 있는지 몰라도 된다 (rule("busan_ref")).
"""
from functools import cache
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).resolve().parents[4] / "skills"
RULES_FILE = "rules.md"


def _front_matter(path: Path) -> dict:
    """rules.md 맨 앞 --- 로 둘러싸인 YAML 블록을 dict로 돌려준다. 프론트매터가 없으면 실패시킨다."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path}에 프론트매터가 없습니다")
    front = yaml.safe_load(text.split("---", 2)[1]) or {}
    if not isinstance(front, dict):
        raise ValueError(f"{path} 프론트매터가 키: 값 모양이 아닙니다")
    return front


@cache
def load_rules(skills_dir: Path = SKILLS_DIR) -> dict:
    """skills/*/rules.md 프론트매터를 모두 읽어 한 dict로 합친다.

    파일 순서는 폴더 이름순이라 실행마다 같다. 같은 키가 두 파일에 있으면 ValueError (권한자는 하나).
    @cache라 파일은 처음 한 번만 읽는다. rules.md를 고쳤으면 서버를 다시 띄운다.
    """
    merged: dict = {}
    where: dict[str, Path] = {}  # 키 → 그 키를 정의한 파일. 중복 오류 메시지에 두 파일을 다 적는다
    paths = sorted(skills_dir.glob(f"*/{RULES_FILE}"))
    if not paths:
        raise ValueError(f"{skills_dir}에서 */{RULES_FILE}를 찾지 못했습니다")
    for path in paths:
        for key, value in _front_matter(path).items():
            if key in merged:
                raise ValueError(f"{key}가 두 파일에 있습니다: {where[key]}, {path}. 한 파일에만 둡니다")
            merged[key] = value
            where[key] = path
    return merged


@cache
def load_file(path: Path) -> dict:
    """rules.md가 아닌 Skill 파일 하나의 프론트매터 (예: port-busan/cargo-vessels.md, 선박 검색 기준).
    load_rules의 합치기에는 들어가지 않는다. 판정에 쓰지 않는 값이라 rule()과 섞지 않는다."""
    return _front_matter(path)


def rule(key: str):
    """값 하나를 읽는다. 없으면 바로 실패시켜 오타를 조용히 넘기지 않는다."""
    rules = load_rules()
    if key not in rules:
        raise KeyError(f"skills/*/{RULES_FILE}에 {key}가 없습니다")
    return rules[key]


def stage_key(name: str) -> str:
    """단계 이름 비교용. 띄어쓰기만 다른 이름("수입신고 수리"와 "수입신고수리")을 같게 본다."""
    return "".join(name.split())


def is_listed_stage(name: str) -> bool:
    """customs-stages/rules.md customs_stages 목록에 있는 단계인가. 관세사 필요 여부와 통관 설명 고정 문장이 같이 쓴다."""
    return stage_key(name) in customs_stage_names()


@cache
def customs_stage_names() -> frozenset[str]:
    """customs-stages/rules.md customs_stages 목록의 name들을 stage_key 모양으로 돌려준다.

    관세사 필요 여부(needs_broker)는 코드가 정하고, 어떤 단계가 정상 목록에 있는지는 rules.md가 원본이다.
    그래서 코드가 목록을 따로 적지 않고 rules.md를 읽는다. 전에는 SKILL.md 표 첫 칸을 읽었는데,
    표 모양이 바뀌면 깨지기 쉬워 YAML 목록으로 옮겼다.
    목록이 비어 읽히면 모든 단계가 "목록에 없음"이 되므로 바로 실패시킨다.
    """
    names = frozenset(stage_key(stage["name"]) for stage in rule("customs_stages") or [])
    if not names:
        raise ValueError("customs-stages/rules.md customs_stages가 비어 있습니다")
    return names
