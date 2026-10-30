# 0010. 배포 서버는 재생 모드가 아니라 실제 모드로 돌린다

상태: 대체됨 → [0021](0021-deploy-vercel-cloudrun-replay.md). 2026-10-26부터의 공개 배포(Cloud Run 서울)는 재생 모드(`REPLAY_MODE=true`)다. 아래는 2차 제출 때 Railway 배포가 실제 모드였다는 기록이다.

## 맥락
처음엔 배포 서버도 재생 모드(`REPLAY_MODE=true`)였다. Railway용 Dockerfile을 만들 때 "배포는 데모로 시연"으로 정했고, 재생 모드면 켜질 때 데모 재생 파일을 만들게 했다 (커밋 `186b830`). 실제 모드로 바꾼 직접 이유는 레포에 기록이 없다.

## 결정
- 배포된 api는 `REPLAY_MODE=false`(실제 모드)로 돈다. 문서에 배포 모드를 쓸 때는 이 한 가지로만 쓴다.
- 재생 모드는 키 없는 재현, 로컬 데모, 평가용이다 ([0008](0008-replay-mode-keyless.md)).

## 대안
- 재생 모드 배포 유지: 데모 위치가 시간이 지나면 오래된 위치가 되어 데모 결과가 바뀌는 문제가 있었다 (커밋 `c577c56` 메시지, [SDD 6.4절](../Marvia_SDD.md)).

## 결과
- 좋아진 것: 운영 채팅의 입항 선박 검색이 실제 선박 목록을 돌려줬다. 예: "일본에서 1주 안에 부산 오는 수입 화물선" 질문에 43척 ([release_manifest.json](../release_manifest.json) `deploy.mof_relay.note`).
- 대가: 해수부 API가 Railway 싱가포르에서 막혀 릴레이가 필요해졌다 ([0011](0011-mof-seoul-relay.md)). 43척은 한 번의 확인이고 지속 가동률은 재지 않았다 ([SDD 6.7절](../Marvia_SDD.md)).

## 근거
- [CLAUDE.md](../../CLAUDE.md) "배포 기록": "배포 서버는 실제 모드(REPLAY_MODE=false)다. 문서에 배포 모드를 쓸 때 이 한 가지로만 쓴다"
- [SDD](../Marvia_SDD.md) 2.2절, 6.4절
- [release_manifest.json](../release_manifest.json) `deploy.replay_mode`, `deploy.replay_mode_note`
