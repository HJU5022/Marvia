# ShipFinder fixture

실제 응답과 형식만 같은 가공값이다 (CLAUDE.md "실제 응답 원본은 커밋하지 않는다", ShipFinder 이용 조건).
MMSI·선명·호출부호는 실재하지 않는 값으로 바꿨고, 응답 구조와 경계 사례만 남겼다.

| 파일 | 담은 경계 사례 |
|---|---|
| position_busan_anchored.json | 부산 북항 정박(sog 0, navistat 8). eta 필드 자체가 없음, hdg 511.0(무효, float) |
| position_ok.json | 공식 문서 응답 예시. 항해 중, eta 있음 |
| search_same_name.json | 같은 선명 여럿, 같은 IMO에 MMSI 2개, 7자리가 아닌 IMO(357289382), imo 0 |
| search_same_imo.json | 공식 문서 응답 예시. 같은 IMO에 MMSI 3개 |
| not_found.json, no_permission.json, rate_limited.json | status 3, 21, 29 |

실제 응답이 필요하면 `scripts/fetch_shipfinder.py`로 받아 로컬(.local/, gitignore)에만 둔다.
