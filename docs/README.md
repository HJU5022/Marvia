# 문서 지도

**기준 문서는 PRD, SDD, 작업 리스트 셋이다. 서로 어긋나면 SDD가 구현 기준이다.** 루트 [README.md](../README.md)는 서비스 소개와 실행법, 이 폴더는 기획·설계와 그 근거 기록이다.

## 무엇이 궁금하면 어디를 보나

기준 문서

| 궁금한 것 | 볼 곳 |
|---|---|
| 왜 만드나, 범위, 안 만드는 것, 평가 설계 | [Marvia_PRD.md](./Marvia_PRD.md) (안 만드는 것은 4절, 평가는 8절) |
| 어떻게 구현하나: 계약 C1~C8과 DB, 처리 흐름, 파일별 책임, 배포, 보안, 실패 처리, 테스트 | [Marvia_SDD.md](./Marvia_SDD.md) (데이터 설계 3절, 흐름 4절, 컴포넌트 5절, 배포 6절, 보안 7절, 실패 8절, 테스트 9절) |
| 작업 ID(A~G), 완료 기준, 기한, 묶음 경계, 실사용 점검 번호 | [Marvia_개발_작업_리스트.md](./Marvia_개발_작업_리스트.md) |

설계 결정과 근거 기록

| 궁금한 것 | 볼 곳 |
|---|---|
| 왜 이렇게 설계했나 (결정 하나당 한 장, 20건) | [adr/](./adr/README.md) |
| SDD에 없는 기능의 범위와 동작 | [specs/](#specs) (아래 표) |
| DB 표와 칸, 관계, 마이그레이션 | [ERD.md](./ERD.md) |
| 프롬프트 10개의 지금 버전, 버전마다 무엇을 왜 바꿨고 결과가 어땠나 | [prompt_versions.md](./prompt_versions.md) (원문은 `backend/app/prompts/`) |
| 지금 배포된 것: 주소, 모델, 프롬프트 번호, 코드 커밋, 검증 결과, 되돌리기 절차 | [release_manifest.json](./release_manifest.json) |
| Langfuse 집계와 캡처, 배포 주소 MCP 연결 기록 | [evidence/](#evidence) (아래 표) |
| 화면 녹화(GIF) | `assets/gif/` |
| 평가 숫자, 목표 대비 결과, 한계 | [../EVAL_REPORT.md](../EVAL_REPORT.md) |
| 평가셋 구성과 판정 방식 | [../evals/README.md](../evals/README.md) |

## specs

SDD 5절과 작업 리스트에 없는 기능은 Spec을 먼저 쓴다 (CLAUDE.md "할 것"). Spec과 코드가 다른 곳은 각 파일 안에 적었다.

| 파일 | 내용 |
|---|---|
| [cargo-watch.md](./specs/cargo-watch.md) | 지켜보는 화물: 감시와 지도 |
| [chat-progress.md](./specs/chat-progress.md) | 답을 기다리는 동안 실제 처리 단계를 SSE로 보여 주기 |
| [chat-search.md](./specs/chat-search.md) | 자연어 입력 하나로 조회, 입항 선박 검색 |
| [customs-detail.md](./specs/customs-detail.md) | UNI-PASS 처리 이력 원문 화면 표시 |
| [document-extract.md](./specs/document-extract.md) | 서류 사진에서 조회 값 뽑기 |
| [injection-redteam.md](./specs/injection-redteam.md) | 프롬프트 주입 레드팀 점검 |
| [memory.md](./specs/memory.md) | 화물 비서 기억: 사용자별 화물 표와 메모장, 채팅 입구 |
| [mrn-fallback.md](./specs/mrn-fallback.md) | 세관에 아직 없는 화물은 MRN으로 배 상태까지 |
| [operator-admin.md](./specs/operator-admin.md) | 운영자 관리: 관리 탭, 고객 관리, 운영자 등록과 해지 |
| [referral-guide.md](./specs/referral-guide.md) | 안내처 표: 신호별 다음 행선지와 범위 밖 질문 |
| [token-quota.md](./specs/token-quota.md) | 1명당 하루 LLM 토큰 한도 |
| [user-profile.md](./specs/user-profile.md) | 회원 정보 필수 입력, 암호화 저장과 마스킹 |

## evidence

| 파일 | 내용 |
|---|---|
| [langfuse_summary.md](./evidence/langfuse_summary.md), [langfuse_summary.json](./evidence/langfuse_summary.json) | Langfuse 집계(트레이스, 비용, 지연, 프롬프트 버전), `scripts/eval/langfuse_evidence.py`가 만든다. 집계 기간 2026-09-01 ~ 2026-10-08. 이 파일의 프롬프트 production 번호는 생성 시점 값이고, 지금 번호는 release_manifest.json을 따른다 |
| [langfuse_summary_20261002.md](./evidence/langfuse_summary_20261002.md) | 같은 스크립트(`scripts/eval/langfuse_evidence.py`)의 이전 실행. 집계 기간 2026-09-01 ~ 2026-10-02 |
| `langfuse-01-dashboard.jpg` ~ `langfuse-10-latency-percentiles.jpg` (10장) | Langfuse 화면 캡처: 대시보드, 트레이스, 재시도, 프롬프트, 실험, 데이터셋, 비용, 지연 |
| [mcp-02-deployed-tools.txt](./evidence/mcp-02-deployed-tools.txt) | 배포 주소 `/mcp` 연결 기록. 토큰이 있으면 도구 4개, 없으면 401 |
| `B10-mcp-연결-도구목록-호출.png` | 로컬 MCP 서버(`/mcp`)에 langchain-mcp-adapters 클라이언트로 붙어 도구 4개 목록을 받고 estimate_distance를 부른 캡처 |

## 폴더 README

| 파일 | 내용 |
|---|---|
| [backend/README.md](../backend/README.md) | FastAPI 앱 구조 |
| [mcp_server/README.md](../mcp_server/README.md) | MCP 도구 4개 |
| [skills/README.md](../skills/README.md) | Skill 6개 |
| [relay/README.md](../relay/README.md) | 해수부 API 서울 릴레이 |
| [web/README.md](../web/README.md) | 화면 |
| [web/DESIGN.md](../web/DESIGN.md) | 화면 디자인 규칙과 그 이유 |
| [evals/README.md](../evals/README.md) | 평가셋과 실행기 |
| [scripts/ops/README.md](../scripts/ops/README.md) | 실제 DB와 계정을 바꾸는 운영 스크립트 (돌리기 전에 읽는다) |
| [evals/results/injection/README.md](../evals/results/injection/README.md) | 프롬프트 주입 측정 결과의 원본 |
| [evals/results/e2e_attack_20261008/README.md](../evals/results/e2e_attack_20261008/README.md) | 채팅·서류 경로 공격 e2e 기록 |
| [evals/fixtures/replay/README.md](../evals/fixtures/replay/README.md) | REPLAY_MODE 재생 응답 |
| [evals/fixtures/shipfinder/README.md](../evals/fixtures/shipfinder/README.md) | ShipFinder 가공 fixture |
| [backend/tests/fixtures/documents/README.md](../backend/tests/fixtures/documents/README.md) | 서류 사진 테스트 자료 (가공) |
| [web/public/landing/README.md](../web/public/landing/README.md) | 소개 페이지 사진 출처 |
