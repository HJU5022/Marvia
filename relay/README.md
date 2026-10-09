# relay (해수부 릴레이)

서울 Google Cloud Run에 `mof-relay`로 올리는 작은 FastAPI 서비스다. 백엔드는 해수부 API(`apis.data.go.kr`)를 이 릴레이를 거쳐 부른다. Railway 서버(리전 기록은 싱가포르)에서 해수부 API를 바로 부르면 ConnectTimeout으로 실패하기 때문이다. 원인은 확인하지 못했다. 배경과 결정은 [ADR 0011](../docs/adr/0011-mof-seoul-relay.md), 배포 전체 구성은 루트 [README.md](../README.md)의 배포 절에 있다.

하는 일은 GET 요청을 그대로 넘기고 상태·본문·content-type을 돌려주는 것뿐이다. 백엔드 쪽 호출은 `backend/app/clients/mof.py`에 있다.

## 보안

| 항목 | 동작 |
|---|---|
| 토큰 | `X-Relay-Token` 헤더가 `RELAY_TOKEN`과 같아야 한다(상수 시간 비교). `RELAY_TOKEN`이 없으면 전부 503 |
| 허용 경로 | `/1192000/VsslEtrynd5/*`, `/1192000/CntlVssl2/*`뿐이다. 나머지는 404 |
| 로그 | 쿼리스트링(serviceKey 포함)은 남기지 않는다. 경로, 상태, 소요 ms만 남긴다 |
| `/health` | 인증 없이 200 `ok`. Cloud Run이 `/healthz`를 가로채서 이 이름을 쓴다 |

## 환경변수

| 이름 | 어디 | 설명 |
|---|---|---|
| `RELAY_TOKEN` | 릴레이 | 공유 비밀. 백엔드의 `MOF_RELAY_TOKEN`과 같은 값 |
| `PORT` | 릴레이 | Cloud Run이 넣는다. 없으면 8080 |
| `MOF_BASE_URL` | 백엔드 | 릴레이 주소. 비우면 `https://apis.data.go.kr`를 직접 부른다 |
| `MOF_RELAY_TOKEN` | 백엔드 | 있으면 모든 해수부 요청에 `X-Relay-Token` 헤더로 보낸다 |

## 배포

레포 루트에서 소스로 올린다. 토큰 값은 저장소에 적지 않는다.

```bash
gcloud run deploy mof-relay --source relay --region asia-northeast3 \
  --allow-unauthenticated --set-env-vars RELAY_TOKEN=<비밀값> \
  --max-instances 2 --memory 256Mi
```

`--allow-unauthenticated`는 Cloud Run 앞단 인증만 끈다. 토큰이 없는 요청은 릴레이가 막는다.

## 로컬 실행과 테스트

```bash
RELAY_TOKEN=x python -m uvicorn relay.main:app --port 8099   # 레포 루트에서
pytest relay -q
```
