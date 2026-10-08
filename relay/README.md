# 해수부 API 릴레이

## 무엇을, 왜
실측: Railway(싱가포르)에서 해수부 API(`apis.data.go.kr`)를 부르면 ConnectTimeout이 난다(한국에서는 0.1초).
서울 Cloud Run에 이 릴레이를 두고 백엔드가 여기를 거쳐 부르게 한다. GET만 그대로 넘기고 상태·본문·content-type을 돌려준다.

## 보안
- `X-Relay-Token` 헤더가 환경변수 `RELAY_TOKEN`과 같아야 한다(상수 시간 비교). `RELAY_TOKEN`이 없으면 전부 503
- 허용 경로는 `/1192000/VsslEtrynd5/*`, `/1192000/CntlVssl2/*`뿐. 나머지는 404
- 쿼리스트링(serviceKey 포함)은 로그에 남기지 않는다. 경로·상태·소요 ms만 기록
- `/health`는 인증 없이 200 `ok` (Cloud Run이 `/healthz`를 가로채서 이 이름을 쓴다)

## 환경변수
| 이름 | 어디 | 설명 |
|---|---|---|
| `RELAY_TOKEN` | 릴레이 | 공유 비밀. 백엔드의 `MOF_RELAY_TOKEN`과 같은 값 |
| `PORT` | 릴레이 | Cloud Run이 설정. 기본 8080 |
| `MOF_BASE_URL` | 백엔드 | 릴레이 주소(끝에 `/` 없이). 비우면 `https://apis.data.go.kr` 직접 호출 |
| `MOF_RELAY_TOKEN` | 백엔드 | 있으면 모든 해수부 요청에 `X-Relay-Token`으로 보낸다 |

## 배포 (템플릿)
```
gcloud run deploy mof-relay --source relay --region asia-northeast3 \
  --allow-unauthenticated --set-env-vars RELAY_TOKEN=<비밀값> \
  --max-instances 2 --memory 256Mi
```
`--allow-unauthenticated`여도 토큰이 없으면 막힌다. 토큰 값은 저장소에 적지 않는다.

## 로컬 실행
```
RELAY_TOKEN=x python -m uvicorn relay.main:app --port 8099   # 저장소 루트에서
```
테스트: `.venv/bin/python -m pytest relay -q`
