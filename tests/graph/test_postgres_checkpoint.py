"""서버를 껐다 켠 것처럼 새 연결·새 그래프로 멈춘 질문을 이어 간다. 로컬 DB가 꺼져 있으면 건너뛴다.

[왜] 실제 실행과 같은 암호화 저장기(live_memory)를 시험용 스키마(test_url)에서 쓴다.
     public 스키마의 개발 DB에 시험 줄(평문 번호)을 남기지 않는다.
"""

from cryptography.fernet import Fernet
from langgraph.types import Command

from marvia.graph.live import live_memory
from marvia.graph.main import build_main_graph


def test_resume_after_restart(agent_deps, test_url):
    key = Fernet.generate_key().decode()  # [왜] 시험 안에서 만든 키. 저장소의 키를 쓰지 않는다
    config = {"configurable": {"thread_id": "pg-resume"}}
    # 첫 번째 서버: 질문하다 멈춘다. live_memory가 체크포인트 표를 만든다
    with live_memory(test_url, key) as (saver, _store):
        out = build_main_graph(agent_deps(), saver).invoke({"text": "MOCK12345678TEST87654321"}, config)
        assert "__interrupt__" in out
    # with 블록을 나오면 DB 연결이 닫힌다 = 서버가 꺼진 것과 같다
    # 두 번째 서버: 새 연결, 새 그래프. 같은 대화 번호로 DB에서 사진을 꺼내 이어 간다
    with live_memory(test_url, key) as (saver, _store):
        out = build_main_graph(agent_deps(), saver).invoke(Command(resume={"selected": 0}), config)
        assert "TEST87654321: 하선신고 (인천)" in out["answer"]
