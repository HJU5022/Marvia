# mcp_server

외부 데이터 도구 4종을 MCP(FastMCP, Streamable HTTP)로 노출한다. 기본은 API 서버 안의 `/mcp` 경로이고, 서비스(`backend/app/services/mcp_client.py`)도 외부 MCP 클라이언트와 같은 이 창구로 도구를 부른다.

| 구분 | 내용 |
|---|---|
| 책임 | ShipFinder, 해수부, searoute 데이터를 원본 값과 `fetched_at`과 함께 돌려준다 |
| 하지 않는 것 | 판정, freshness 계산. 위치가 오래됐는지는 `services/judge/signals.py`가 정한다 |

## 파일

| 경로 | 역할 |
|---|---|
| `server.py` | FastMCP 서버(`create_mcp`)와 도구 4종 등록, 읽기 전용 표시. 동기 도구는 스레드에서 돌려 API 서버가 멈추지 않게 한다 |
| `auth.py` | `/mcp` Bearer 토큰 검사 |
| `schemas.py` | 도구 출력 계약 C4 (`ToolError`, `VesselCandidatesResult`, `LivePositionResult`, `PortScheduleResult`, `DistanceResult`) |
| `tools/` | 도구 본체 |
| `tests/` | pytest (`test_auth`, `test_distance`, `test_live_position`, `test_port_schedule`, `test_tool_descriptions`, `test_vessel_candidates`) |

## 도구 4종 (`tools/`)

| 도구 | 입력 | 돌려주는 것 | 출처 |
|---|---|---|---|
| `get_vessel_candidates` | `ship_name`, `nationality`, `eta_window_days`, `call_sign` | 선박 후보 목록(mmsi, imo, name, call_sign, flag, dest, last_time, ship_type, similarity). 후보를 좁히지 않는다 | ShipFinder |
| `get_live_position` | `mmsi` | lat, lng, sog, cog, navistat, dest, destcode, ais_eta, last_time, cached_at | ShipFinder |
| `get_port_schedule` | `call_sign`, `ship_name`, `lookback_days`, `lookahead_days` | planned_arrival, actual_arrival, facility(접안 시설), control_events | 해수부 |
| `estimate_distance` | `lat`, `lng`, `sog` | distance_nm(부산항까지 해리), calc_hours_at_sog | searoute (키 불필요) |

모든 응답에 `source`와 `fetched_at`이 붙는다.

## 인증과 오류

- `/mcp`는 `Authorization: Bearer <MCP_TOKEN>` 없이 부를 수 없다. `MCP_TOKEN`이 비었으면 `REPLAY_MODE`일 때만 열고, 아니면 같은 컨테이너 안(루프백)의 요청만 받는다(`auth.py` 상단 설명).
- 도구는 예외를 던지지 않고 `{error: {code, message, retryable}}`를 돌려준다(`schemas.py ToolError`).

## 실행과 테스트

```bash
pytest mcp_server/tests                                          # 키 없이
python -m mcp_server.server --port 8001                          # 따로 띄울 때 (기본 포트 8001)
python -m scripts.demo.mcp_check http://localhost:8000/mcp --token <MCP_TOKEN>   # API 서버 안의 /mcp 확인
```
