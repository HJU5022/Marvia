# Marvia 개발 작업 리스트

기준: PRD (2026-09-22). 코드 동결 10/8 자정. **상태 갱신: 2026-09-30.**
팀원 2명, 둘 다 풀스택. A~G 묶음은 담당을 정하지 않고 열린 작업을 누구든 가져간다. 함정 경험이 필요한 Skill 검수와 라벨 확정만 하정운이 맡는다. 묶음 사이는 **계약(인터페이스)**으로만 이어지고, 계약을 먼저 고정하면 서로 기다리지 않고 개발할 수 있다.

상태: ✅ 완료 · 🔶 일부 (남은 것은 비고) · ⬜ 남음. 완료는 완료 기준을 테스트나 실행으로 확인한 것만 적는다.

## 진행률 (09-30)

| 묶음 | 완료 | 일부 | 남음 | 진행률 |
| --- | --- | --- | --- | --- |
| A. 백엔드 골격과 배포 | 10 | 1 | 1 | 88% |
| B. MCP 서버와 데이터 소스 | 9 | 0 | 1 | 90% |
| C. 판정 로직, LLM 호출, Skill | 12 | 0 | 0 | 100% |
| D. 관측, 수집 워커, 평가 | 5 | 5 | 2 | 63% |
| E. 프론트엔드 | 0 | 1 | 10 | 5% |
| F. 마감 작업 | 0 | 1 | 5 | 8% |
| G. 확장 (최소 범위) | 1 | 0 | 3 | 25% |

> 진행률 = (완료 + 일부 × 0.5) ÷ 항목 수

## 0. 먼저 고정할 계약 (9/23, 전원)

병행 개발의 전제다. 바꾸면 평가셋, fixture, 프론트가 같이 깨지므로 PR 리뷰를 거친다.

| 계약 | 내용 | 파일 |
| --- | --- | --- |
| C1 응답 스키마 | status(ok · partial · insufficient · failed · unsupported), verdict, decided_by, vessel_match, reasons, conflicts, actions, days_margin, evidence 등 | `backend/app/schemas/agent.py` |
| C2 요청 스키마 | bl_no, bl_type(M/H) 필수. sale_due_date · forwarder_eta · voyage_no · resolved_mmsi · follow_up_question · session_id 선택 (판매 예정일은 09-29부터 선택) | `backend/app/schemas/agent.py` |
| C3 1층 신호 출력 | 신호 7종 각각 triggered / clear / unknown + 값 + 출처 | `backend/app/schemas/signals.py` |
| C4 MCP 도구 4종 입출력 | 모든 출력에 source, fetched_at 포함. 실패는 {error: {code, message, retryable}} | `mcp_server/schemas.py` |
| C5 UNI-PASS 정제 결과 | ship_name, ship_nat, voyage, entry_date, stage_history, shed_name. LLM에 안 넘기는 필드(품명, 중량) 제외 | `backend/app/schemas/customs.py` |
| C6 Skill 임계값 | 오래된 위치 6시간 · ETA 상충 12시간 · 정지 속도 0.5노트 · 정박 24시간 · 부산 반경 30해리 · 여유 부족 2일 | `skills/ais-reliability/rules.md` 프론트매터 |
| C7 평가 레코드 | 입력(C2) + 가공 fixtures + 정답 status · verdict · vessel_match · 물을 것 + 라벨러 + 사유 | `evals/schema.py` |
| C8 환경변수 | .env.example 키 목록 | `.env.example` |

레포 구조 (실제):

```
proj2-5/
  backend/app/    FastAPI (라우터, 서비스, 스키마, 클라이언트, 관측, 프롬프트 사본)
  mcp_server/     FastMCP 도구 4종 (/mcp는 API 서버 안의 경로)
  skills/         Skill 문서 3종 + 임계값
  worker/         수집 워커
  evals/          평가셋 30건, 베이스라인, 실행기, 검증 모델 채점, 재생 fixture
  scripts/        손으로 돌리는 확인 스크립트 (MCP 확인, 데모 파일 생성, 실패 훈련)
  web/            Next.js (아직 없음)
  docker-compose.yml  Dockerfile  .env.example  README.md  EVAL_REPORT.md
```

## A. 백엔드 골격과 배포

| # | 작업 | 완료 기준 | 상태 | 비고 |
| --- | --- | --- | --- | --- |
| A1 | FastAPI 프로젝트 생성, `GET /health`, `/docs` | 로컬에서 200 | ✅ | |
| A2 | Pydantic 스키마 C1·C2·C5 코드화 | import 되고 예시 JSON이 검증 통과 | ✅ | |
| A3 | Dockerfile, docker-compose.yml (api + worker + postgres) | `docker compose up` 한 줄로 전체 기동 | ✅ | MCP는 api 안의 `/mcp` (09-30). 서류 사진 OCR 패키지는 api 이미지에만 |
| A4 | Cloud Run 배포 (서비스 1개, `/mcp` 포함), URL 확보 | 외부에서 /health 200, `/mcp` 토큰 없이 401 | ⬜ | Cloud Run 주소에서 MCP가 421로 막히던 문제는 09-30에 미리 고침 |
| A5 | 구조화 로그 미들웨어 (요청 ID, 모델, 토큰, 지연) | 로그 1건에 4필드 | ✅ | 실패는 `failure stage=… error=…` 한 줄 |
| A6 | `POST /api/agent` 라우터. 서비스 계층 호출만, LLM SDK import 금지 | 라우터에 openai/anthropic import 없음 | ✅ | |
| A7 | B/L 형식 검증, 범위 밖 입력 거절 | 잘못된 형식 400, 정상 통과. 부산 외 항만은 unsupported | ✅ | |
| A8 | UNI-PASS 클라이언트, 응답 → C5 정제, 필드 마스킹 | 실제 B/L 1건 조회 성공 또는 모의 응답으로 파싱 통과 | ✅ | 실제 B/L 1건 MRN 식별까지 확인 (09-28) |
| A9 | 실패 경로: 외부 API 타임아웃 · 5xx 재시도 2회 + 백오프, partial 응답 | 모의 지연으로 재시도 로그 확인 | ✅ | 실패 훈련 스크립트 `scripts/failure_drill.py` |
| A10 | CORS, /mcp 토큰 인증, 비밀값 서버 환경변수만 | 브라우저에서 키 노출 없음, 토큰 없으면 401 | ✅ | 배포 때 `MCP_TOKEN`을 새로 만들어 넣는다 |
| A11 | README 실행 절차 (clone → .env → compose up, 10분) | 다른 사람이 처음 클론해서 재현 | 🔶 | 키 없이 도는 데모 3건 절차 작성 · 로컬과 Docker로 확인. 다른 사람 재현은 남음 (F5) |
| A12 | `GET /api/history` 라우터. query_log를 session_id로 읽기만 | agent 2회 호출 뒤 같은 세션 조회 시 2건, 다른 세션 0건 | ✅ | |

## B. MCP 서버와 데이터 소스

| # | 작업 | 완료 기준 | 상태 | 비고 |
| --- | --- | --- | --- | --- |
| B1 | FastMCP 서버, Streamable HTTP `/mcp` | MCP 클라이언트로 tool 목록 조회 | ✅ | 09-30 API 서버 안으로 합침. 우리 서비스는 도구 함수를 직접 부르고, `/mcp`는 외부 AI 프로그램용 |
| B2 | ShipFinder 클라이언트: VesselSearch, VesselPositionSingle. status 코드 매핑(0, 3, 9, 13, 21, 23, 29) | 실제 선박 1척 MMSI 조회 성공(MMSI는 로컬에만) | ✅ | |
| B3 | 도구 `get_vessel_candidates`: 후보 목록 + 유사도 + last_time. 같은 IMO면 최신 MMSI만 | 동명 선박 검색 시 후보 복수 반환 | ✅ | |
| B4 | 도구 `get_live_position`: 원본 값과 last_time 반환 (freshness 판정은 C-4가 함) | 실제 선박 1척 조회 | ✅ | |
| B5 | 해수부 클라이언트: 관제정보(`CntlVssl2`), 선박운항정보(`VsslEtrynd5`). 호출부호 · 선명으로 조회 | 부산항 입항 예정 목록 1회 수신 | ✅ | |
| B6 | 도구 `get_port_schedule`: 입항 예정 · 실적, 접안 시설 | 실제 선박 1척 매칭 | ✅ | |
| B7 | searoute 도구 `estimate_distance` | 부산까지 해리 반환 | ✅ | |
| B8 | ShipFinder 캐시 (최근 값 + 캐시 시각) | 빈도 초과 모의 시 캐시 응답 | ✅ | 23 · 29는 6시간 안 캐시, 타임아웃은 오래된 캐시도 쓰고 partial (평가 F02) |
| B9 | tool_description: 언제 쓰는 도구인지 한 문장 | 리뷰 통과 | ✅ | 설명에 판단 · 지시 표현 금지 테스트 |
| B10 | /mcp 연결 스크린샷, tool 목록 · 호출 결과 캡처 | 제출물 확보 | ⬜ | 로컬에서 MCP 클라이언트로 연결 · 도구 4개 · 호출 확인(09-30). 배포 주소로 캡처 남음 |

## C. 판정 로직, LLM 호출, Skill (Skill 검수: 하정운)

| # | 작업 | 완료 기준 | 상태 | 비고 |
| --- | --- | --- | --- | --- |
| C-1 | `skills/ais-reliability/SKILL.md` + `rules.md`. 신호 7종, 상충 우선순위, 판정 표, 되묻기 조건 | 하정운 검수 | ✅ | 판정 표 예외(깨진 목적지 · 항해상태 불일치), 판매일 없을 때, 날짜 말하기 추가 (09-29) |
| C-2 | `skills/customs-stages/SKILL.md`: 실제 처리구분 이름, 의미, 다음 단계, 할 일, 관세사 확인 조건 | 단계 전체 확보 | ✅ | 실제 처리구분 10단계. "사용자가 할 일" 칸 하정운 확인 (09-30) |
| C-3 | `skills/port-busan/SKILL.md`: 부두 · 정박지 개요, 하역 장소 문장 규칙 | 하정운 검수 | ✅ | |
| C-4 | 1층 신호 판정 코드 (`services/signals.py`): rules.md 읽어 7종 판정 → C3 | 단위 테스트 통과 | ✅ | 정박 시간은 워커 위치 이력으로 잰다 |
| C-5 | 선박 식별: 후보 1척이면 코드 확정, 복수면 LLM 판단, uncertain이면 판정 차단 | 동명 선박(B01) 케이스가 uncertain | ✅ | MRN 호출부호 · 세관 국적과 다르면 1척이어도 되묻기 |
| C-6 | `services/llm.py`: LLM 호출 단일 지점, Skill 주입, 모델 A/B 스위치 | 라우터 밖에서 LLM SDK import 없음 | ✅ | 도구는 코드가 순서대로 부른다(LLM이 도구를 고르지 않음). Vertex(`vertex/`)와 OpenRouter 두 길. 키 없는 데모는 녹화 답 재생 |
| C-7 | 출력 검증 V1~V8 + 3단계 재시도 + 폴백 | 위반 응답 주입 시 재시도 트레이스 | ✅ | V8 등급 검사(09-30). 폴백은 판정 표 등급 + 고정 문구로 partial, failed는 통관 조회 실패만 |
| C-8 | days_margin 코드 계산, LLM 덮어쓰기 금지 울타리 | LLM이 다른 값 내도 코드 값 유지 | ✅ | 판매일 없으면 null |
| C-9 | 후속 질의: 근거 범위 밖 질문 거절 | "비트코인 시세" 거절 | ✅ | 후속 답도 V1 · V7 검사 |
| C-10 | 신뢰 경계: 도구 응답 · dest 문자열 속 지시문 무시 | dest에 지시문 넣은 케이스 통과 | ✅ | 평가 주입 3건 통과 |
| C-11 | 프롬프트 작성, Langfuse에 등록 (연동 코드는 D4) | Langfuse에 prompt 존재 | ✅ | 5종: judge · pick-vessel · follow-up · judge-eval · doc-extract. 이력은 `docs/prompt_versions.md` |
| C-12 | 등급은 판정 표 코드로 (`services/verdict.py`), 회색 지대만 LLM이 올리기 | 판정 표와 다른 등급이면 V8, 회색 지대는 표 이상만 | ✅ | 09-30 결정. 30건 판정 정확도 100% |

## D. 관측, 수집 워커, 평가

| # | 작업 | 완료 기준 | 상태 | 비고 |
| --- | --- | --- | --- | --- |
| D1 | 수집 워커: 부산 입항 예정 컨테이너선 최대 12척 선정 → 6시간마다 위치 저장 (ShipFinder 하루 50회 안) | 기록 쌓임 | 🔶 | 코드 완료. 스케줄러 기본 꺼짐이라 주기 가동은 안 함 |
| D2 | 입항 실적 수집: 관제정보 · 선박운항정보 저장 | 입항 완료 선박에 실제 시각 기록 | 🔶 | 코드 완료. D1과 같이 주기 가동 안 함 |
| D3 | Langfuse 트레이스: llm.py 호출마다 generation, session_id, 재시도 · 모델 · 토큰 · 비용 | 대시보드에 trace 1건 | ✅ | 서버 종료 때 남은 트레이스 전송(09-29) |
| D4 | Langfuse Prompt fetch 코드(`get_prompt`), 버전 → 트레이스 링크 | trace에 prompt 버전 표시 | ✅ | |
| D5 | 평가셋 30건: 정상 8, 경계 14(판정 9 · 되묻기 5), 실패 8. 가상 B/L · 통관 · 판매 예정일 | Langfuse Dataset 업로드 | ✅ | `marvia-golden-30`. 평가 실행이 문항별로 연결된다 |
| D6 | 라벨링: 문항마다 판정자 · 사유. 사후 입항 시각으로 예측 적중 별도 | 30건 라벨 완료 | 🔶 | 30건 라벨 완료(판정자 · 사유). 라벨 날짜 비어 있음 · 사후 입항 적중은 안 함. 없는 상황 4개(판매일 없음 · 도착일 모름 · 여유 0~1일 · 회색 지대) 문항 추가 예정 |
| D7 | 베이스라인 (a) 규칙만 | 30건 실행 결과 | ✅ | 27/30 |
| D8 | 평가 실행기: (a)(b)(c) × 30건, 축 7개 채점 | 결과 표 자동 생성 | ✅ | 결과는 실행마다 새 파일 (`evals/results/<구성>_<시각>.json`) |
| D9 | LLM-as-judge: 통관 해설 채점 모델(gpt-4o-mini) ≠ 생성 모델 | 표본 5건 사람 대조 | 🔶 | 채점 연결 · 20/21 통과. 사람 대조 5건은 남음 |
| D10 | 개선 실험: 한 가지만 바꿔 재측정 | KEEP/DISCARD 기록 | 🔶 | 등급을 판정 표로(27 → 30/30), 생각 끄기 등 실험 여러 번. EVAL_REPORT 형식 정리 남음 |
| D11 | EVAL_REPORT.md: 평가셋 구성, 베이스라인 비교, 전후 지표, 실패 사례, 판정 방식 · 한계 | 게이트 판정 표시 | ⬜ | 틀만 있음 |
| D12 | 운영 지표: p50/p95, 요청당 비용, 계약 준수율 | README 지표 표 | ⬜ | 숫자는 측정됨(p95 3.8초 · 요청당 약 2.4원), README 표 비어 있음 |

## E. 프론트엔드

`web/` 없음. 화면 목업은 레포 밖에 있다. 백엔드 응답(C1)은 확정.

| # | 작업 | 완료 기준 | 상태 | 비고 |
| --- | --- | --- | --- | --- |
| E1 | Next.js 프로젝트, Vercel 배포 | URL 확보 | ⬜ | |
| E2 | 입력 폼: B/L(필수), M/H 구분, 판매 예정일(선택), 서류 사진 | 형식 오류 인라인 표시 | ⬜ | 판매 예정일은 선택 입력 |
| E3 | 조회 진행 표시 (식별 → 위치 → 판정 단계) | 로딩 상태 3단계 | ⬜ | |
| E4 | 결과 화면: 판정 배지(fine/watch/act), 할 일, 지도(stale은 흐리게), 화물 카드, 통관 타임라인, 하역 장소 | C1 응답 전 필드 렌더 | ⬜ | |
| E5 | 근거 카드: evidence 목록 (출처, 값, 조회 시각) | 클릭 시 원본 값 | ⬜ | |
| E6 | 되묻기 화면: 후보 + 근거, missing_inputs 입력 폼 → 재요청 | 동명 선박(B01) 케이스 흐름 | ⬜ | |
| E7 | 실패 화면: partial · failed 원인, 마지막 확인 시각, 다음 행동 | 타임아웃 모의 시 표시 | ⬜ | |
| E8 | 채팅 후속 질의 UI | 근거 범위 답변 표시 | ⬜ | |
| E9 | 재생 모드 (데모 B/L 3개, "재생" 배지) | API 키 없이도 시연 가능 | 🔶 | 백엔드 재생 완료(키 없는 데모 3건). 화면 배지 남음 |
| E10 | 소개 페이지 (한 줄 정의, 지표 표, 아키텍처 그림) | Vercel에 공개 | ⬜ | |
| E11 | 조회 이력 화면 (A12 응답 렌더) | 이력 목록에서 클릭 시 해당 판정으로 | ⬜ | |

## F. 마감 작업

| # | 작업 | 상태 | 비고 |
| --- | --- | --- | --- |
| F1 | 데모 영상: 정상 · 실패 · 되묻기 | ⬜ | |
| F2 | Langfuse 스크린샷 3장 이상 (트레이스 상세 1장 포함) | 🔶 | 캡처 9장 있음(서류 사진 · 판정 · 실험 비교). 제출용 선정 남음 |
| F3 | README 최종: 한 줄 정의, 지표 표, compose up, 아키텍처 | ⬜ | |
| F4 | .env.example 점검, 민감값 커밋 검사 (git log grep) | ⬜ | |
| F5 | 다른 노트북에서 10분 재현 테스트 | ⬜ | |
| F6 | 10/8 자정 태그 `v1.0-freeze` | ⬜ | |

## G. 확장 (최소 범위, 09-30 결정)

| # | 작업 | 최소 범위 | 상태 | 비고 |
| --- | --- | --- | --- | --- |
| G1 | 서류 사진 1차 | 사진 → OCR(B/L 가림) → LLM이 7칸 채움 | ✅ | 가공 서류 확인, 옆으로 누운 사진도 읽음 |
| G3 | 로그인 · 사용자 ID | 간단 로그인, 조회를 사용자에 묶기 | ⬜ | 지금은 세션 ID로 구분 |
| G4 | 메모리 | 지난 조회로 "이 B/L 다시 볼까요?" 제안 | ⬜ | G3 뒤 |
| G5 | 등록 · 감시 · 알림 | 등록한 B/L 목록 + 주기 재판정 · 변화 감지 + 다음 접속 때 바뀐 판정 표시 | ⬜ | 수집 워커 · 스케줄러는 있음. ShipFinder 하루 50회 안에서 척수 · 주기를 정한다 |

하지 않는 것과 확장 가능성(이번 범위 밖)은 PRD 4절과 09-30 회의록을 따른다: 어려운 판정을 대형 모델로 넘기기는 하지 않고, 판정 파인튜닝 · 서류 사진 2차(1차가 못 읽은 사진을 모델이 직접 읽기, 배포 뒤 끝까지 측정해서 필요하면 소형 모델 하나 추가) · 알림 발송(이메일 · 푸시) · 부산 외 · 해외 항만 · 대형 화주는 확장 가능성으로 남긴다.

## 경계 정리 (겹치기 쉬운 곳)

| 경계 | 어느 작업 | 아닌 작업 |
| --- | --- | --- |
| freshness 판정 | C-4 signals.py | B4는 last_time만 반환 |
| 등급 | C-12 verdict.py 판정 표 | LLM은 설명 · 회색 지대 올리기만 |
| 프롬프트 | C-11 내용 · 등록 | D4 fetch 코드 · 버전 링크 |
| Langfuse 트레이스 | D3 | C-6은 llm.py 본체만 |
| UNI-PASS | A8 클라이언트 · 정제 | C는 정제 결과(C5)만 소비 |
| days_margin | C-8 evidence.py 코드 계산 | LLM 출력값은 덮어씀 |

## 의존 관계 (무엇이 무엇을 기다리나)

```
계약 C1~C8 ─┬─> A6 라우터 ──> E4 결과 화면
            ├─> B3~B7 도구 ──> C-5, C-6 판정 ──> D8 평가 실행
            ├─> C-4 신호 판정 ──> C-12 판정 표 · D7 베이스라인 (a)
            └─> D1 워커 ──> D2 실적 ──> G5 등록 · 감시
G3 로그인 ──> G4 메모리 · G5 등록 · 감시
A4 배포 ──> B10 MCP 캡처 · E1 Vercel 연결
```

## Claude Code에 넘길 때

각 항목마다 이렇게 넘기면 SDD 흐름에 맞는다.

1. 계약 파일(C1~C8) 경로와 PRD 해당 장 번호를 함께 준다
2. "완료 기준" 열을 그대로 테스트 조건으로 쓴다
3. 금지 사항을 명시한다: langgraph 설치 금지, 벡터 검색 · 청킹 금지, 라우터에서 LLM SDK import 금지, 프롬프트 문자열 코드 하드코딩 금지(Langfuse Prompt)
4. 외부 API 응답은 실제와 형식만 같은 가공 JSON을 fixture로 준다. 실제 응답 원본은 약관상 레포에 올리지 않는다 (SDD 7절)
