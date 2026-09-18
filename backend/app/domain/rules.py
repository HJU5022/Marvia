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


# ─────────────────────────────────────────────────────────────────────────────
# 규칙 적용 (SDD 5절 5단계)
# ─────────────────────────────────────────────────────────────────────────────
# 값은 전부 skills/converge/rules/ 에서 읽는다. 여기에 숫자를 적지 않는다 (SDD 7절 원칙).

import re

_TIME_WORDS = {"아침": 8, "오전": 9, "점심": 12, "오후": 14, "저녁": 18, "밤": 21, "새벽": 5}


def parse_meet_time(text: str | None) -> str | None:
    """사람이 쓴 시각 표현에서 "HH:MM" 을 뽑는다. 못 뽑으면 None.

      "목요일 08:00" → "08:00"     "오늘 22:00" → "22:00"
      "목요일 아침 8시" → "08:00"   "오후 2시" → "14:00"

    날짜는 여기서 다루지 않는다. 날짜는 세션의 meet_at 이 가진다 (테이블정의서 1절).
    LLM 에 맡기지 않는 이유는 같은 문장이 늘 같은 시각으로 읽혀야 하기 때문이다.
    """
    if not text:
        return None

    hhmm = re.search(r"(\d{1,2})\s*:\s*(\d{2})", text)
    if hhmm:
        hour, minute = int(hhmm.group(1)), int(hhmm.group(2))
    else:
        korean = re.search(r"(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?", text)
        if not korean:
            return None
        hour, minute = int(korean.group(1)), int(korean.group(2) or 0)

    # "오후 2시" 처럼 앞에 붙은 말로 12시간제를 푼다
    if hour < 12:
        for word, base in _TIME_WORDS.items():
            if word in text and base >= 12:
                hour += 12
                break
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def lead_min(preset: str | None) -> int:
    """절차 소요(분). 함정은 위병소, SI 는 1층 인솔 (access.md)."""
    access = load_rule("access")
    return int(access["gate_lead_min"] if preset == "ship_maintenance" else access["lobby_lead_min"])


def buffer_min(preset: str | None) -> int:
    """여유(분). 함정 정비는 고객사 방문과 같은 기준, SI 배포는 인솔 기준 (transport.md, SDD 7절 프리셋 표)."""
    transport = load_rule("transport")
    key = "buffer_client_min" if preset == "ship_maintenance" else "buffer_deploy_min"
    return int(transport[key])


def traffic_extra_min(raw_min: int, transport: str, transfer_count: int | None) -> int:
    """경로 API 값에 얹는 시간. 자동차는 정체분, 대중교통은 환승 가산 (transport.md)."""
    rules = load_rule("transport")
    if transport == "car":
        pct = int(rules["car_traffic_pct"])
        return max(int(rules["car_traffic_min_min"]), round(raw_min * pct / 100))
    if transfer_count:
        return int(rules["transit_transfer_extra_min"])
    return 0


def access_ok(kind: str, applied: bool | None) -> bool:
    """이 자리가 지금 출입조치 상태로 가능한가 (access.md pier_requires_access_applied).

    부두 안은 출입조치를 신청해 둔 경우에만 쓸 수 있다. 위병소·로비는 절차가 시작되는 자리라
    신청 전이어도 만날 수 있다. 거기서 신청 결과를 확인하고 들어간다.
    """
    if kind == "pier" and load_rule("access")["pier_requires_access_applied"]:
        return applied is True
    return True


def candidate_score(kind: str, access_required: bool) -> int:
    """후보를 줄 세우는 점수. 클수록 앞. 대형 모델을 부르지 않는 경우에 쓴다 (SDD 5절 라우팅 small).

    절차가 있는 현장이면 절차 시작점이 먼저다 (access.md rendezvous_is_procedure_start).
    절차가 없으면 찾기 쉬운 랜드마크가 먼저다.
    """
    procedure_start = {"gate", "lobby", "hq"}
    if access_required:
        return 2 if kind in procedure_start else 1
    return 2 if kind == "landmark" else 1


def switch_outside(constraints: list[str]) -> bool:
    """도착이 어긋나 출입조치를 포기하고 부두 밖에서 만나야 하는가 (access.md switch_if_delay_min).

    근거: 인천 레이더 건. 입항이 늦어 도착이 30분 이상 어긋나면 출입조치 시각을 맞출 수 없어
    부두 밖 랜드마크로 옮겼다.

    지금은 슬롯에 "몇 분 어긋났는지"가 없고 `arrival_delayed` 플래그만 있다. 그래서 플래그가 있으면
    기준을 넘었다고 본다. 분 단위가 슬롯에 들어오면 switch_if_delay_min 과 직접 비교로 바꾼다
    (SDD 11절에 남겨 둔 항목).
    """
    if "arrival_delayed" not in constraints:
        return False
    return int(load_rule("access")["switch_if_delay_min"]) > 0
