"""감시 목록의 화물을 모두 다시 조회해 단계 변화를 기록한다 (계획 3d). 상주 프로그램은 두지 않는다.

실행: uv run python scripts/recheck_watch.py
주기 실행은 바깥 도구에 맡긴다. 예(30분마다, crontab):
  */30 * * * * cd <저장소> && uv run python scripts/recheck_watch.py
조회는 marvia.tools.unipass다(기본 재생, MARVIA_UNIPASS_MODE=live에 키가 있을 때만 실제).
"""

import sys

from marvia.config import Settings
from marvia.db import connect
from marvia.watch import recheck, watch_keys

settings = Settings()
try:
    keys = watch_keys(settings.data_key.get_secret_value())
except ValueError:
    # [왜] 키가 없거나 틀리면 표의 번호를 풀 수 없다. DB를 건드리기 전에 멈춘다
    # [주의] 키 값은 출력하지 않는다
    print("MARVIA_DATA_KEY가 없거나 올바른 키가 아닙니다. .env를 확인한 뒤 다시 실행하세요.")
    sys.exit(1)

with connect(settings.database_url) as conn:
    print("단계가 바뀐 화물:", recheck(conn, keys))
