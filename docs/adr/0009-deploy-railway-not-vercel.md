# 0009. 배포는 Railway로 하고 Vercel과 api용 Cloud Run은 쓰지 않는다

상태: 채택

## 맥락
처음 계획은 화면 Vercel + 서버 GCP Cloud Run이었다 ([SDD 2.2절](../Marvia_SDD.md)). Railway로 바꾼 이유는 레포에 기록이 없다.

## 결정
- `marvia-api`는 `Dockerfile.railway`(app 단계만)로, `marvia-web`(`web/`, Next.js)은 따로 Railway 서비스로 배포한다. DB는 Supabase다.
- Cloud Run은 해수부 릴레이 하나에만 쓴다 ([0011](0011-mof-seoul-relay.md)).
- Railway는 GitHub에서 자동 배포되지 않는다. 배포할 때마다 커밋, `/health` 응답, 실제 호출 결과를 [docs/release_manifest.json](../release_manifest.json)에 적는다.

## 결과
- 좋아진 것: 코드 되돌리기는 Railway에서 이전 deployment를 Redeploy하는 한 가지다 ([release_manifest.json](../release_manifest.json) `rollback.code`).
- 대가: Railway 서비스 설정(빌드 방식, 환경변수)은 레포 밖에 있다 ([SDD 6.3절](../Marvia_SDD.md)). 기본 Dockerfile의 base, app 단계를 고치면 `Dockerfile.railway`도 같이 고쳐야 한다. web은 `--path-as-root` 없이 올리면 루트 Dockerfile이 빌드돼 화면이 502가 된다.

## 근거
- [SDD](../Marvia_SDD.md) 2.2절, 6.3절, 6.4절
- [release_manifest.json](../release_manifest.json) `deploy`, `rollback`
- [CLAUDE.md](../../CLAUDE.md) "배포 기록": "Railway는 GitHub에서 자동 배포되지 않는다", 폴더 표 Dockerfile 행
