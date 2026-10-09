"""채팅 응답의 미니 지도 자료 테스트 (services/chat/chat._map_payload, routers/chat.ChatMap).

에이전트가 이번 문장에서 선박 실시간 위치를 실제로 조회했을 때만 map이 붙고, 좌표는 도구 결과에서만 온다.
LLM·MCP·판정 흐름은 부르지 않는다: llm.chat_agent와 run_tool을 가짜로 끼운다 (test_chat_agent.py와 같은 방식).
선명·좌표는 모두 모의값이다.
"""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import chat as chat_router
from backend.app.routers.agent import _response
from backend.app.schemas.agent import AgentRequest, Evidence, EtaInfo, VesselInfo
from backend.app.services.chat import chat as svc
from backend.tests.integration.test_chat_agent import MCP_TOOLS, _agent, _mcp  # noqa: F401 - autouse 픽스처(agent_path)도 같이 쓴다
from backend.tests.integration.test_chat_agent import agent_path  # noqa: F401
from backend.tests.integration.test_chat import _agent_calls

# get_live_position 실제 필드 이름 (mcp_server/schemas.py LivePositionResult)에 맞춘 모의 결과
POSITION = {"mmsi": 440999001, "lat": 35.123, "lng": 129.456, "sog": 12.3, "last_time": "2026-10-05T01:02:03Z",
            "source": "shipfinder", "fetched_at": "2026-10-05T01:05:00+00:00"}
DISTANCE = {"distance_nm": 42.5, "source": "searoute", "fetched_at": "2026-10-05T01:05:00+00:00"}
CTX = AgentRequest(bl_no="TESTBL01", bl_type="HOUSE", session_id="old")


def _vessel():
    return VesselInfo(mmsi=440999001, imo=None, name="TEST STAR", call_sign=None, flag=None, ship_type=None, voyage_no=None)


def _cards(now=None):
    """후속 답이 get_live_position을 썼을 때 routers/agent._tool_evidence가 붙이는 카드 모양."""
    at = now or datetime.now(timezone.utc)
    return [Evidence(source="shipfinder", field="get_live_position.lat", value="35.123", fetched_at=at),
            Evidence(source="shipfinder", field="get_live_position.lng", value="129.456", fetched_at=at),
            Evidence(source="shipfinder", field="get_live_position.last_time", value="2026-10-05T01:02:03Z", fetched_at=at)]


def test_direct_live_position_sets_map_with_exact_coords(monkeypatch):
    _mcp(monkeypatch)
    _agent(monkeypatch, [("get_live_position", {"mmsi": 440999001})], ["위치를 확인했습니다"])
    r = svc.handle("그 배 지금 어디야", "s1", None, lambda req: None, run_tool=lambda n, a: POSITION)
    assert r.map == {"lat": 35.123, "lng": 129.456, "ship_name": None, "distance_nm": None,
                     "received_at": "2026-10-05T01:02:03Z", "source": "shipfinder"}


def test_direct_position_with_distance_tool_in_same_turn(monkeypatch):
    _mcp(monkeypatch)
    distance_tool = {"type": "function", "function": {"name": "estimate_distance", "description": "distance to Busan",
                                                      "parameters": {"type": "object", "properties": {}}}}
    monkeypatch.setattr(svc.mcp_client, "read_only_tools", lambda: MCP_TOOLS + [distance_tool])
    _agent(monkeypatch, [("get_live_position", {"mmsi": 440999001}), ("estimate_distance", {"lat": 35.123, "lng": 129.456})])
    r = svc.handle("그 배 어디야, 부산까지 얼마나", "s1", None, lambda req: None,
                   run_tool=lambda n, a: POSITION if n == "get_live_position" else DISTANCE)
    assert r.map["distance_nm"] == 42.5 and r.map["lat"] == 35.123


def test_ask_cargo_follow_up_that_used_position_sets_map(monkeypatch):
    _mcp(monkeypatch)
    _agent(monkeypatch, [("ask_cargo", {"question": "지금 어디쯤이야?"})])
    resp = _response(status="ok", answer="부산 근처입니다", vessel=_vessel(),
                     eta=EtaInfo(ais_eta=None, mof_eta=None, calc_eta=None, trusted_eta=None, distance_nm=30.0),
                     evidence=_cards())
    r = svc.handle("지금 어디쯤이야?", "s1", CTX, lambda req: resp)
    assert r.map == {"lat": 35.123, "lng": 129.456, "ship_name": "TEST STAR", "distance_nm": 30.0,
                     "received_at": "2026-10-05T01:02:03Z", "source": "shipfinder"}


def test_ask_cargo_stale_position_cards_from_earlier_turn_are_ignored(monkeypatch):
    _mcp(monkeypatch)
    _agent(monkeypatch, [("ask_cargo", {"question": "언제 와?"})])
    old = datetime(2026, 10, 4, tzinfo=timezone.utc)  # 지난 문장 후속 답의 카드가 저장돼 다시 온 경우
    resp = _response(status="ok", answer="내일 옵니다", vessel=_vessel(), evidence=_cards(old))
    assert svc.handle("언제 와?", "s1", CTX, lambda req: resp).map is None


def test_ask_cargo_without_position_tool_has_no_map(monkeypatch):
    _agent(monkeypatch, [("ask_cargo", {"question": "통관 어디까지 됐어?"})])
    resp = _response(status="ok", answer="신고 단계입니다", vessel=_vessel())
    assert svc.handle("통관 어디까지?", "s1", CTX, lambda req: resp).map is None


def test_check_cargo_only_has_no_map(monkeypatch):
    _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]"})])
    agent, run = _agent_calls()
    assert svc.handle("TESTBL01 괜찮아?", "s1", None, run).map is None


def test_position_tool_error_has_no_map(monkeypatch):
    _mcp(monkeypatch)
    _agent(monkeypatch, [("get_live_position", {"mmsi": 440999001})])
    error = {"error": {"code": "upstream", "message": "down", "retryable": True}}
    r = svc.handle("그 배 어디야", "s1", None, lambda req: None, run_tool=lambda n, a: error)
    assert r.map is None


def test_api_chat_response_has_map_key(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr(svc.mcp_client, "read_only_tools", lambda: MCP_TOOLS)
    _agent(monkeypatch, [("get_live_position", {"mmsi": 440999001})])
    monkeypatch.setattr(chat_router, "_follow_up_tool", lambda n, a: POSITION)
    with TestClient(app) as client:
        body = client.post("/api/chat", json={"message": "그 배 어디야", "session_id": "s1"}).json()
        assert body["map"] == {"lat": 35.123, "lng": 129.456, "ship_name": None, "distance_nm": None,
                               "received_at": "2026-10-05T01:02:03Z", "source": "shipfinder"}
        _agent(monkeypatch, [])
        body = client.post("/api/chat", json={"message": "안녕", "session_id": "s1"}).json()
        assert "map" in body and body["map"] is None



def test_follow_up_answer_citing_stored_position_gets_map():
    """(c) 후속 답이 도구 없이 지난 결과의 위치를 말하면 그 좌표로 지도를 붙인다. 좌표를 말하지 않으면 붙이지 않는다."""
    from datetime import datetime, timezone
    from backend.app.routers.agent import _response
    from backend.app.schemas.agent import Position
    pos = Position(lat=34.5, lng=129.0, sog=12.0, cog=30.0, navistat=0, last_time=datetime(2026, 10, 5, 12, tzinfo=timezone.utc), freshness="fresh")
    said = svc.ChatResult(kind="cargo", reply="배의 마지막 수신 위치는 위도 34.5, 경도 129.0 부근입니다.",
                          agent=_response(status="ok", answer="x", position=pos))
    m = svc._map_payload([{"name": "ask_cargo", "arguments": {}, "result": {"answer": said.reply}}], [said], datetime.now(timezone.utc))
    assert m and m["lat"] == 34.5 and m["lng"] == 129.0 and m["received_at"].startswith("2026-10-05")
    quiet = svc.ChatResult(kind="cargo", reply="통관은 입항 신고 단계입니다.", agent=_response(status="ok", answer="x", position=pos))
    assert svc._map_payload([], [quiet], datetime.now(timezone.utc)) is None
