# REPLAY_MODE 재생 응답

`REPLAY_MODE=true`면 외부 API 대신 이 폴더를 읽는다 (SDD 6.1). 채점자가 키 없이 데모를 돌려 보기 위한 것이다.
읽는 코드는 `backend/app/clients/replay.py`다. 클라이언트의 파싱·재시도 경로는 실제 호출과 같다.

값은 전부 실제와 형식만 같은 가공값이다. 실제 응답 원본은 넣지 않는다 (CLAUDE.md, SDD 7절, ShipFinder·UNI-PASS 이용 조건).

## 파일 위치

| 소스 | 경로 | 파일 이름(키) |
|---|---|---|
| ShipFinder 검색 | `shipfinder/VesselSearch/<선명>.json` | keywords를 대문자로, 공백·기호는 `_` (예: `TEST_STAR.json`) |
| ShipFinder 위치 | `shipfinder/VesselPositionSingle/<MMSI>.json` | mmsi |
| ShipFinder 국적 | `shipfinder/VesselFlagInfo/<MMSI>.json` | mmsi |
| 해수부 관제정보 | `mof/CntlVssl2/<호출부호>.xml` | clsgn. 호출부호 없이 부르면 `_ALL.xml` |
| 해수부 선박운항정보 | `mof/VsslEtrynd5/<호출부호>.xml` | 같음 |
| UNI-PASS | `unipass/<B/L 번호>.xml` | mblNo 또는 hblNo. 모의 번호만(예: `TESTBL01.xml`) |

파일 형식은 `evals/fixtures/shipfinder/`, `evals/fixtures/mof/`, `evals/fixtures/unipass/`의 fixture와 같다.

## 파일이 없을 때

실제 API가 모르는 배에 답하는 모양으로 돌려준다. 검색은 0건, 위치·국적은 status 3(대상 없음), 해수부는 빈 결과, UNI-PASS는 tCnt 0(없는 B/L).
그래서 재생 데이터가 없는 B/L은 평소처럼 되묻기나 partial 경로를 탄다.

## 아직 없는 것

- 데모 B/L 3건(정상·되묻기·실패)의 재생 데이터. 어느 시나리오로 할지 팀에서 정한 뒤 채운다
- LLM(OpenRouter) 재생. 지금은 키가 없으면 판정 없이 partial로 끝난다
