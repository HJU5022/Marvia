# MCP_GUIDE

FastMCP 서버. `backend/app/main.py`에 ASGI로 마운트되어 같은 프로세스에서 `/mcp`로 제공된다. 별도 실행 없음.

## 도구 7개

시그니처와 호출 API는 docs/SDD.md 6절이 기준이다.

| 도구 | 언제 쓰나 |
|---|---|
| `geocode` | 지명 텍스트를 좌표로. 기준 좌표 편향으로 동명 지명(서면: 부산/순천)을 가른다 |
| `search_places` | 좌표 주변에서 절차 시작점(위병소·정문·로비)이나 랜드마크(항만 입구·역)를 찾는다 |
| `route_car` | 자동차 경로·소요시간. 출발 시각이 있으면 미래 운행 |
| `route_transit` | 대중교통 경로·환승·요금 |
| `first_last_train` | 역의 첫차·막차. 서울 1~9호선, 부산 |
| `vessel_schedule` | 함정 프리셋에서 입항·출항 시각이 확정됐는지. 기록에 없으면 미확정 |
| `departure_calc` | 도착 기한, 소요시간, 여유, 절차 소요로 출발 시각 역산. 계산만 |

## 지킬 것

- `tools/` 파일 하나에 도구 하나. description 한 문장으로 언제 쓰는 도구인지 드러나야 한다. 모델은 그것만 보고 고른다
- 실제 API 호출 코드를 여기 다시 쓰지 않는다. `backend/app/services/`의 함수를 부른다
- 헤더 `Authorization: Bearer {MCP_TOKEN}` 없으면 거부. 브라우저는 `/mcp`를 직접 부르지 않는다
- 응답에 API 키를 싣지 않는다

## 제출 증거

`docs/evidence/mcp/`에 연결 스크린샷, tool 목록, 실제 호출 결과. 접근 제어 방식은 README에도 적는다 (가이드 요구).
