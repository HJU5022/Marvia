# 0006. 외부 데이터 도구는 MCP 서버로 노출하고 서비스도 /mcp로 부른다

상태: 채택 · 날짜: 2026-10-02 (서비스가 /mcp를 호출하도록 바꾼 커밋 fb434f9)

## 맥락
위치(ShipFinder), 입항 일정(해수부), 거리(searoute) 같은 실시간 데이터가 필요하다. 후속 질문과 채팅 에이전트는 LLM이 읽기 전용 도구를 골라 쓴다.

## 결정
- `mcp_server/`에 FastMCP(Streamable HTTP, `/mcp`)로 도구 4종을 둔다. 판정, freshness 계산은 하지 않는다.
- 서비스(`routers/agent.py`, `routers/chat.py`)도 `services/mcp_client.py`로 `/mcp`를 거쳐 부른다. 처음엔 도구 함수를 직접 불렀다. 외부 MCP 클라이언트(Claude Desktop 등)와 같은 창구가 된다.
- 도구는 예외를 던지지 않고 `{error: {code, message, retryable}}`을 돌려준다. 모든 응답에 source와 fetched_at을 붙인다.
- `MCP_TOKEN`이 있으면 Bearer 인증이 필요하고, 없으면 REPLAY_MODE일 때만 열거나 루프백만 받는다.
- 동기 도구 함수는 스레드에서 돌려 API 서버 전체가 멈추지 않게 한다 (같은 날 수정 3d44b69).

## 대안
- 도구 함수를 서비스에서 직접 호출: 처음 구현. 바꾼 이유는 SDD가 "같은 창구"라고만 적고 있다.

## 결과
좋아진 것: 서비스와 외부 클라이언트가 한 경로를 쓴다. 대가: 인증과 Host 검사, 스레드 처리 같은 운영 규칙이 늘었다 (SDD 5.9절).

## 근거
- `docs/Marvia_SDD.md` 3.4절, 5.9절
- `CLAUDE.md` "할 것" 4번째 항목
- 테스트: `mcp_server/tests/`, `backend/tests/unit/test_mcp_client.py`, `test_mcp_mount.py`
