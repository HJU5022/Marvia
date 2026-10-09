"""UNI-PASS 처리 이력 원문(화면 전용) 테스트 (docs/specs/customs-detail.md). 키 없이 돈다.

지키는 것: 13칸을 그대로 화면 응답에 싣되, 판정 LLM 입력·이력 저장(DB)·후속 질문 LLM 입력에는 넣지 않는다.
XML 값은 모두 가공값이다 (실제 신고번호·관세법인명 아님).
"""
import contextlib
import json

import httpx
import pytest

from backend.app.routers import agent as agent_router
from backend.app.schemas.agent import AgentRequest, AgentResponse
from backend.app.schemas.customs import CustomsDetailRow
from backend.app.services import llm
from backend.app.services.judge.customs import UnipassClient
from backend.app.services.judge import saved as agent_saved

XML = """<?xml version="1.0" encoding="UTF-8"?><cargCsclPrgsInfoQryRtnVo><tCnt>1</tCnt>
<cargCsclPrgsInfoQryVo><shipNm>TEST STAR</shipNm><shipNat>PA</shipNat><cargMtNo>26TEST0099I00010001</cargMtNo>
<dsprCd>KRPUS</dsprCd><prnm>가공품명</prnm></cargCsclPrgsInfoQryVo>
<cargCsclPrgsInfoDtlQryVo><shedNm>테스트 터미널 CY</shedNm><prcsDttm>20260915065057</prcsDttm>
<dclrNo>TESTDCLR0001A</dclrNo><rlbrDttm>2026-09-15 06:40:48</rlbrDttm><wght>1720</wght><rlbrBssNo>테스트관세법인</rlbrBssNo>
<bfhnGdncCn>[부가사항] 테스트 장치기간 안내</bfhnGdncCn><wghtUt>KG</wghtUt><pckGcnt>2</pckGcnt>
<cargTrcnRelaBsopTpcd>반입신고</cargTrcnRelaBsopTpcd><pckUt>GT</pckUt><rlbrCn>입항 반입</rlbrCn><shedSgn>00000001</shedSgn>
</cargCsclPrgsInfoDtlQryVo>
<cargCsclPrgsInfoDtlQryVo><shedNm></shedNm><prcsDttm>20260914080655</prcsDttm><dclrNo>26TEST0099I</dclrNo>
<rlbrDttm></rlbrDttm><wght></wght><cargTrcnRelaBsopTpcd>입항보고 수리</cargTrcnRelaBsopTpcd><pckGcnt>0</pckGcnt>
</cargCsclPrgsInfoDtlQryVo></cargCsclPrgsInfoQryRtnVo>"""


def _record():
    client = UnipassClient(key="test-key", transport=httpx.MockTransport(lambda r: httpx.Response(200, text=XML)))
    return client.fetch("TESTMBL0000001")


def test_detail_rows_keep_all_columns_in_response_order():
    rows = _record().display_rows
    assert [r.kind for r in rows] == ["반입신고", "입항보고 수리"]  # 응답 순서(최신이 위) 그대로
    first = rows[0]
    assert (first.processed_at, first.declaration_no, first.moved_at) == ("20260915065057", "TESTDCLR0001A", "2026-09-15 06:40:48")
    assert (first.weight, first.weight_unit, first.package_count, first.package_unit) == ("1720", "KG", "2", "GT")
    assert (first.basis, first.content, first.shed_code) == ("테스트관세법인", "입항 반입", "00000001")
    assert first.notice == "[부가사항] 테스트 장치기간 안내"
    assert rows[1].weight is None and rows[1].shed_name is None  # 빈 칸은 None


def test_detail_rows_never_reach_judge_input():
    """CustomsRecord.display_rows는 exclude라 model_dump(판정 LLM 입력을 만드는 곳)에 안 나온다."""
    dumped = json.dumps(_record().model_dump(mode="json"), ensure_ascii=False)
    assert "display_rows" not in dumped
    assert "1720" not in dumped and "테스트관세법인" not in dumped


def _response_with_detail():
    row = CustomsDetailRow(kind="반입신고", weight="1720", weight_unit="KG", basis="테스트관세법인")
    return agent_router._response().model_copy(update={"customs_detail": [row]})


def test_detail_is_not_saved_to_history(monkeypatch):
    saved = {}
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(agent_router, "connect", lambda: contextlib.nullcontext(object()))
    monkeypatch.setattr(agent_router, "log_query", lambda conn, session_id, **kw: saved.update(kw))
    monkeypatch.setattr(agent_router, "_as_jsonb", lambda data: data)
    response = _response_with_detail()

    request = AgentRequest(bl_no="TESTBL01", bl_type="HOUSE", session_id="s1")
    assert agent_router._logged(request, response) is response  # 화면으로 나가는 응답에는 그대로 있다
    assert response.customs_detail
    assert "customs_detail" not in saved["response"]
    assert "1720" not in json.dumps(saved["response"], ensure_ascii=False)


def test_detail_is_not_sent_to_follow_up_llm(monkeypatch):
    sent = {}

    def fake_ask(prompt, user_content, *args, **kwargs):
        sent["content"] = user_content
        raise llm.LLMError("stop", kind="test")

    monkeypatch.setattr(llm, "_ask_json", fake_ask)
    try:
        llm.answer_follow_up("중량이 얼마야?", _response_with_detail())
    except llm.LLMError:
        pass
    assert "customs_detail" not in sent["content"]
    assert "1720" not in sent["content"] and "테스트관세법인" not in sent["content"]


def test_assess_attaches_detail_after_judging(monkeypatch):
    """판정이 끝난 응답에 화면 전용 원문을 붙인다. 판정 흐름(_after_customs)은 원문을 보지 않는다."""
    record = _record()
    seen = {}

    def fake_after(request, customs, memory=None):
        seen["response"] = agent_router._response(status="ok", answer="판정")
        return seen["response"]

    monkeypatch.setattr(agent_router, "_fetch_customs", lambda request: (record, None))
    monkeypatch.setattr(agent_router, "_after_customs", fake_after)
    out = agent_router._assess(AgentRequest(bl_no="TESTBL01", bl_type="HOUSE", session_id="s1"))
    assert not seen["response"].customs_detail
    assert [r.kind for r in out.customs_detail] == ["반입신고", "입항보고 수리"]


# ── 컨테이너 번호. B/L처럼 화물을 특정하는 번호라 후속 LLM과 평문 이력에 넣지 않는다 ──

def _response_with_container():
    from backend.app.schemas.agent import CustomsInfo
    customs = CustomsInfo(stage_code="X", stage_name="입항보고 수리", plain_explanation="모의 해설", next_stage=None,
                          needs_broker=False, forwarder_name="테스트포워딩", container_no="TCNU0000001")  # 모의값
    return agent_router._response().model_copy(update={"customs": customs})


def test_container_no_is_not_sent_to_follow_up_llm(monkeypatch):
    sent = {}

    def fake_ask(prompt, user_content, *args, **kwargs):
        sent["content"] = user_content
        raise llm.LLMError("stop", kind="test")

    monkeypatch.setattr(llm, "_ask_json", fake_ask)
    try:
        llm.answer_follow_up("포워더가 어디야?", _response_with_container())
    except llm.LLMError:
        pass
    # 원문 번호는 안 가고 [CNTR1] 번호표로만 간다 (llm.hide_containers). 칸 이름은 남아도 된다
    assert "TCNU0000001" not in sent["content"] and "[CNTR1]" in sent["content"]
    assert "테스트포워딩" in sent["content"]  # 포워더 이름은 후속 질문 재료라 남긴다


def test_container_no_is_not_saved_to_history(monkeypatch):
    saved = {}
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(agent_router, "connect", lambda: contextlib.nullcontext(object()))
    monkeypatch.setattr(agent_router, "log_query", lambda conn, session_id, **kw: saved.update(kw))
    monkeypatch.setattr(agent_router, "_as_jsonb", lambda data: data)
    response = _response_with_container()
    request = AgentRequest(bl_no="TESTBL01", bl_type="HOUSE", session_id="s1")
    assert agent_router._logged(request, response).customs.container_no == "TCNU0000001"  # 화면 응답에는 그대로
    assert "TCNU0000001" not in json.dumps(saved["response"], ensure_ascii=False)
    assert saved["response"]["customs"]["stage_name"]  # 다른 통관 칸은 그대로 남는다


def test_container_no_in_answer_text_is_not_saved_to_history(monkeypatch):
    """후속 답은 화면용으로 실제 번호를 되돌린 문장이다. 이력에는 그 문장 속 번호도 번호표로 저장한다.
    안 그러면 다음 후속 질문 때 이력의 답 문장이 원문 그대로 LLM에 간다"""
    saved = {}
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(agent_router, "connect", lambda: contextlib.nullcontext(object()))
    monkeypatch.setattr(agent_router, "log_query", lambda conn, session_id, **kw: saved.update(kw))
    monkeypatch.setattr(agent_router, "_as_jsonb", lambda data: data)
    response = _response_with_container().model_copy(update={"answer": "컨테이너 번호는 TCNU0000001입니다."})
    request = AgentRequest(bl_no="TESTBL01", bl_type="HOUSE", session_id="s1")
    assert agent_router._logged(request, response).answer == "컨테이너 번호는 TCNU0000001입니다."  # 화면에는 그대로
    stored = json.dumps(saved["response"], ensure_ascii=False)
    assert "TCNU0000001" not in stored and saved["response"]["answer"] == "컨테이너 번호는 [CNTR1]입니다."


# ── 이력의 컨테이너 번호는 잠가 두고 후속 질문이 읽을 때 푼다 (후속 질문도 번호를 알아야 한다) ──

@pytest.fixture
def bl_key(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("BL_ENCRYPTION_KEY", Fernet.generate_key().decode())


def test_history_seals_container_and_previous_response_opens_it(monkeypatch, bl_key):
    """저장된 이력에는 평문 번호가 없고, 후속 질문이 이력을 읽으면 원래 번호가 customs.container_no로 돌아온다"""
    saved = {}
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(agent_router, "connect", lambda: contextlib.nullcontext(object()))
    monkeypatch.setattr(agent_router, "log_query", lambda conn, session_id, **kw: saved.update(kw))
    monkeypatch.setattr(agent_router, "_as_jsonb", lambda data: data)
    request = AgentRequest(bl_no="TESTBL01", bl_type="HOUSE", session_id="s1")
    agent_router._logged(request, _response_with_container())

    stored = saved["response"]
    assert "TCNU0000001" not in json.dumps(stored, ensure_ascii=False) and stored[agent_saved.SEALED_CONTAINER_KEY]
    monkeypatch.setattr(agent_router, "recent_responses", lambda *a, **k: [(stored, None)])
    previous = agent_router._previous_response(request)
    assert previous.customs.container_no == "TCNU0000001"


def test_follow_up_from_history_knows_container_as_token(monkeypatch, bl_key):
    """이력에서 되살린 결과로 후속 질문을 하면 LLM은 [CNTR1]을 받는다. 번호를 '모르는' 상태가 아니다"""
    stored = agent_router._seal_containers(_response_with_container())
    sent = {}

    def fake_ask(prompt, user_content, *args, **kwargs):
        sent["content"] = user_content
        raise llm.LLMError("stop", kind="test")

    monkeypatch.setattr(llm, "_ask_json", fake_ask)
    with pytest.raises(llm.LLMError):
        llm.answer_follow_up("컨테이너 번호 뭐야?", AgentResponse.model_validate(agent_router._open_containers(stored)))
    assert "[CNTR1]" in sent["content"] and "TCNU0000001" not in sent["content"]


def test_history_without_key_drops_container_instead_of_plain_text(monkeypatch):
    """열쇠가 없으면 잠근 칸 없이 저장한다. 원문을 남기지 않는다"""
    monkeypatch.delenv("BL_ENCRYPTION_KEY", raising=False)
    stored = agent_router._seal_containers(_response_with_container())
    assert agent_saved.SEALED_CONTAINER_KEY not in stored and "TCNU0000001" not in json.dumps(stored, ensure_ascii=False)
    assert agent_router._open_containers(stored)["customs"].get("container_no") is None
