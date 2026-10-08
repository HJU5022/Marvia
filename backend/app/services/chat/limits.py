"""채팅 창구의 숫자 상한·시간대·파일 경로 같은 설정 값 (services/chat/chat.py에서 옮김)."""
from __future__ import annotations

from pathlib import Path
from datetime import timedelta, timezone

KST = timezone(timedelta(hours=9))

# 수입 화물선 기준(선종·입항 목적) 원본. 코드에 목록을 적지 않는다 (skills/port-busan/cargo-vessels.md)
CARGO_RULES_PATH = Path(__file__).resolve().parents[4] / "skills" / "port-busan" / "cargo-vessels.md"

MESSAGE_MAX = 500          # 입력 문장 상한 (EC-07)

CACHE_SEC = 600            # 같은 기간 입항 예정은 10분 동안 다시 받지 않는다

# 후속 답 근거 카드의 조회 시각이 이번 문장 시작보다 이만큼 이전이면 지난 문장의 카드로 본다 (시계 차이 여유)
MAP_CARD_SLACK_SEC = 60

CARGO_CALLS_PER_TURN = 1  # 한 문장에서 화물 도구 호출은 한 번만. 한 문장에 B/L이 여러 개면 그 한 번 안에서 코드가 모두 조회한다 (아래 MAX_BLS_PER_TURN)

MAX_BLS_PER_TURN = 3  # 한 문장에서 한꺼번에 조회하는 B/L 수 상한. 판정 흐름마다 UNI-PASS·LLM을 부르므로 비용·지연이 B/L 수만큼 는다

HISTORY_TURNS = 6  # LLM에 넘길 최근 대화 줄 수. "이건", "그 배"가 가리키는 것은 보통 바로 앞 두세 턴에 있다

SHIP_LIST_SHOWN = 5  # 입항 선박 검색 답 문장에 이름을 적는 척 수. 전체 표는 화면이 그린다

ARRIVALS_SHOWN = 8  # 입항 선박 검색 결과 중 LLM에 돌려줄 척 수. 전체 표는 화면이 그린다

UNRELATED_MAX_CHARS = 120  # 잡담에 LLM이 직접 쓰는 답은 한 문장. 이보다 길면 고정 안내로 (unrelated 답 검사)

MEMO_MAX_ITEMS = 12

SCREEN_ARRIVALS_MAX = 10  # 화면 선박 목록에서 LLM에 주는 최대 줄 수. 입력 길이를 작게 두려는 상한이다

UNREAD_MAX = 3

SEND_ONLY_MAX = 40  # 이 길이 이하의 보내기 요청은 다른 질문이 없는 것으로 보고 LLM 없이 코드가 처리한다

# 제안 문장의 고정 끝말. 대화 기록에서 "앞서 제안했나"를 찾는 표식이기도 하다 (화면이 보낸 글이라 글자 그대로 찾는다)
WATCH_ONLY_MAX = 20  # 이 길이 이하이고 지켜보기 낱말이 있으면 다른 질문이 없는 지켜보기 요청으로 본다 ("이거 지켜봐 줘", "그만 지켜봐도 돼")

# ── 지금 상태를 카카오톡으로 보내기 ──
# 문장은 코드가 쓴다. 재료는 그 사용자의 화물 줄에 저장된 마지막 판정(last_*)뿐이라 없는 값을 지어내지 않는다.
# (화면의 답은 요청에 담겨 오지 않는다. 저장된 줄이 가장 믿을 수 있는 "지금 상태"다: 지켜보기 알림이 읽는 곳과 같다)
KAKAO_COOLDOWN_SEC = 300  # 같은 사용자·같은 화물은 5분에 한 번. 카카오톡 메시지가 쏟아지지 않게
