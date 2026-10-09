# 0006. 외부 데이터 도구는 MCP 서버로 노출하고 서비스도 /mcp로 부른다

상태: 채택

## 맥락
위치(ShipFinder), 입항 일정(해수부), 거리(searoute) 같은 실시간 데이터가 필요하다. 후속 질문과 채팅 에이전트는 LLM이 읽기 전용 도구를 골라 쓴다.

## 결정
- `mcp_server/`에 FastMCP(Streamable HTTP, `/mcp`)로 읽기 전용 도구 4개(get_vessel_candidates, get_live_position, get_port_schedule, estimate_distance)를 둔다. 판정과 freshness 계산은 하지 않는다.
- 서비스(`routers/agent.py`, `routers/chat.py`)도 `services/mcp_client.py`로 `/mcp`를 거쳐 부른다. 외부 MCP 클라이언트(Claude Desktop 등)와 같은 창구다.
- 도구는 예외를 던지지 않고 `{error: {code, message, retryable}}`을 돌려준다. 모든 응답에 source와 fetched_at을 붙인다.
- 인증 (`mcp_server/auth.py`): `MCP_TOKEN`이 있으면 Bearer 토큰이 같아야 한다. 비어 있으면 재생 모드에서는 열고, 실제 모드에서는 같은 컨테이너 안(루프백) 요청만 받는다.
- 동기 도구 함수는 스레드에서 돌려 API 서버 전체가 멈추지 않게 한다.

## 대안
- 서비스가 도구 함수를 직접 호출: 처음 구현이다. 외부 클라이언트와 같은 창구를 쓰려고 바꿨다 ([SDD](../Marvia_SDD.md) "부록. 계획 대비 변경" 표 서비스의 MCP 호출 행).

## 결과
- 좋아진 것: 서비스와 외부 클라이언트가 한 경로를 쓴다. 배포 주소에서 토큰이 있으면 도구 4개가 보이고, 토큰이 없으면 401이다 ([docs/evidence/mcp-02-deployed-tools.txt](../evidence/mcp-02-deployed-tools.txt)).
- 대가: 인증, Host 검사, 스레드 처리 같은 운영 규칙이 늘었다 ([SDD 5.9절](../Marvia_SDD.md)).

## 근거
- [SDD](../Marvia_SDD.md) 3.4절, 5.9절
- [CLAUDE.md](../../CLAUDE.md) "할 것": "MCP 도구는 예외를 던지지 않고 {error: {code, message, retryable}}을 돌려준다", "모든 도구 응답에 source와 fetched_at을 붙이고 evidence로 남긴다"
- 커밋 `fb434f9`(서비스가 /mcp로 호출), `3d44b69`(동기 도구를 스레드에서 실행)
- 테스트: `mcp_server/tests/`, `backend/tests/unit/test_mcp_client.py`, `backend/tests/integration/test_mcp_mount.py`
