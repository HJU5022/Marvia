# 0009. 배포는 Railway로 하고 Vercel과 api용 Cloud Run은 쓰지 않는다

상태: 채택 (계획을 대체함)

## 맥락
계획은 화면 Vercel + 서버 GCP Cloud Run이었다 (SDD 2.2절).

## 결정
`marvia-api`는 `Dockerfile.railway`(app 단계만)로, `marvia-web`(`web/`, Next.js)은 Railway 서비스로 배포한다. DB는 Supabase다. Vercel과 api, web용 Cloud Run은 쓰지 않는다. Cloud Run은 해수부 릴레이 하나에만 쓴다 (ADR 0011).
Railway는 GitHub에서 자동 배포되지 않는다. 배포할 때마다 커밋, `/health` 응답, 실제 호출 결과를 `docs/release_manifest.json`에 적는다.

## 대안
- Vercel + Cloud Run: 처음 계획. 바꾼 이유는 근거 문서에 적혀 있지 않다.

## 결과
좋아진 것: 되돌리기는 Railway에서 이전 deployment를 Redeploy하는 한 가지다 (`docs/release_manifest.json` rollback).
대가: Railway 서비스 설정(빌드 방식, 환경변수)은 레포 밖이라 SDD가 확인하지 못했다고 적는다 (6.3절). 기본 Dockerfile의 base, app을 고치면 `Dockerfile.railway`도 같이 고쳐야 한다 (`CLAUDE.md`).

## 근거
- `docs/Marvia_SDD.md` 2.2절, 6.3절, 6.4절
- `README.md` 17행, `docs/release_manifest.json` deploy 항목
- `CLAUDE.md` "배포 기록"
