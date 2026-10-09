# mcp_server

외부 데이터 도구 4종을 MCP(FastMCP, Streamable HTTP)로 노출한다. 도구는 모두 읽기 전용이다. 판정과 freshness 계산은 하지 않는다. 위치가 오래됐는지는 `backend/app/services/judge/signals.py`가 정한다.

서버는 API 서버 안의 `/mcp` 경로에 붙는다(`backend/app/main.py`). 서비스도 같은 MCP 프로토콜로 도구를 부른다(`backend/app/services/mcp_client.py`).

| 서비스가 부르는 길 | 언제 |
|---|---|
| `MCP_URL`(`http://127.0.0.1:8000/mcp`)에 HTTP로 붙는다. 외부 MCP 클라이언트와 같은 길이고 인증도 거친다 | Docker 이미지로 띄운 api (`Dockerfile`, `Dockerfile.railway`가 `MCP_URL`을 넣는다. `Dockerfile.railway`는 포트를 `${PORT:-8000}`으로 맞춘다). compose의 worker는 `http://api:8000/mcp`를 부른다(`docker-compose.yml`) |
| 같은 프로세스 안의 MCP 서버에 메모리로 붙는다. HTTP와 인증만 빠진다 | `MCP_URL`이 없을 때 (테스트, 평가 실행기, 스크립트) |

## 파일

| 경로 | 역할 |
|---|---|
| `server.py` | FastMCP 서버(`create_mcp`)와 도구 4종 등록, 읽기 전용 표시(`readOnlyHint`). 동기 도구는 스레드에서 돌려 API 서버가 멈추지 않게 한다 |
| `auth.py` | `/mcp` Bearer 토큰 검사 |
| `schemas.py` | 도구 출력 계약 C4. 계약 설명은 [docs/Marvia_SDD.md](../docs/Marvia_SDD.md) 3.4절 |
| `tools/` | 도구 본체 4개 |
| `tests/` | pytest. 도구마다 한 파일과 `test_auth.py`, `test_tool_descriptions.py` |

## 도구 4종

| 도구 | 입력 | 돌려주는 것 | 출처 |
|---|---|---|---|
| `get_vessel_candidates` | `ship_name`, `nationality`, `eta_window_days`, `call_sign` | 선박 후보 목록. 후보마다 mmsi, imo, name, call_sign, flag, dest, last_time, ship_type, similarity | ShipFinder |
| `get_live_position` | `mmsi` | lat, lng, sog, cog, navistat, dest, destcode, ais_eta, last_time | ShipFinder |
| `get_port_schedule` | `call_sign`, `ship_name`, `lookback_days`, `lookahead_days` | planned_arrival, actual_arrival, facility(접안 시설), control_events | 해수부 |
| `estimate_distance` | `lat`, `lng`, `sog` | distance_nm(부산항까지 해리), calc_hours_at_sog | searoute (키 없음, 외부 호출 없음) |

- `get_vessel_candidates`는 후보를 하나로 좁히지 않는다. 어느 배인지는 서비스가 정한다.
- 정상 응답에는 `source`와 `fetched_at`이 붙는다. ShipFinder 도구는 빈도 초과로 캐시 값을 돌려줄 때 `cached_at`도 붙인다.
- 도구는 예외를 던지지 않고 `{error: {code, message, retryable}}`를 돌려준다(`schemas.py`의 `ToolError`).

## 인증

| `MCP_TOKEN` | `/mcp` 요청 |
|---|---|
| 있다 | `Authorization: Bearer <MCP_TOKEN>`이 맞아야 받는다. 없거나 틀리면 401. 배포에서는 반드시 채운다 |
| 비었고 `REPLAY_MODE=true` | 모두 받는다. 가공 응답만 읽어 키를 쓰지 않기 때문이다 |
| 비었고 실제 모드 | 같은 컨테이너 안(루프백 주소)에서 온 요청만 받는다. api가 자기 `/mcp`를 부르는 길이다. 나머지는 401 |

## 실행과 테스트

```bash
pytest mcp_server/tests                                                          # 키 없이
python -m mcp_server.server --port 8001                                          # 따로 띄울 때 (기본 포트 8001)
python -m scripts.demo.mcp_check http://localhost:8000/mcp --token <MCP_TOKEN>   # 연결과 도구 목록 확인
```

`scripts/demo/`에는 토큰 없이·틀린 토큰·맞는 토큰 세 경우를 불러 보는 `mcp_auth_check.py`와 도구 4종을 차례로 부르는 `mcp_demo.py`도 있다.
