"""실제 UNI-PASS로 번호 하나를 조회해 본다 (done 2.3의 실제 확인, 직접 할 일). 키가 필요하다.

실행: MARVIA_UNIPASS_MODE=live uv run python scripts/try_unipass.py <화물관리번호 또는 B/L> [B/L 연도]
결과: 단계·단계 시각·항구만 찍는다. 번호·키·응답 원문은 찍지 않는다(약관, 설계 12절).
[주의] 실제 번호를 쓰는 일이라 직접 돌린다. 결과를 저장소나 LLM에 넣지 않는다.
"""

import sys

import httpx

from marvia.config import Settings
from marvia.identify.models import CargoFacts
from marvia.tools.unipass import CFG, fetch_cargo

settings = Settings()
key = settings.unipass_key.get_secret_value()
if settings.unipass_mode != "live" or not key:
    sys.exit("[멈춤] MARVIA_UNIPASS_MODE=live와 MARVIA_UNIPASS_KEY가 있어야 한다")
year = int(sys.argv[2]) if len(sys.argv) > 2 else None
with httpx.Client(timeout=CFG["timeout_s"], follow_redirects=False) as client:
    result = fetch_cargo(sys.argv[1], key=key, client=client, year=year)
# [주의] number 칸(실제 번호)은 찍지 않는다
print(
    result.model_dump(include={"stage", "stage_at", "port"})
    if isinstance(result, CargoFacts)
    else result.model_dump()
)
