# 0011. 해수부 API는 서울 Cloud Run 릴레이를 거쳐 부른다

상태: 채택 · 날짜: 2026-10-07 (커밋 048888b)

## 맥락
Railway 서버(리전 기록은 Singapore)에서 해수부 API(`apis.data.go.kr`)가 ConnectTimeout(15초 x 3회)으로 실패한다. 한국에서는 0.1초에 응답한다. 원인은 확인하지 못했다. 미국 GitHub Actions에서 같은 증상이 보고되어 해외 접속 차단으로 짐작하지만 공식 확인은 아니다. UNI-PASS는 싱가포르에서 된다 (SDD 2.2절).

## 결정
- `relay/`의 작은 FastAPI를 Google Cloud Run 서울(asia-northeast3)에 `mof-relay`로 둔다. 개인 GCP 프로젝트(팀 계정 아님)이고 무료 체험 크레딧을 쓴다.
- 해수부 경로 두 가지(`/1192000/VsslEtrynd5/*`, `/1192000/CntlVssl2/*`)만 넘긴다. `X-Relay-Token`이 같아야 하고 serviceKey는 로그에 남기지 않는다.
- 백엔드는 `MOF_BASE_URL`, `MOF_RELAY_TOKEN`으로 연결한다. 연결 실패는 한 번 바로 다시 시도하고 그래도 안 되면 15초 동안 바로 실패시킨다 (`clients/mof.py CIRCUIT_OPEN_SEC`).

## 대안
근거 문서에 비교한 대안이 적혀 있지 않다.

## 결과
좋아진 것: 로컬 릴레이 경유로 입항 예정 206건을 약 2초에 받았다. 운영 채팅 검색이 43척을 돌려줬다 (SDD 6.7절).
대가: 개인 계정의 무료 크레딧에 기대고 있다. 이 숫자들은 한 번의 확인이다.

## 근거
- `docs/Marvia_SDD.md` 2.2절, 6.7절
- `docs/release_manifest.json` deploy.mof_relay
- `relay/README.md`, `CLAUDE.md` 폴더 표 relay 행
