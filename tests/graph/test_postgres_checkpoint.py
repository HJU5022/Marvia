"""서버를 껐다 켠 것처럼 새 연결·새 그래프로 멈춘 질문을 이어 간다. 로컬 DB가 꺼져 있으면 건너뛴다."""

from uuid import uuid4

import psycopg
import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

from marvia.config import Settings
from marvia.graph.main import build_main_graph

URL = Settings().database_url


def _db_up() -> bool:
    try:
        with psycopg.connect(URL, connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


# [왜] DB가 꺼진 컴퓨터에서도 나머지 테스트는 돌아야 한다. 이 파일만 "건너뜀"으로 표시한다
pytestmark = pytest.mark.skipif(not _db_up(), reason="로컬 Postgres가 꺼져 있음 (docker compose up -d db)")


def test_resume_after_restart(agent_deps):
    # [왜] 돌릴 때마다 새 대화 번호를 쓴다. 지난번 실행의 사진과 섞이지 않게
    config = {"configurable": {"thread_id": f"pg-{uuid4()}"}}
    # 첫 번째 서버: 질문하다 멈춘다
    with PostgresSaver.from_conn_string(URL) as saver:
        saver.setup()  # 체크포인트 표가 없으면 만든다. 이미 있으면 그대로 둔다
        out = build_main_graph(agent_deps(), saver).invoke({"text": "MOCK12345678TEST87654321"}, config)
        assert "__interrupt__" in out
    # with 블록을 나오면 DB 연결이 닫힌다 = 서버가 꺼진 것과 같다
    # 두 번째 서버: 새 연결, 새 그래프. 같은 대화 번호로 DB에서 사진을 꺼내 이어 간다
    with PostgresSaver.from_conn_string(URL) as saver:
        out = build_main_graph(agent_deps(), saver).invoke(Command(resume={"selected": 0}), config)
        assert "TEST87654321: 하선신고 (인천)" in out["answer"]
