# 문서 지도

루트 [README.md](../README.md)는 서비스 소개와 실행법이다. 이 폴더는 기획, 설계, 근거 자료다. 기준 문서는 PRD, SDD, 작업 리스트 셋이고, 서로 어긋나면 SDD가 구현 기준이다.

## 무엇이 궁금하면 어디를 보나

| 궁금한 것 | 볼 곳 |
|---|---|
| 왜 만드나, 범위, 만들지 않는 것, 평가 설계 | [Marvia_PRD.md](./Marvia_PRD.md) (안 만드는 것은 4절) |
| 왜 이렇게 설계했나 (설계 결정 기록, 결정 하나당 한 장) | [adr/](./adr/README.md) |
| 어떻게 구현하나: 스키마(계약 C1~C8), 처리 흐름, 파일별 책임, 실패 처리, 배포 | [Marvia_SDD.md](./Marvia_SDD.md) (스키마 3절, 흐름 4절, 파일 책임 5절, 배포 6절, 보안 7절, 실패 8절) |
| 작업 ID(A1~G5), 완료 기준, 기한, 묶음 경계 | [Marvia_개발_작업_리스트.md](./Marvia_개발_작업_리스트.md) |
| DB 표와 관계, 마이그레이션 001~023 | [ERD.md](./ERD.md) |
| 프롬프트 버전마다 무엇을 왜 바꿨고 결과가 어땠나 | [prompt_versions.md](./prompt_versions.md) (원문은 `backend/app/prompts/`) |
| 지금 배포된 것: 주소, 모델, 코드 커밋, 검증 결과, 되돌리기 절차 | [release_manifest.json](./release_manifest.json) |
| SDD에 없는 기능의 범위와 동작 | [specs/](./specs/) (아래 표) |
| Langfuse 집계, 트레이스·프롬프트·비용 캡처, MCP 연결 캡처 | [evidence/](./evidence/) |
| 평가 숫자, 목표 대비 결과, 한계 | [../EVAL_REPORT.md](../EVAL_REPORT.md) |
| 평가셋 구성과 판정 방식 | [../evals/README.md](../evals/README.md) |

## specs/

SDD 5절과 작업 리스트에 없는 기능은 Spec을 먼저 쓴다(CLAUDE.md). 코드와 다른 곳은 파일 안에 적혀 있다.

| 파일 | 내용 |
|---|---|
| [cargo-watch.md](./specs/cargo-watch.md) | 지켜보는 화물: 감시와 지도 |
| [chat-progress.md](./specs/chat-progress.md) | 답을 기다리는 동안 실제 처리 단계를 SSE로 보여 주기 |
| [chat-search.md](./specs/chat-search.md) | 자연어 입력 하나로 조회, 입항 선박 검색 |
| [customs-detail.md](./specs/customs-detail.md) | UNI-PASS 처리 이력 원문 화면 표시 |
| [document-extract.md](./specs/document-extract.md) | 서류 사진에서 조회 값 뽑기 |
| [injection-redteam.md](./specs/injection-redteam.md) | 프롬프트 주입 레드팀 점검 |
| [memory.md](./specs/memory.md) | 화물 비서 기억 (G4 메모리와 채팅 입구) |
| [mrn-fallback.md](./specs/mrn-fallback.md) | 세관에 아직 없는 화물은 MRN으로 배 상태까지 |
| [operator-admin.md](./specs/operator-admin.md) | 운영자 관리: 관리 탭, 고객 관리, 운영자 등록과 해지 |
| [referral-guide.md](./specs/referral-guide.md) | 안내처 표: 신호별 다음 행선지와 범위 밖 질문 |
| [token-quota.md](./specs/token-quota.md) | 1명당 하루 LLM 토큰 한도 |
| [user-profile.md](./specs/user-profile.md) | 회원 정보 필수 입력, 암호화 저장과 마스킹 |

## 폴더 README

| 폴더 | 설명 |
|---|---|
| [backend/](../backend/README.md) | FastAPI 앱 구조 |
| [mcp_server/](../mcp_server/README.md) | MCP 도구 4종 |
| [skills/](../skills/README.md) | Skill 6종 |
| [relay/](../relay/README.md) | 해수부 릴레이 |
| [web/](../web/README.md) | 화면 |
| [evals/](../evals/README.md) | 평가셋 |
