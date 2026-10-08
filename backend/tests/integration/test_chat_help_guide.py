"""채팅 에이전트 결정 A~F 테스트 (services/chat/chat.py, prompts/marvia-chat-agent.md, services/judge/bl_parse.py 연결).
A 인사 · B 사용법(코드 고정 문장)·고정 안내 · C 상황 설명 · D 통관 시기 · E 여러 B/L 비교 문장(프롬프트) · F B/L 고쳐 읽기·붙은 번호.
LLM·판정 흐름은 test_chat_agent.py의 가짜를 쓴다. B/L은 모의값이다."""
import pytest

from backend.app.routers.agent import NO_CARGO, _response
from backend.app.schemas.agent import AgentRequest
from backend.app.services.judge import bl_parse
from backend.app.services import llm
from backend.app.services.chat import chat as svc
from backend.tests.integration.test_chat_agent import _agent, _out, agent_path  # noqa: F401 (fixture)
from backend.app.services import llm_schemas

CTX = AgentRequest(bl_no="TESTBL01", bl_type="HOUSE", session_id="old")


def kind(reply="", answer_kind="unrelated"):
    return (reply, answer_kind, "")


# ── A·B 인사와 사용법 ──

@pytest.mark.parametrize("ctx", [None, CTX])
def test_greeting_is_code_sentence_without_bl_request(monkeypatch, ctx):
    calls = _agent(monkeypatch, [], [kind("", "greeting")])
    r = svc.handle("안녕!", "s1", ctx, lambda req: None)
    assert r.reply == svc.GREETING_REPLY and "B/L" not in r.reply and len(calls) == 1  # 화물이 화면에 있어도 다시 묻지 않는다


@pytest.mark.parametrize("ctx", [None, CTX])
def test_help_returns_usage_guide_from_code(monkeypatch, ctx):
    calls = _agent(monkeypatch, [], [kind("마르비아는 사진도 찍어 드려요", "help")])  # LLM이 쓴 글은 버린다
    r = svc.handle("어떻게 쓰는 거야?", "s1", ctx, lambda req: None)
    assert r.reply == svc.USAGE_GUIDE and "사진도 찍어" not in r.reply and len(calls) == 1
    assert "TESTBL" not in r.reply  # 예시에 테스트 B/L을 쓰지 않는다


def test_fallback_points_to_guide_not_only_bl():
    assert "어떻게 써" in svc.OTHER_REPLY and "문장에 넣어 주세요" not in svc.OTHER_REPLY
    assert svc.NEED_BL.startswith("조회할 B/L 번호")  # 진짜 B/L이 필요한 자리(check_cargo)는 그대로


def test_kinds_include_help_and_greeting():
    assert {"help", "greeting"} <= set(llm_schemas.CHAT_AGENT_KINDS)
    llm.ChatAgentOutput(reply="", answer_kind="help")


# ── C 상황 설명은 unrelated가 아니다 ──

def test_situation_without_bl_gets_general_answer_with_tag(monkeypatch):
    _agent(monkeypatch, [], [kind("포워더 말고 선사에도 도착 통지서를 요청해 보세요.", "general")])
    r = svc.handle("B/L도 없고 포워더는 연락이 안 되는데 뭘 할 수 있을까?", "s1", None, lambda req: None)
    assert "일반 설명이에요" not in r.reply and r.reply != svc.OTHER_REPLY  # 꼬리표 없음


def test_prompt_says_situation_is_not_unrelated():
    text = open("backend/app/prompts/marvia-chat-agent.md", encoding="utf-8").read()
    assert "is NOT unrelated" in text and "B/L도 없고 포워더는 연락이 안 되는데" in text
    assert "answer_kind to help" in text and "answer_kind to greeting" in text


# ── D 통관 시기 ──

@pytest.mark.parametrize("q", ["통관 며칠 걸려?", "언제 통관돼?", "언제 반출돼?", "통관 얼마나 걸려요"])
def test_clearance_timing_regex_matches(q):
    assert svc.CLEARANCE_TIMING.search(q)


@pytest.mark.parametrize("q", ["안녕", "B/L 번호는 어디에 있어?", "관세는 얼마야?"])
def test_clearance_timing_regex_ignores_others(q):
    assert not svc.CLEARANCE_TIMING.search(q)


def test_clearance_timing_with_cargo_calls_ask_cargo(monkeypatch):
    # 첫 답은 도구 없는 일반 설명. 화물이 화면에 있으니 코드가 ask_cargo를 부르라고 다시 묻고, 두 번째에 부른다
    calls = _agent(monkeypatch, [], [kind("보통 서류 심사가 끝나면 반출돼요.", "general"), kind("", "tool")],
                   retry_script=[("ask_cargo", {"question": "통관은 어디까지 진행됐나요?"})])
    asked = []

    def run(req):
        asked.append(req.follow_up_question)
        return _response(status="ok", answer="지금은 수입신고 수리 단계입니다.")
    r = svc.handle("통관 며칠 걸려?", "s1", CTX, run)
    assert asked == ["통관은 어디까지 진행됐나요?"] and r.reply == "지금은 수입신고 수리 단계입니다."
    assert calls[1]["feedback"].startswith("TOOL:") and "customs stage" in calls[1]["feedback"]


def test_clearance_timing_without_cargo_uses_clearance_tag(monkeypatch):
    _agent(monkeypatch, [], [kind("서류 심사가 끝나면 반출할 수 있어요.", "general")])
    r = svc.handle("언제 반출돼?", "s1", None, lambda req: None)
    assert r.reply == "서류 심사가 끝나면 반출할 수 있어요." and "일반 설명이에요" not in r.reply


# ── E 여러 B/L 비교 문장 ──

def test_prompt_allows_one_comparison_sentence_after_cargos():
    text = open("backend/app/prompts/marvia-chat-agent.md", encoding="utf-8").read()
    assert 'check_cargo returned "cargos"' in text and "ONE Korean sentence" in text


# ── CARGO_TALK 좁히기, 로그 ──

def test_cargo_talk_only_counts_where_attached_to_cargo_words():
    assert not svc.CARGO_TALK.search("B/L 번호는 어디에 있는 거야?")
    for q in ("내 화물 어디쯤이야?", "이 배 어디에 있어?", "그 배는 어디야", "[BL1] 알려줘"):
        assert svc.CARGO_TALK.search(q), q


# ── F B/L 고쳐 읽기와 붙은 번호 ──

def _exists(monkeypatch, known):
    monkeypatch.setattr(bl_parse, "exists_in_customs", lambda bl: bl in known)


def test_repaired_bl_is_looked_up_masked_and_note_appended(monkeypatch):
    _exists(monkeypatch, {"TESTBL01"})
    calls = _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]"})])
    seen = []

    def run(req):
        seen.append(req.bl_no)
        return _response(status="ok", answer="괜찮습니다")
    r = svc.handle("test-bl-01 괜찮아?", "s1", None, run)
    assert seen == ["TESTBL01"] and r.reply.endswith(bl_parse.NOTE_SYMBOL)
    assert "TESTBL" not in str(calls).upper() and "test-bl" not in str(calls)  # LLM에는 토큰만


def test_unverified_candidate_changes_nothing(monkeypatch):
    _exists(monkeypatch, set())
    calls = _agent(monkeypatch, [], [kind("", "clarify")])
    r = svc.handle("test-bl-01 괜찮아?", "s1", None, lambda req: None)
    assert bl_parse.NOTE_SYMBOL not in r.reply and "test-bl-01" in calls[0]["masked"]  # 문장은 그대로


def test_glued_bls_split_and_looked_up_as_multi(monkeypatch):
    _exists(monkeypatch, {"TESTBL01", "TESTBL26"})
    calls = _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]"})])
    seen = []

    def run(req):
        seen.append(req.bl_no)
        if req.bl_no == "TESTBL01TESTBL26":
            return _response(status="insufficient", answer=NO_CARGO)
        return _response(status="ok", answer=f"{req.bl_no[-2:]}번 답")
    r = svc.handle("TESTBL01TESTBL26 둘 중 뭐가 먼저 와?", "s1", None, run)
    assert sorted(set(seen)) == ["TESTBL01", "TESTBL01TESTBL26", "TESTBL26"]  # 붙은 번호는 하우스·마스터 둘 다 본다
    assert [c["bl_no"] for c in r.cargos] == ["TESTBL01", "TESTBL26"] and bl_parse.NOTE_GLUED in r.reply
    result = calls[0]["tool_calls"][0]["result"]
    assert [c["bl_ref"] for c in result["cargos"]] == ["[BL2]", "[BL3]"]  # 나눈 번호도 새 토큰으로만 LLM에 간다
    assert "TESTBL" not in str(calls).upper() and "TESTBL" not in r.reply.upper()


def test_glued_not_found_without_split_keeps_normal_answer(monkeypatch):
    _exists(monkeypatch, set())
    _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]"})])
    r = svc.handle("TESTBL01TESTBL26 조회", "s1", None, lambda req: _response(status="insufficient", answer=NO_CARGO))
    assert svc.NO_RESULT_BOTH in r.reply and not r.cargos  # 판정 흐름 문구(~습니다)는 채팅에서 ~요로 나간다
