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
| 위치 이력 | `positions/<MMSI>.json` | 워커가 6시간마다 모은 위치 `[{at, lat, lng, sog}]`. 서버가 재생 모드일 때 DB 대신 읽는다 (10-06) |

파일 형식은 `evals/fixtures/shipfinder/`, `evals/fixtures/mof/`, `evals/fixtures/unipass/`의 fixture와 같다.

## 파일이 없을 때

실제 API가 모르는 배에 답하는 모양으로 돌려준다. 검색은 0건, 위치·국적은 status 3(대상 없음), 해수부는 빈 결과, UNI-PASS는 tCnt 0(없는 B/L).
그래서 재생 데이터가 없는 B/L은 평소처럼 되묻기나 partial 경로를 탄다.

## 서버 데모 13건 (10-06)

`python -m scripts.demo.make_demo`가 라이브 데모 10건과 평가셋 3건을 지금 시각 기준으로 옮겨 이 폴더에 쓴다.
만든 파일(`shipfinder/`·`mof/`·`unipass/`·`positions/`)은 실행 시각에 따라 바뀌어 깃에 올리지 않는다(.gitignore).

- 라이브 데모 10건: B/L `DEMOQD2610001` ~ `DEMOQD2610010`. 순항·주의·긴급과 되묻기, 반출 완료를 실제 API 응답처럼 필드를 다 채운 모의 화물로 보여 준다.
  시나리오는 `scripts/demo/demo_live.py`의 `SPECS`에 한 건당 dict 하나로 적고, 그것을 펼친 `evals/fixtures/demo_live.jsonl`을 make_demo가 읽는다
- 평가셋 3건: N01(정상)·B01(되묻기)·F04(실패). B/L은 `TESTBL01`·`TESTBL04`·`TESTBL26`
- 서류 대조 10건(`TESTBL41~50`, `demo_papers.jsonl`)은 서버 데모에서 뺐다. 기능 테스트(`test_demo_papers.py`)만 쓴다

날짜를 왜 옮기는지, F04만 배 이름을 바꾸는 이유는 `scripts/demo/make_demo.py` 머리 주석에 있다.

## LLM 녹화 답

`llm/<프롬프트 이름>.json`. REPLAY_MODE이고 `LLM_MODEL`가 비어 있으면 모델 대신 이 파일의 답을 쓴다 (`services/llm.py` `_replay_answer`).

- 한 파일에 녹화 여러 개. `match`(여유 일수, 신호 7종 상태)가 이번 입력과 같은 녹화의 `output`을 돌려준다
- 맞는 녹화가 없으면 키가 없을 때와 같은 실패(not_configured)로 끝난다. 라우터는 판정 없이 partial을 돌려준다
- 지금 있는 것: `marvia-judge.json` 정상 건 2개(판매 예정일 넣음 여유 4일 / 비움). 09-29 `google/gemini-2.5-flash`(Vertex, 생각 끔)로 데모 입력을 한 번 돌려 받은 답이다
- 라이브 데모 10건에는 녹화 답이 없다 (10-06): `LLM_MODEL`이 비어 있으면 등급은 판정 표대로 나오지만 상태는 partial이고 설명 문장은 고정 문구다. 설명까지 보이려면 `LLM_MODEL`을 넣는다
- 되묻기(B01)는 선박 선택 LLM의 녹화가 없어 실패하고, 라우터가 그대로 되묻는다. 키가 있을 때와 결과가 같다
