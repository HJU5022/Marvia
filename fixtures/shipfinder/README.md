# ShipFinder 재생 응답 (계획 8a)

`MARVIA_SHIPFINDER_MODE=replay`(기본)이면 `src/marvia/tools/shipfinder.py`가 바깥 API 대신 이 폴더를 읽는다.
값은 모두 가공값이다. 실제 응답은 넣지 않는다. 배 번호(MMSI)는 999로, 호출부호는 QQ로 시작한다.

| 경로 | 열쇠 |
|---|---|
| `VesselSearch/<검색어>.json` | 검색어를 대문자로, 글자·숫자가 아닌 것은 `_`로 (예: `TEST_CARGO_A.json`) |
| `VesselPositionSingle/<MMSI>.json` | 배 번호 |
| `VesselFlagInfo/<MMSI>.json` | 배 번호 |

파일이 없으면 검색은 0건, 위치와 국적은 "대상 없음"으로 답한다.
