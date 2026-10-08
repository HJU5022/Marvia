"""컨테이너 번호로 화물 찾기 테스트 (services/chat/chat.py _swap_containers·mask_containers, services/watch/cargo.find_by_container).

DB·LLM·판정 흐름은 부르지 않는다. 가짜 연결과 가짜 llm.chat_agent를 끼운다.
B/L과 컨테이너 번호는 모두 모의값이다(실제 번호 아님). 컨테이너는 검산 숫자를 아래 _make가 따로 계산해 만든다.
"""
from contextlib import contextmanager

import pytest
from cryptography.fernet import Fernet

from backend.app import crypto
from backend.app.services.watch import cargo
from backend.app.services.chat import chat as svc
from backend.app.services import llm
from backend.tests.integration.test_chat import _agent_calls
from backend.tests.integration.test_chat_agent import _agent
from backend.app.services.chat import ids as chat_ids

BL = "MOCKBL20261006"  # 모의 B/L


def _make(owner: str, serial: str) -> str:
    """ISO 6346 검산 숫자를 붙인 컨테이너 번호. chat.container_check_digit과 따로 짠 계산이다(같은 코드를 쓰면 틀려도 같이 맞는다).
    글자 값: A=10부터 세되 11의 배수는 건너뛴다. 아래 표는 그 결과를 손으로 적은 것이다."""
    table = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                     [10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 34, 35, 36, 37, 38]))
    body = owner + serial
    total = sum((table[c] if c.isalpha() else int(c)) * 2 ** i for i, c in enumerate(body))
    return body + str(total % 11 % 10)


C1 = _make("ABCU", "123456")
C2 = _make("WXYJ", "654321")
C_BAD = C1[:-1] + str((int(C1[-1]) + 1) % 10)  # 검산 숫자만 틀린 번호


@pytest.fixture(autouse=True)
def agent_path(monkeypatch):
    monkeypatch.setenv("CHAT_AGENT", "on")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setattr(svc.memory, "lookup_notes", lambda user_id, bl: [])
    # 못 찾은 컨테이너는 세관에 같은 번호 B/L이 있는지 본다 (보완). 기본은 "세관에 없음"으로 두고 필요한 테스트만 바꾼다
    monkeypatch.setattr(svc.bl_parse, "exists_in_customs", lambda bl: False)


@pytest.fixture
def bl_key(monkeypatch):
    monkeypatch.setenv("BL_ENCRYPTION_KEY", Fernet.generate_key().decode())


class FakeConn:
    """execute로 들어온 SQL과 값을 적어 두고, 정해 둔 줄을 돌려준다."""

    def __init__(self, rows=()):
        self.calls, self.rows = [], list(rows)

    def execute(self, sql, params=()):
        self.calls.append((sql, list(params)))
        conn = self

        class Cur:
            def fetchall(self):
                return conn.rows
        return Cur()


def _stored(container_no, bl=BL, bl_type="MASTER"):
    """find_by_container가 읽는 줄 하나: (*COLUMNS, container_no, bl_encrypted)."""
    base = dict.fromkeys(cargo.COLUMNS)
    base.update(cargo_key="k1", bl_masked="MOC*******1006", bl_type=bl_type, status="active")
    return (*[base[c] for c in cargo.COLUMNS], container_no, crypto.encrypt(bl))


def _db(monkeypatch, rows):
    """DATABASE_URL을 두고 svc.connect를 가짜로. 연결이 열린 횟수와 FakeConn을 돌려준다."""
    conn = FakeConn(rows)
    opened = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")

    @contextmanager
    def fake_connect(*a, **k):
        opened.append(1)
        yield conn
    monkeypatch.setattr(svc, "connect", fake_connect)
    return conn, opened


def _no_llm(monkeypatch):
    monkeypatch.setattr(llm, "chat_agent", lambda *a, **k: pytest.fail("LLM을 부르면 안 된다"))
    monkeypatch.setattr(llm, "route_chat", lambda *a, **k: pytest.fail("LLM을 부르면 안 된다"))


# ── 검산 숫자 ──

def test_check_digit_accepts_valid_and_rejects_invalid():
    assert svc.find_containers(f"{C1} 어디쯤이야?") == [C1]
    assert svc.find_containers(f"{C_BAD} 어디쯤이야?") == []  # 검산 숫자가 틀리면 컨테이너로 보지 않는다
    assert chat_ids.container_check_digit(C1[:10]) == int(C1[10])


def test_detection_shape_rules():
    assert svc.find_containers(C1.lower()) == [C1]  # 소문자도 같은 번호
    assert svc.find_containers(f"{C1} {C2} {C1}") == [C1, C2]  # 나온 순서, 중복 없음
    bad_category = "ABCX" + C1[4:]  # 4번째 글자가 U/J/Z가 아니다
    assert svc.find_containers(bad_category) == []
    assert svc.find_containers("X" + C1) == [] and svc.find_containers(C1 + "7") == []  # 더 긴 글자의 일부


def test_plain_bl_is_not_a_container():
    assert svc.find_containers("MOCKBL20261006 괜찮아?") == []  # 일반 B/L 모양은 그대로 B/L 흐름


def test_mask_containers_tokens_before_bl_mask():
    masked, refs = chat_ids.mask_containers(f"{C1}랑 {C2}, {C1}")
    assert masked == "[CNTR1]랑 [CNTR2], [CNTR1]" and refs == {"[CNTR1]": C1, "[CNTR2]": C2}
    # 먼저 가리지 않으면 B/L 모양에 걸려 [BL1]이 된다 (순서가 중요한 이유)
    assert svc.mask_bls(C1)[0] == "[BL1]"


# ── cargo.find_by_container ──

def test_find_by_container_matches_whole_item_of_list(bl_key):
    stored = f"{C1}, {C2}"
    conn = FakeConn([_stored(stored)])
    row = cargo.find_by_container(conn, "u1", C2.lower())  # 목록의 둘째 항목, 소문자
    assert row["container_no"] == stored and row["bl_type"] == "MASTER"
    assert crypto.decrypt(row["bl_encrypted"]) == BL
    sql, params = conn.calls[0]
    assert "user_id = %s" in sql and params[0] == "u1" and C2 in params[1]  # 다른 사용자 줄은 SQL에서 이미 걸러진다


def test_find_by_container_rejects_partial_and_other_numbers(bl_key):
    conn = FakeConn([_stored(C2 + "9"), _stored(f"{C2[:6]}, ZZZZ")])  # SQL의 ILIKE는 걸렸지만 항목 통째로는 다르다
    assert cargo.find_by_container(conn, "u1", C2[:10]) is None
    assert cargo.find_by_container(FakeConn([]), "u1", C1) is None
    assert cargo.find_by_container(FakeConn([_stored(None)]), "u1", C1) is None  # container_no가 비어 있다


# ── handle: 찾았을 때 ──

def test_found_container_uses_real_bl_and_stored_type(monkeypatch, bl_key):
    conn, opened = _db(monkeypatch, [_stored(f"{C1}, {C2}", bl_type="MASTER")])
    calls = _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]"})])
    agent, run = _agent_calls()
    r = svc.handle(f"{C2} 어디쯤이야?", "s1", None, run, user_id="u1")
    assert len(agent) == 1 and agent[0].bl_no == BL and agent[0].bl_type == "MASTER"  # 저장된 구분으로 조회한다
    assert "하우스 B/L" not in r.reply  # 구분을 말하지 않아 HOUSE로 조회했다는 안내가 붙지 않는다
    assert calls[0]["masked"] == "[BL1] 어디쯤이야?" and calls[0]["refs"] == ["[BL1]"]
    assert C1 not in str(calls) and C2 not in str(calls) and BL not in str(calls)  # LLM 입력 어디에도 원문이 없다
    assert opened == [1] and conn.calls[0][1][0] == "u1"


def test_found_container_with_stored_house(monkeypatch, bl_key):
    _db(monkeypatch, [_stored(C1, bl_type="HOUSE")])
    _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]"})])
    agent, run = _agent_calls()
    svc.handle(f"{C1} 어디야", "s1", None, run, user_id="u1")
    assert agent[0].bl_no == BL and agent[0].bl_type == "HOUSE"


def test_stated_type_beats_stored_type(monkeypatch, bl_key):
    _db(monkeypatch, [_stored(C1, bl_type="MASTER")])
    _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]", "bl_type": "HOUSE"})])
    agent, run = _agent_calls()
    svc.handle(f"{C1} 하우스로 봐줘", "s1", None, run, user_id="u1")
    assert agent[0].bl_type == "HOUSE"


def test_stored_type_does_not_leak_to_next_request(monkeypatch, bl_key):
    _db(monkeypatch, [_stored(C1, bl_type="MASTER")])
    _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]"})])
    agent, run = _agent_calls()
    svc.handle(f"{C1} 어디야", "s1", None, run, user_id="u1")
    svc.handle(f"{BL} 어디야", "s2", None, run, user_id="u1")  # B/L을 직접 쓴 다음 요청은 평소대로 HOUSE
    assert [a.bl_type for a in agent] == ["MASTER", "HOUSE"]


# ── handle: 못 찾았을 때 ──

def test_not_found_returns_fixed_sentence_without_llm(monkeypatch, bl_key):
    _db(monkeypatch, [])
    _no_llm(monkeypatch)
    agent, run = _agent_calls()
    r = svc.handle(f"{C1} 어디쯤이야?", "s1", None, run, user_id="u1")
    assert r.kind == "message" and r.reply == svc.CONTAINER_NOT_FOUND and agent == []
    assert C1 not in r.reply


def test_db_error_falls_back_to_not_found(monkeypatch, bl_key):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")

    @contextmanager
    def broken(*a, **k):
        raise RuntimeError("db down")
        yield
    monkeypatch.setattr(svc, "connect", broken)
    _no_llm(monkeypatch)
    agent, run = _agent_calls()
    r = svc.handle(f"{C1} 어디쯤이야?", "s1", None, run, user_id="u1")
    assert r.reply == svc.CONTAINER_NOT_FOUND and agent == []


def test_unreadable_bl_counts_as_not_found(monkeypatch, bl_key):
    """열쇠가 달라 B/L을 못 열면 못 찾은 것으로 본다 (원본이 없으면 조회할 수 없다)."""
    row = _stored(C1)
    _db(monkeypatch, [(*row[:-1], "not-a-valid-token")])
    _no_llm(monkeypatch)
    agent, run = _agent_calls()
    assert svc.handle(f"{C1} 어디야", "s1", None, run, user_id="u1").reply == svc.CONTAINER_NOT_FOUND
    assert agent == []


# ── handle: 로그인 안 함 ──

def test_not_logged_in_never_touches_db_and_replies_fixed(monkeypatch, bl_key):
    conn, opened = _db(monkeypatch, [_stored(C1)])
    _no_llm(monkeypatch)
    agent, run = _agent_calls()
    r = svc.handle(f"{C1} 어디쯤이야?", "s1", None, run)  # user_id 없음
    assert r.reply == svc.CONTAINER_NEED_LOGIN and agent == [] and opened == []


def test_without_database_url_is_not_found(monkeypatch, bl_key):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(svc, "connect", lambda *a, **k: pytest.fail("DB에 붙으면 안 된다"))
    _no_llm(monkeypatch)
    agent, run = _agent_calls()
    assert svc.handle(f"{C1} 어디야", "s1", None, run, user_id="u1").reply == svc.CONTAINER_NOT_FOUND


def test_not_logged_in_with_bl_masks_container_token(monkeypatch):
    """B/L이 같이 있으면 평소처럼 B/L을 조회하고, 컨테이너는 [CNTR1]로 가려서 LLM에 간다."""
    calls = _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]"})])
    agent, run = _agent_calls()
    svc.handle(f"{C1} 이거 {BL} 맞아?", "s1", None, run)
    assert calls[0]["masked"] == "[CNTR1] 이거 [BL1] 맞아?"
    assert C1 not in str(calls) and agent[0].bl_no == BL


# ── 기록 가리기 ──

def test_history_turns_mask_containers(monkeypatch):
    calls = _agent(monkeypatch, [], ["안녕하세요"])
    history = [{"role": "user", "text": f"{C1} 어디야?"}, {"role": "assistant", "text": f"{C2} 는 모릅니다"}]
    _, run = _agent_calls()
    svc.handle("고마워", "s1", None, run, history=history)
    texts = [t["text"] for t in calls[0]["history"]]
    assert texts == ["[CNTR1] 어디야?", "[CNTR1] 는 모릅니다"]  # B/L 가리기에 먼저 걸려 [BL1]이 되지 않는다
    assert C1 not in str(calls) and C2 not in str(calls)
    assert svc._masked_history(history, {})[0]["text"] == "[CNTR1] 어디야?"


# ── 컨테이너 모양인데 실제로는 B/L (보완: B/L을 넣었는데 "못 찾음"이 뜨면 안 된다) ──

def test_container_shaped_bl_in_customs_goes_to_bl_flow(monkeypatch, bl_key):
    """내 화물에 없는 컨테이너 모양 번호가 세관에 B/L로 있으면, 막지 않고 B/L로 조회한다. LLM에는 [BL1]로만 간다"""
    _db(monkeypatch, [])
    asked = []
    monkeypatch.setattr(svc.bl_parse, "exists_in_customs", lambda bl: asked.append(bl) or bl == C1)
    calls = _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]"})])
    agent, run = _agent_calls()
    r = svc.handle(f"{C1} 어디쯤이야?", "s1", None, run, user_id="u1")
    assert r.reply != svc.CONTAINER_NOT_FOUND and len(agent) == 1 and agent[0].bl_no == C1
    assert calls[0]["masked"] == "[BL1] 어디쯤이야?" and C1 not in str(calls)
    assert C1 in asked  # 세관에 물어봤다


def test_not_logged_in_container_shaped_bl_in_customs_goes_to_bl_flow(monkeypatch):
    """로그인 안 해도 같다. 세관에 B/L로 있으면 로그인 안내 대신 조회한다"""
    monkeypatch.setattr(svc.bl_parse, "exists_in_customs", lambda bl: bl == C1)
    _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]"})])
    agent, run = _agent_calls()
    r = svc.handle(f"{C1} 어디쯤이야?", "s1", None, run)
    assert r.reply != svc.CONTAINER_NEED_LOGIN and len(agent) == 1 and agent[0].bl_no == C1


def test_found_in_my_cargo_does_not_ask_customs(monkeypatch, bl_key):
    """내 화물에서 찾으면 세관에 따로 묻지 않는다 (UNI-PASS 호출을 늘리지 않는다)"""
    _db(monkeypatch, [_stored(C1)])
    monkeypatch.setattr(svc.bl_parse, "exists_in_customs", lambda bl: pytest.fail("세관에 물으면 안 된다") if bl == C1 else False)
    _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]"})])
    agent, run = _agent_calls()
    svc.handle(f"{C1} 어디쯤이야?", "s1", None, run, user_id="u1")
    assert agent[0].bl_no == BL
