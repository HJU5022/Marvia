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


def test_an_approval_inside_a_subagent_resumes_after_restart(agent_deps, test_url, monkeypatch):
    # [왜] 수퍼바이저 길(계획 7b)은 서브에이전트를 노드 안에서 따로 부른다. 그 안에서 승인으로 멈춘 자리가
    #      암호화 저장기에 남고, 새 연결·새 그래프가 그 자리에서 이어 가 도구를 한 번만 돌리는지 본다
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    from marvia.graph import tools

    class ToolModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    def call(name, args, id):
        return AIMessage("", tool_calls=[{"name": name, "args": args, "id": id}])

    chili = {
        "category": "농산물·임산물",
        "same": ["생산국", "품명", "수출업소", "포장장소"],
        "different": [],
        "prior_precise": "받음",
        "prior_result": "적합",
        "prior_cert_on": "2026-03-10",
        "flags": [],
    }
    checks = []
    real = tools.reimport_check
    monkeypatch.setattr(tools, "reimport_check", lambda *a, **k: checks.append(1) or real(*a, **k))
    key = Fernet.generate_key().decode()
    config = {"configurable": {"thread_id": "pg-sub-approval", "user_id": "u1"}}
    first = [
        call("handoff", {"to": "item", "task": "건고추 재수입 판정 뒤 품목 카드로 저장"}, "h1"),
        call("check_reimport", {"facts": chili}, "r1"),
        call("save_item_card", {"name": "건고추"}, "v1"),
    ]
    # 첫 번째 서버: 품목 서브에이전트 안에서 승인을 기다리며 멈춘다
    with live_memory(test_url, key) as (saver, store):
        deps = agent_deps(model=ToolModel(messages=iter(first)))
        graph = build_main_graph(deps, saver, loop="supervisor", store=store)
        out = graph.invoke({"text": "건고추 카드로 기억해 줘"}, config)
        assert out["__interrupt__"][0].value["action_requests"][0]["name"] == "save_item_card"
        assert store.get(("users", "u1", "items"), "건고추") is None
    # 두 번째 서버: 새 연결, 새 그래프, 남은 대본만 가진 새 모델
    rest = [AIMessage("저장했어요."), AIMessage("")]
    with live_memory(test_url, key) as (saver, store):
        deps = agent_deps(model=ToolModel(messages=iter(rest)))
        graph = build_main_graph(deps, saver, loop="supervisor", store=store)
        out = graph.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config)
        values = graph.get_state(config).values
        assert store.get(("users", "u1", "items"), "건고추").value["name"] == "건고추"
    assert "answer" in out and values["actions"] == ["품목 카드 '건고추' 저장"]
    assert len(checks) == 1  # 재수입 판정은 다시 돌지 않았다
    assert values["llm_calls"] == 5 + 1  # 멈추기 전 3 + 이어 간 뒤 2 + 작성자
