"""채팅 에이전트 버그 두 개 (버그 찾기, services/chat/chat.py _agent).
1) 한 문장에 B/L이 2~3개: 모두 병렬로 조회해 표(cargos)로 돌려준다. 4개 이상이면 앞 셋과 코드 안내.
2) 화물 답과 LLM 문장이 같은 문장을 되풀이하면 LLM 문장을 버린다.
LLM·MCP는 test_chat_agent.py의 가짜를 그대로 쓴다."""
import pytest

from backend.app.routers.agent import _response
from backend.app.services.chat import chat as svc
from backend.tests.integration.test_chat import _agent_calls
from backend.tests.integration.test_chat_agent import _agent, _mcp

CHECK = [("check_cargo", {"bl_ref": "[BL1]", "bl_type": "MASTER"})]


def _two_run():
    """B/L마다 다른 배·도착일·판정을 돌려주는 가짜 판정 흐름. 일꾼 스레드에서도 단계 소식이 나가는지 보려고 step도 부른다."""
    from datetime import datetime, timezone
    from backend.app.schemas.agent import EtaInfo, VesselInfo
    from backend.app.services.chat import progress
    seen = []

    def run(req):
        seen.append(req)
        progress.step("customs")
        n = int(req.bl_no[-2:])
        eta = EtaInfo(ais_eta=None, mof_eta=None, calc_eta=None, trusted_eta=datetime(2026, 10, 5 + n, tzinfo=timezone.utc), distance_nm=None)
        vessel = VesselInfo(mmsi=440000000 + n, imo=None, name=f"SHIP{n}", call_sign=None, flag=None, ship_type=None, voyage_no=None)
        return _response(status="ok", verdict="fine" if n == 1 else "watch", days_margin=n, answer=f"{n}번 화물 답", eta=eta, vessel=vessel)
    return seen, run


def test_two_bls_look_up_both_and_return_table(monkeypatch):
    calls = _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]", "sale_due_date": "2026-10-11", "forwarder_eta": "2026-10-09", "voyage_no": "V1"})])
    seen, run = _two_run()
    r = svc.handle("TESTBL01이랑 TESTBL02 중에 뭐가 더 빨리 와? 판매예정일 2026-10-11", "s1", None, run)
    assert sorted(x.bl_no for x in seen) == ["TESTBL01", "TESTBL02"]  # 둘 다 조회
    assert all(str(x.sale_due_date) == "2026-10-11" for x in seen)  # 판매일은 모두에게
    assert all(x.forwarder_eta is None and x.voyage_no is None for x in seen)
    assert [c["bl_no"] for c in r.cargos] == ["TESTBL01", "TESTBL02"]  # 문장에 나온 순서
    assert [c["ship_name"] for c in r.cargos] == ["SHIP1", "SHIP2"] and [c["days_margin"] for c in r.cargos] == [1, 2]
    assert r.request.bl_no == "TESTBL01" and r.agent is r.cargos[0]["agent"]  # 다음 문장의 문맥과 오른쪽 칸은 첫 B/L
    assert r.map is None and "2건" in r.reply and svc.MULTI_BL_NOTICE not in r.reply
    # LLM에는 토큰 요약만 간다
    result = calls[0]["tool_calls"][0]["result"]
    assert [c["bl_ref"] for c in result["cargos"]] == ["[BL1]", "[BL2]"]
    assert "TESTBL" not in str(calls).upper()
    assert "TESTBL" not in r.reply.upper()


def test_three_bls_ok_four_bls_cut_to_three_with_notice(monkeypatch):
    calls = _agent(monkeypatch, CHECK)
    seen, run = _two_run()
    r = svc.handle("TESTBL01 TESTBL02 TESTBL03 TESTBL04 비교해줘", "s1", None, run)
    assert [x.bl_no for x in sorted(seen, key=lambda x: x.bl_no)] == ["TESTBL01", "TESTBL02", "TESTBL03"]  # 앞 셋만
    assert len(r.cargos) == 3 and svc.MULTI_BL_NOTICE in r.reply and "최대 세 개" in r.reply
    assert "TESTBL" not in str(calls).upper() and "TESTBL" not in r.reply.upper()


def test_valid_llm_sentence_is_used_and_bad_one_falls_back_to_lead(monkeypatch):
    _agent(monkeypatch, CHECK, ["두 화물 모두 살펴봤고 첫 화물이 더 빨리 옵니다."])
    _, run = _two_run()
    r = svc.handle("TESTBL01 TESTBL02 어느 게 더 빨리 와?", "s1", None, run)
    assert r.reply.startswith("두 화물 모두 살펴봤고") and len(r.cargos) == 2
    _agent(monkeypatch, CHECK, ["TESTBL01이 9월 3일에 옵니다. 99노트로 달립니다."])  # 근거 없는 숫자: 검사에 걸린다
    r = svc.handle("TESTBL01 TESTBL02 어느 게 더 빨리 와?", "s1", None, run)
    assert "99" not in r.reply and "2건" in r.reply and len(r.cargos) == 2  # 표만 답

    _agent(monkeypatch, CHECK, ["[BL1] 화물이 [BL2] 화물보다 더 빨리 옵니다."])  # 화면 문장엔 번호표 대신 사용자가 쓴 B/L
    r = svc.handle("TESTBL01 TESTBL02 어느 게 더 빨리 와?", "s1", None, run)
    assert r.reply.startswith("TESTBL01 화물이 TESTBL02 화물보다") and "[BL" not in r.reply


def test_one_failed_lookup_keeps_the_others(monkeypatch):
    _agent(monkeypatch, CHECK)
    _, run2 = _two_run()

    def run(req):
        if req.bl_no.endswith("02"):
            raise RuntimeError("boom")
        return run2(req)
    r = svc.handle("TESTBL01 TESTBL02 알려줘", "s1", None, run)
    assert r.kind == "cargo" and r.cargos == [] and r.request.bl_no == "TESTBL01"  # 한 건만 남으면 단일 답
    assert svc.MULTI_FAILED_NOTICE in r.reply


def test_stage_events_stream_from_worker_threads(monkeypatch):
    from backend.app.services.chat import progress
    _agent(monkeypatch, CHECK)
    _, run = _two_run()
    got = []
    with progress.listening(got.append):
        svc.handle("TESTBL01 TESTBL02 알려줘", "s1", None, run)
    assert got.count("customs") == 2  # 일꾼 스레드의 단계 소식도 이 요청의 듣는 쪽으로 온다


def test_single_bl_unchanged_has_no_cargos(monkeypatch):
    _agent(monkeypatch, CHECK)
    agent, run = _agent_calls()
    r = svc.handle("TESTBL01 괜찮아?", "s1", None, run)
    assert r.cargos == [] and len(agent) == 1 and svc.MULTI_BL_NOTICE not in r.reply
    from backend.app.routers.chat import ChatResponse
    assert ChatResponse(**r.__dict__).cargos == []


def test_chat_response_accepts_cargo_rows(monkeypatch):
    from backend.app.routers.chat import ChatResponse
    _agent(monkeypatch, CHECK)
    _, run = _two_run()
    r = svc.handle("TESTBL01 TESTBL02 알려줘", "s1", None, run)
    body = ChatResponse(**r.__dict__).model_dump(mode="json")
    assert body["cargos"][0]["sale_due_date"] is None
    assert len(body["cargos"]) == 2 and body["cargos"][1]["request"]["bl_no"] == "TESTBL02" and body["cargos"][0]["eta"]


def test_llm_sentence_repeating_cargo_reply_is_dropped(monkeypatch):
    ask = "같은 이름의 배가 여러 척입니다. 항차 번호나 입항 예정일로 가릅니다."
    script = CHECK + [("get_live_position", {"mmsi": 440999001})]
    _, run_tool = _mcp(monkeypatch)
    run = lambda req: _response(status="ok", answer=ask)
    _agent(monkeypatch, script, [ask])
    r = svc.handle("TESTBL04 판매예정일 2026-09-28", "s1", None, run, run_tool=run_tool)
    assert r.reply.count("같은 이름의 배가 여러 척입니다") == 1


def test_repeats_reply_ignores_spacing_and_short_overlap():
    assert svc._repeats_reply("같은 이름의  배가 여러 척입니다.", ["같은 이름의 배가\n여러 척입니다. 확인하세요"])
    assert not svc._repeats_reply("지금 속력은 12.3노트입니다.", ["괜찮습니다"])
    assert not svc._repeats_reply("괜찮습니다.", ["괜찮습니다"])  # 12자 미만은 우연히 겹칠 수 있다
