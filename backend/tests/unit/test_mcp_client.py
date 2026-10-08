"""서비스가 MCP 도구를 MCP 프로토콜로 부르는 곳 테스트 (services/mcp_client.py).

- MCP_URL이 없으면 메모리 통로로 붙고, 결과가 도구를 직접 부른 값과 같다
- None 인자는 빠지고, 도구가 돌려준 {error}는 그대로 온다
- 통로 자체가 실패해도 예외가 나지 않고 mcp_failed 오류 dict가 온다
- 입력 스키마 위반은 bad_input, 인증 실패(401)는 unauthorized로 오고 둘 다 retryable=False다
- 이벤트 루프가 이미 도는 곳(평가 실행기의 Langfuse 실험)에서 불러도 도구가 돈다
- 호출마다 Langfuse tool 관측에 이름·인자·결과 요약·통로·지연이 넘어가고, 키가 없으면 결과에 영향이 없다 (SDD 5.11)

키도 서버도 없이 돈다. HTTP 통로 실패는 아무도 듣지 않는 포트(9)로 확인한다.
"""
import asyncio

from backend.app.services import mcp_client
from mcp_server.tools.distance import estimate_distance as direct_estimate_distance


def _without_fetched_at(result: dict) -> dict:
    """부른 시각은 매번 달라서 비교에서 뺀다."""
    return {k: v for k, v in result.items() if k != "fetched_at"}


# 메모리 통로: MCP를 거친 결과가 파이썬으로 직접 부른 결과와 같아야 부르는 쪽 동작이 바뀌지 않는다
def test_memory_path_matches_direct_call(monkeypatch):
    monkeypatch.delenv("MCP_URL", raising=False)
    via_mcp = mcp_client.estimate_distance(34.5, 128.8, 12)
    direct = direct_estimate_distance(34.5, 128.8, 12)
    assert _without_fetched_at(via_mcp) == _without_fetched_at(direct)


# call_sign·ship_name을 안 주면 None이 빠진 채 가고, 도구가 돌려준 bad_input 오류가 그대로 와야 한다
def test_none_args_dropped_and_tool_error_passed_through(monkeypatch):
    monkeypatch.delenv("MCP_URL", raising=False)
    result = mcp_client.get_port_schedule()
    assert result["error"]["code"] == "bad_input"


# 이벤트 루프가 이미 도는 곳에서 불러도 도구가 돌아야 한다.
# 평가 실행기의 Langfuse run_experiment가 루프 안에서 문항을 돌려, asyncio.run이 RuntimeError를 내고 도구가 전부 mcp_failed였다
def test_call_inside_running_event_loop(monkeypatch):
    monkeypatch.delenv("MCP_URL", raising=False)
    monkeypatch.setattr(mcp_client, "_read_only_tools", None)

    async def inside_loop():
        return mcp_client.estimate_distance(34.5, 128.8, 12), mcp_client.read_only_tools()

    via_mcp, tools = asyncio.run(inside_loop())
    assert _without_fetched_at(via_mcp) == _without_fetched_at(direct_estimate_distance(34.5, 128.8, 12))
    assert len(tools) == 4


# 서버가 없는 주소로 붙어도 예외 대신 mcp_failed가 와야 서비스가 도구 실패와 같은 경로로 간다
def test_transport_failure_returns_error_dict(monkeypatch):
    monkeypatch.setenv("MCP_URL", "http://127.0.0.1:9/mcp")
    result = mcp_client.call_tool("estimate_distance", lat=34.5, lng=128.8)
    assert result["error"]["code"] == "mcp_failed"
    assert result["error"]["retryable"] is True


# 입력 스키마 위반(위도 999)은 다시 불러도 같으니 bad_input·retryable=False여야 한다 (전엔 mcp_failed·True)
def test_schema_violation_is_bad_input(monkeypatch):
    monkeypatch.delenv("MCP_URL", raising=False)
    result = mcp_client.estimate_distance(999, 999)
    assert result["error"]["code"] == "bad_input"
    assert result["error"]["retryable"] is False


# 토큰이 틀려 401이면 unauthorized·retryable=False여야 한다 (전엔 ExceptionGroup·mcp_failed·True).
# MCP 클라이언트가 HTTP 오류를 ExceptionGroup에 싸서 던지는 모양을 그대로 만들어 넣는다
def test_unauthorized_is_not_retryable(monkeypatch):
    import httpx
    request = httpx.Request("POST", "http://127.0.0.1/mcp")
    denied = httpx.HTTPStatusError("401", request=request, response=httpx.Response(401, request=request))
    assert mcp_client._transport_failed(ExceptionGroup("tg", [denied]))["error"] == {
        "code": "unauthorized", "message": "MCP 인증 실패 (401)", "retryable": False}
    assert mcp_client._transport_failed(ExceptionGroup("tg", [OSError()]))["error"]["retryable"] is True


# Langfuse 키가 없으면 트레이스는 빠지고 호출 결과는 그대로여야 한다 (테스트·REPLAY_MODE가 이 길을 탄다, SDD 5.11)
def test_call_works_without_langfuse_keys(monkeypatch):
    monkeypatch.delenv("MCP_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    via_mcp = mcp_client.call_tool("estimate_distance", lat=34.5, lng=128.8, sog=12)
    direct = direct_estimate_distance(34.5, 128.8, 12)
    assert _without_fetched_at(via_mcp) == _without_fetched_at(direct)


# tool 관측에 넘기는 값: 이름 mcp:<도구>, 인자, 원본이 아닌 요약(키 이름 또는 오류 코드), 통로, 지연 (SDD 5.11)
def test_tool_span_records_summary_not_raw(monkeypatch):
    monkeypatch.delenv("MCP_URL", raising=False)
    started, ended = [], []
    monkeypatch.setattr(mcp_client, "start_tool", lambda name, input: started.append((name, input)) or "span")
    monkeypatch.setattr(mcp_client, "end_tool",
                        lambda tool, output, metadata, error=None: ended.append((tool, output, metadata, error)))

    result = mcp_client.call_tool("estimate_distance", lat=34.5, lng=128.8)
    assert started == [("mcp:estimate_distance", {"lat": 34.5, "lng": 128.8})]
    tool, output, metadata, error = ended[0]
    assert tool == "span" and error is None
    assert output == {"ok": True, "keys": sorted(result.keys())}
    assert metadata["transport"] == "memory" and isinstance(metadata["latency_ms"], int)

    mcp_client.get_port_schedule()  # 도구가 bad_input을 돌려주는 경우: 오류 코드만 남는다
    _, output, _, error = ended[1]
    assert output == {"ok": False, "error": "bad_input"} and error == "bad_input"
