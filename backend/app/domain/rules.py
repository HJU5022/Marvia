"""규칙값 로드. skills/converge/rules/*.md 의 yaml 프론트매터를 읽어 dict로 돌려준다.

왜 이 파일이 있나 (SDD 7절):
  규칙값(여유 시간, 보관 일수, 출입 절차 소요 등)은 코드가 아니라 문서가 기준이다.
  코드에 숫자를 직접 적으면 문서와 코드가 따로 놀게 되고, 값을 바꿀 때 코드를 찾아 고쳐야 한다.
  그래서 코드는 이 함수로 문서를 읽기만 한다. 값을 바꾸려면 .md 파일만 고친다.

이 폴더의 규칙 (domain/CLAUDE.md):
  - 네트워크·LLM 호출 없음. 파일만 읽는다
  - API 키 없이 pytest가 돌아야 한다. 이 파일은 키가 전혀 필요 없다

지금은 로드 함수만 있다. 절차 소요·여유·역산·전환 조건 같은 계산식은 SDD 5절 5·7단계를
구현할 때 여기에 붙인다.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

# 규칙 문서 폴더. 이 파일(backend/app/domain/rules.py)에서 저장소 루트까지 올라간 뒤 skills/로.
# Docker 이미지 안에서도 같은 상대 구조로 복사되므로(Dockerfile이 루트를 빌드 컨텍스트로 씀) 그대로 동작한다.
_REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_DIR = _REPO_ROOT / "skills" / "converge" / "rules"

# 프론트매터 = 파일 맨 앞의 `---` 와 `---` 사이. 그 아래 본문(근거 사례·설명)은 사람이 읽는 부분이라 무시한다.
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


@lru_cache(maxsize=None)
def load_rule(name: str) -> dict:
    """skills/converge/rules/<name>.md 의 프론트매터를 dict로 돌려준다.

    예) load_rule("session") -> {"register_within_days": 30, "retain_after_meet_days": 30, ...}

    lru_cache: 같은 파일을 요청마다 다시 읽지 않도록 첫 호출 결과를 기억한다.
    규칙 파일은 배포 중에 바뀌지 않으므로(바꾸면 재배포) 캐시해도 안전하다.

    파일이 없거나 프론트매터가 없으면 바로 예외를 낸다. 규칙값이 없는 채로 조용히 돌아가면
    기본값이 코드에 숨어 들어가게 되므로, 시작 시점에 크게 실패하는 쪽을 택했다.
    """
    path = RULES_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"규칙 파일 없음: {path}")

    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if match is None:
        raise ValueError(f"프론트매터(--- ... ---)가 없음: {path}")

    data = yaml.safe_load(match.group(1))  # safe_load: 임의 파이썬 객체 생성 금지. 문서는 데이터일 뿐
    if not isinstance(data, dict):
        raise ValueError(f"프론트매터가 key: value 형식이 아님: {path}")
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 출발 시각 역산 (SDD 5절 7단계, MCP 도구 departure_calc)
# ─────────────────────────────────────────────────────────────────────────────
# 이 폴더 규칙대로 순수 계산만. 소요시간은 카카오·TMAP이 준 값을 인자로 받고, 여유·절차 소요는
# skills/converge/rules/ 의 값을 호출 쪽이 읽어 넘긴다. 여기서 규칙 파일을 직접 읽지 않는 이유는
# 프리셋(함정/SI)마다 다른 값을 고르는 판단이 파이프라인 몫이기 때문이다.

from datetime import datetime, timedelta


def calc_departure(
    arrive_by: str, duration_sec: int, buffer_min: int, access_lead_min: int
) -> dict:
    """도착 기한에서 거꾸로 빼서 출발 시각을 구한다.

      arrive_by            "09:00"  약속 시각 (점검 시작, 배포 시작)
      − access_lead_min    20       위병소 출입·인솔 절차. 이 시각까지 절차 시작점에 도착해야 함
      = arrive_by_adjusted "08:40"
      − duration_sec       2700     이동 (45분)
      − buffer_min         20       여유 (정체·환승)
      = depart_at          "07:35"

    반환: {"depart_at": "07:35", "arrive_by_adjusted": "08:40", "day_offset": 0}
    day_offset: 출발이 도착 기한의 전날이면 -1 (야간 배포 22:00~06:00 에서 실제로 생긴다).
                "HH:MM" 문자열만 주면 날짜가 사라지므로 따로 준다 (SDD 6절, 09-18 추가).
    """
    if duration_sec < 0 or buffer_min < 0 or access_lead_min < 0:
        raise ValueError("소요·여유·절차 시간은 음수일 수 없다")

    # 날짜는 계산용 임의 기준일. 시각 차이만 쓰므로 어느 날이든 상관없다.
    base = datetime(2000, 1, 2)  # 1월 2일: 전날(1월 1일)로 넘어가도 음수 날짜가 안 되게
    arrive = base.replace(hour=int(arrive_by[:2]), minute=int(arrive_by[3:5]))

    adjusted = arrive - timedelta(minutes=access_lead_min)
    depart = adjusted - timedelta(seconds=duration_sec) - timedelta(minutes=buffer_min)

    return {
        "depart_at": depart.strftime("%H:%M"),
        "arrive_by_adjusted": adjusted.strftime("%H:%M"),
        "day_offset": (depart.date() - arrive.date()).days,  # 0 = 같은 날, -1 = 전날
    }
