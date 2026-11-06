"""감시 목록의 화물을 모두 다시 조회해 단계 변화를 기록한다 (계획 3d). 상주 프로그램은 두지 않는다.

실행: uv run python scripts/recheck_watch.py
주기 실행은 바깥 도구에 맡긴다. 예(30분마다, crontab):
  */30 * * * * cd <저장소> && uv run python scripts/recheck_watch.py
지금 조회는 재생 데이터(unipass_replay)다. 실제 UNI-PASS 조회는 계획 3b에서 같은 함수 모양으로 붙인다.
"""

from marvia.config import Settings
from marvia.db import connect
from marvia.watch import recheck

with connect(Settings().database_url) as conn:
    print("단계가 바뀐 화물:", recheck(conn))
