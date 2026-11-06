import pytest
from cryptography.fernet import Fernet
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from marvia.config import Settings
from marvia.graph.live import agent_deps, checkpoint_serde, live_memory


def test_builds_without_calling():
    # [왜] 만들기만 하면 LLM·DB·Voyage를 부르지 않는다. 가짜 키와 빈 연결로도 만들어진다
    deps = agent_deps(Settings(_env_file=None, anthropic_api_key="sk-test-not-real"), None, None)
    assert callable(deps.plan) and callable(deps.item) and callable(deps.write) and callable(deps.rag.search)


@pytest.mark.parametrize("secret", ["", "short-typed-secret"])
def test_memory_refuses_a_missing_or_bad_key_before_connecting(secret):
    # [왜] 없는 주소라도 연결 오류가 아니라 키 오류가 먼저 난다. 메모리 대화 기록으로 바꿔 쓰지 않는다
    with pytest.raises(ValueError, match="MARVIA_DATA_KEY"):
        with live_memory("postgresql://nowhere.invalid/x", secret):
            pass


def test_checkpoint_serializer_reads_only_encrypted_values():
    # [왜] 시험 안에서 만든 키. 저장소의 키를 쓰지 않는다
    serde = checkpoint_serde(Fernet.generate_key().decode())
    value = {"text": "DEMO0001 언제까지 해요?"}
    assert serde.loads_typed(serde.dumps_typed(value)) == value  # 암호화한 값은 읽는다
    # [왜] 암호화 전에 쓴 줄이나 DB에 직접 넣은 평문 줄을 그대로 받으면 암호화가 읽기 쪽에서 무너진다
    plain = JsonPlusSerializer().dumps_typed(value)
    with pytest.raises(ValueError, match="암호화되지 않은") as refused:
        serde.loads_typed(plain)
    assert "DEMO0001" not in str(refused.value)  # 오류 글에 값을 넣지 않는다


class Recorder:
    """보낸 SQL만 적는 가짜 연결 (실제 DB 없이 어느 연결을 쓰는지 본다)."""

    def __init__(self):
        self.sql: list[str] = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        return self

    def commit(self):
        pass

    def rollback(self):
        pass


def test_watch_writes_on_its_own_connection():
    # [왜] 검색·조문 조회는 DB 오류에 함께 쓰는 연결을 되돌린다. 병렬 도구에서 그 되돌리기가
    #      감시 줄을 넣은 뒤 확정하기 전에 끼면 감시 줄이 사라진다 (R-041)
    shared, own = Recorder(), Recorder()
    key = Fernet.generate_key().decode()
    settings = Settings(_env_file=None, anthropic_api_key="sk-test-not-real", data_key=key)
    deps = agent_deps(settings, shared, own)
    assert deps.watch is not None
    deps.watch.add("u1", "DEMO0001", "반입신고")
    assert any("INSERT INTO watches" in sql for sql in own.sql)
    assert shared.sql == []
