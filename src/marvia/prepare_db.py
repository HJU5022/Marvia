"""DB 표를 준비한다: migrations/*.sql, 대화 기록(checkpointer)·장기 기억(Store) 표 (설계 8절, 계획 4b Task 8).

실행: python -m marvia.prepare_db (compose의 prepare 서비스, 배포의 Cloud Run 작업). 여러 번 돌려도 같다.
[왜] 운영 서버가 시작할 때 표를 만들면 CREATE INDEX CONCURRENTLY가 다른 연결의 트랜잭션을 기다리다 시작 탐침이
     실패할 수 있다(계획 4b 사전 부검 3번). 표 만들기를 한 번 도는 명령으로 떼어 둔다.
     서버의 setup()은 표가 있으면 아무것도 하지 않는다.
하지 않는 일: 코퍼스 색인(scripts/index_corpus.py), 그래프 적재(scripts/build_graph.py).
"""

from __future__ import annotations

from marvia.config import Settings
from marvia.db import connect
from marvia.graph.live import live_memory


def main() -> None:
    settings = Settings()
    with connect(settings.database_url):  # migrations/*.sql을 적용한다
        pass
    with live_memory(settings.database_url, settings.data_key.get_secret_value()):  # setup()이 표를 만든다
        pass
    print("표 준비 끝")


if __name__ == "__main__":
    main()
