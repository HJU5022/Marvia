# ShipFinder fixture

실제 응답과 형식만 같은 가공값이다 (CLAUDE.md "실제 응답 원본은 커밋하지 않는다", ShipFinder 이용 조건).
MMSI·IMO·선명·호출부호·좌표·시각 모두 실재하지 않는 값이다(MMSI 440999xxx, IMO 99000xx, 호출부호 TEST/TST, 좌표는 소수 1~2자리, 시각은 둥근 값).
응답 구조와 경계 사례만 남겼다. 공식 문서 예시를 본뜬 파일도 값은 바꿨다 (09-23 라이선스 점검).

| 파일 | 담은 경계 사례 |
|---|---|
| position_busan_anchored.json | 부산 북항 정박(sog 0, navistat 8). eta 필드 자체가 없음, hdg 511.0(무효, float) |
| position_ok.json | 항해 중, eta 있음 (공식 문서 예시 형식, 값은 가공) |
| search_same_name.json | 같은 선명 여럿, 같은 IMO에 MMSI 2개, 7자리가 아닌 IMO(300000001), imo 0 |
| search_same_imo.json | 같은 IMO에 MMSI 3개 (공식 문서 예시 형식, 값은 가공) |
| not_found.json, no_permission.json, rate_limited.json | status 3, 21, 29 |
| quota_exhausted.json | status 38 하루 호출 한도 소진 (10-06 점검, msg 문구는 가공) |

실제 응답이 필요하면 `scripts/demo/fetch_shipfinder.py`로 받아 로컬(.local/, gitignore)에만 둔다.
