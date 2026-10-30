# 0021. 개인 계정으로 옮기며 화면은 Vercel, API는 Cloud Run 서울에 재생 모드로 공개한다

상태: 채택 (2026-10-21 결정, 2026-10-26 배포)

## 맥락
- 2차 제출(2026-10-09 r8)까지 화면·API·워커는 Railway에 있었고([0009](0009-deploy-railway-not-vercel.md)), 배포 서버는 실제 모드였다([0010](0010-deployed-server-real-mode.md)).
- 발표(10-12) 뒤 Railway를 해지했고 2026-10-15에는 이미 꺼져 있었다. 두 Railway 주소(`marvia.up.railway.app`, `marvia-api-production.up.railway.app`)는 지금 404다.
- 2026-10-20부터 저장소를 개인 계정 HJU5022/Marvia로 옮겨 이어 개발한다. DB·로그인(Supabase), 관측(Langfuse), GCP도 개인 계정으로 옮겼다.
- 공개 배포를 재생 모드로 둔 직접 이유는 레포에 기록이 없다. 같은 시기에 ShipFinder 스타터 키가 만료돼 키를 비워 두었다. 키가 없으면 실제 모드에서 선박 검색·위치 조회가 되지 않는다([README](../../README.md) 키 표).

## 결정
- 화면 `web/`은 Vercel에 올린다: https://marvia-kappa.vercel.app
- API는 Google Cloud Run 서울(asia-northeast3)에 올리고 `REPLAY_MODE=true`로 돌린다: https://marvia-api-898187792720.asia-northeast3.run.app
- 워커는 올리지 않는다. 자동 수집·감시 재판정은 돌지 않는다.
- DB·로그인은 새 Supabase 프로젝트(서울)다. 레포 마이그레이션을 모두 적용했다. 회원 데이터는 옮기지 않았다. 새 Auth에서는 사용자 ID가 새로 생겨 옛 행의 주인이 없어지기 때문이다.
- Google 계정 없이도 둘러볼 수 있게 공유 데모 계정을 둔다([specs/demo-account.md](../specs/demo-account.md), 커밋 `435d41a`).

## 대안
- Railway 유지: 해지해서 택하지 않았다.

## 결과
- 좋아진 것: 2026-10-30 화면 200, API `/health` `{"status":"ok","db":"ok"}`, 토큰 없는 `/mcp` 401을 확인했다. 화면 번들이 위 API 주소를 부른다. 키 없이 재현하는 경로([0008](0008-replay-mode-keyless.md))와 같은 재생 파일로 공개 화면이 돈다.
- 대가: 공개 화면은 실제 화물을 조회하지 않는다. 재생 파일에 있는 가공 B/L만 판정이 나온다.
- 대가: 재생 모드여도 `LLM_MODEL`이 설정돼 있으면 설명 문장은 실제 모델을 부른다(`backend/app/services/llm.py`의 재생 모드 주석). 채팅의 해수부 입항 검색도 `DATA_GO_KR_KEY`가 있으면 실제로 호출한다(`backend/app/services/chat/chat.py`의 `live` 조건).
- 대가: 데모 계정은 여러 사람이 같이 써서 대화·화물 기록이 방문자끼리 보인다.
- 대가: API가 올라간 GCP 프로젝트는 무료 체험 크레딧이고 2026-12-09에 끝난다. 그 뒤 운영 여부는 정하지 않았다.
- 대가: 이 배포의 커밋과 Cloud Run 설정(환경변수)은 레포에 기록하지 않았다.

## 근거
- [release_manifest.json](../release_manifest.json) `_current_deploy`, r8 `deploy`
- [README](../../README.md) 배포 절, 키 표
- [specs/demo-account.md](../specs/demo-account.md), 커밋 `435d41a`
