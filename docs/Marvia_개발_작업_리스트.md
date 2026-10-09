# Marvia 개발 작업 리스트

기준: PRD (2026-09-22). 코드 동결 10/8 자정. 실사용 점검 항목은 I절에만 적었고 아래 진행률 표에는 들어 있지 않다.
팀원 2명, 둘 다 풀스택. A~G 묶음은 담당을 정하지 않고 열린 작업을 누구든 가져간다. 함정 경험이 필요한 Skill 검수와 라벨 확정만 해당 경험이 있는 팀원이 맡는다. 묶음 사이는 **계약(인터페이스)**으로만 이어지고, 계약을 먼저 고정하면 서로 기다리지 않고 개발할 수 있다.

상태: ✅ 완료 · 🔁 바뀜(계획과 다른 모습으로 구현, 비고에 무엇이 바뀌었는지) · 🚫 안 함 · 🔶 일부 (남은 것은 비고) · ⬜ 남음. 완료는 완료 기준을 테스트나 실행으로 확인한 것만 적는다.

**상태 확인 방법:** 상태는 코드 · 폴더 · git log · `docs/release_manifest.json`을 읽어 적었다. 이 정리 중에 서버를 띄우거나 화면을 실행해 본 것은 아니다. 새로 확인했다고 적은 것은 코드와 파일이 있다는 뜻이고, 실행 확인이 안 된 것은 비고에 "확인하지 못했다"로 적었다. `🚫 안 함`으로 표시한 작업은 없다(계획에서 뺀 작업은 모두 대체 구현이 있어 🔁로 적었다).

## 진행률

| 묶음 | 완료 · 바뀜 | 일부 | 남음 | 진행률 |
| --- | --- | --- | --- | --- |
| A. 백엔드 골격과 배포 | 12 | 1 | 1 | 89% |
| B. MCP 서버와 데이터 소스 | 9 | 1 | 0 | 95% |
| C. 판정 로직, LLM 호출, Skill (Skill 검수: 함정 경험 보유 팀원) | 12 | 0 | 0 | 100% |
| D. 관측, 수집 워커, 평가 | 10 | 3 | 1 | 82% |
| E. 프론트엔드 | 10 | 1 | 0 | 95% |
| F. 마감 작업 | 1 | 1 | 4 | 25% |
| G. 확장 (최소 범위) | 4 | 0 | 0 | 100% |

> 진행률 = (완료 + 바뀜 + 일부 × 0.5) ÷ 항목 수. 집계는 아래 각 표의 상태 열을 센 값이다 (H는 제외).

## 0. 먼저 고정할 계약 (9/23, 전원)

병행 개발의 전제다. 바꾸면 평가셋, fixture, 프론트가 같이 깨지므로 PR 리뷰를 거친다.

| 계약 | 내용 | 파일 |
| --- | --- | --- |
| C1 응답 스키마 | status(ok · partial · insufficient · failed · unsupported), verdict, decided_by, vessel_match, reasons, conflicts, actions, days_margin, evidence 등 | `backend/app/schemas/agent.py` |
| C2 요청 스키마 | bl_no, bl_type(M/H) 필수. sale_due_date · forwarder_eta · voyage_no · resolved_mmsi · follow_up_question · session_id 선택 (판매 예정일은 선택 입력) | `backend/app/schemas/agent.py` |
| C3 1층 신호 출력 | 신호 7종 각각 triggered / clear / unknown + 값 + 출처 | `backend/app/schemas/signals.py` |
| C4 MCP 도구 4종 입출력 | 모든 출력에 source, fetched_at 포함. 실패는 {error: {code, message, retryable}} | `mcp_server/schemas.py` |
| C5 UNI-PASS 정제 결과 | ship_name, ship_nat, voyage, entry_date, stage_history, shed_name. LLM에 안 넘기는 필드(중량) 제외 (품명 goods_name은 저장하고 채팅 에이전트에만 준다, 판정 LLM에는 안 준다) | `backend/app/schemas/customs.py` |
| C6 Skill 임계값 | 오래된 위치 6시간 · ETA 상충 12시간 · 정지 속도 0.5노트 · 정박 24시간 · 부산 반경 30해리 · 여유 부족 2일 | `skills/ais-reliability/rules.md` 프론트매터 |
| C7 평가 레코드 | 입력(C2) + 가공 fixtures + 정답 status · verdict · vessel_match · 물을 것 + 라벨러 + 사유 | `evals/schema.py` |
| C8 환경변수 | .env.example 키 목록 | `.env.example` |

레포 구조 (실제):

```
proj2-5/
  backend/app/    FastAPI (라우터, 서비스, 스키마, 클라이언트, 관측, 프롬프트 사본)
  mcp_server/     FastMCP 도구 4종 (/mcp는 API 서버 안의 경로)
  skills/         Skill 문서 5종 (ais-reliability, customs-stages, port-busan, cargo-verdict, referrals) + 임계값
  worker/         수집 워커(collector.py), 지켜보는 화물 재판정(watch.py), run.py
  evals/          평가셋 30건 + 서류 12건, 베이스라인, 실행기, 검증 모델 채점, 재생 fixture
  scripts/        손으로 돌리는 확인 스크립트 (MCP 확인, 데모 파일 생성, 실패 훈련 등)
  web/            Next.js 16 (있음. 경로 /, /watch, /cargo, /history, /settings, /admin, /metrics, /about)
  docker-compose.yml  Dockerfile  Dockerfile.railway  .env.example  README.md  EVAL_REPORT.md
```

## A. 백엔드 골격과 배포

| # | 작업 | 완료 기준 | 상태 | 비고 |
| --- | --- | --- | --- | --- |
| A1 | FastAPI 프로젝트 생성, `GET /health`, `/docs` | 로컬에서 200 | ✅ | |
| A2 | Pydantic 스키마 C1·C2·C5 코드화 | import 되고 예시 JSON이 검증 통과 | ✅ | |
| A3 | Dockerfile, docker-compose.yml (api + worker + postgres) | `docker compose up` 한 줄로 전체 기동 | ✅ 완료 | MCP는 api 안의 `/mcp`. 서류 사진 OCR 패키지는 api 이미지에만. compose는 api · worker · db(postgres 16) 세 서비스. 배포용 `Dockerfile.railway` 추가 |
| A4 | Cloud Run 배포 (서비스 1개, `/mcp` 포함), URL 확보 | 외부에서 /health 200, `/mcp` 토큰 없이 401 | 🔁 바뀜 | Cloud Run 주소에서 MCP가 421로 막히던 문제는 미리 고쳤다. Cloud Run 대신 Railway에 배포. API `marvia-api`, 화면 `marvia-web`, 재생 모드. 주소는 `docs/release_manifest.json`. 외부 /health 200과 /mcp 401을 이 문서 정리 중 직접 확인하지는 않았다 |
| A5 | 구조화 로그 미들웨어 (요청 ID, 모델, 토큰, 지연) | 로그 1건에 4필드 | ✅ | 실패는 `failure stage=… error=…` 한 줄 |
| A6 | `POST /api/agent` 라우터. 서비스 계층 호출만, LLM SDK import 금지 | 라우터에 openai/anthropic import 없음 | ✅ | |
| A7 | B/L 형식 검증, 범위 밖 입력 거절 | 잘못된 형식 400, 정상 통과. 부산 외 항만은 unsupported | ✅ | |
| A8 | UNI-PASS 클라이언트, 응답 → C5 정제, 필드 마스킹 | 실제 B/L 1건 조회 성공 또는 모의 응답으로 파싱 통과 | ✅ | 실제 B/L 1건 MRN 식별까지 확인 |
| A9 | 실패 경로: 외부 API 타임아웃 · 5xx 재시도 2회 + 백오프, partial 응답 | 모의 지연으로 재시도 로그 확인 | ✅ | 실패 훈련 스크립트 `scripts/eval/failure_drill.py` |
| A10 | CORS, /mcp 토큰 인증, 비밀값 서버 환경변수만 | 브라우저에서 키 노출 없음, 토큰 없으면 401 | ✅ | 배포 때 `MCP_TOKEN`을 새로 만들어 넣는다 |
| A11 | README 실행 절차 (clone → .env → compose up, 10분) | 다른 사람이 처음 클론해서 재현 | ✅ 완료 | 키 없이 도는 데모 3건 절차 작성 · 로컬과 Docker로 확인. 다른 사람 재현은 하지 않았다 (F5). README에 키 없는 데모 13건(라이브 10 + 평가셋 3) 절차. 다른 사람 재현은 F5에서 확인하지 못했다 |
| A12 | `GET /api/history` 라우터. query_log를 session_id로 읽기만 | agent 2회 호출 뒤 같은 세션 조회 시 2건, 다른 세션 0건 | ✅ | |
| A13 | 배포 환경 trace: 배포 주소로 조회 1건이 Langfuse에 남는지 | 배포 URL 요청의 trace 1건 확인 | ⬜ 남음 | 체크포인트 D10. A4 뒤. 배포 주소 trace 기록은 레포에서 확인하지 못했다 (EVAL_REPORT 8절에 없다고 적혀 있다) |
| A14 | release manifest(배포한 이미지 · 커밋 · 프롬프트 버전 · 모델 기록)와 rollback(이전 버전으로 되돌리기) | 한 번 되돌려 보고 /health 200 | 🔶 일부 | 체크포인트 D10. A4 뒤. `docs/release_manifest.json`(2026-10-06-r1)에 이미지·커밋·프롬프트 버전·모델·rollback 절차가 있다. 한 번 되돌려 본 기록은 확인하지 못했다 |

## B. MCP 서버와 데이터 소스

| # | 작업 | 완료 기준 | 상태 | 비고 |
| --- | --- | --- | --- | --- |
| B1 | FastMCP 서버, Streamable HTTP `/mcp` | MCP 클라이언트로 tool 목록 조회 | ✅ 완료 | API 서버 안으로 합쳤다. 우리 서비스는 도구 함수를 직접 부르고, `/mcp`는 외부 AI 프로그램용. 우리 서비스도 자기 `/mcp`를 MCP 프로토콜로 부른다(`services/mcp_client.py`). `MCP_URL`이 없으면 같은 프로세스에 메모리로 붙는다 |
| B2 | ShipFinder 클라이언트: VesselSearch, VesselPositionSingle. status 코드 매핑(0, 3, 9, 13, 21, 23, 29) | 실제 선박 1척 MMSI 조회 성공(MMSI는 로컬에만) | ✅ | |
| B3 | 도구 `get_vessel_candidates`: 후보 목록 + 유사도 + last_time. 같은 IMO면 최신 MMSI만 | 동명 선박 검색 시 후보 복수 반환 | ✅ | |
| B4 | 도구 `get_live_position`: 원본 값과 last_time 반환 (freshness 판정은 C-4가 함) | 실제 선박 1척 조회 | ✅ | |
| B5 | 해수부 클라이언트: 관제정보(`CntlVssl2`), 선박운항정보(`VsslEtrynd5`). 호출부호 · 선명으로 조회 | 부산항 입항 예정 목록 1회 수신 | ✅ | |
| B6 | 도구 `get_port_schedule`: 입항 예정 · 실적, 접안 시설 | 실제 선박 1척 매칭 | ✅ | |
| B7 | searoute 도구 `estimate_distance` | 부산까지 해리 반환 | ✅ | |
| B8 | ShipFinder 캐시 (최근 값 + 캐시 시각) | 빈도 초과 모의 시 캐시 응답 | ✅ 완료 | 23 · 29는 6시간 안 캐시, 타임아웃은 오래된 캐시도 쓰고 partial (평가 F02). ShipFinder 한도 소진 status 38 처리 추가(`e19c43c`) |
| B9 | tool_description: 언제 쓰는 도구인지 한 문장 | 리뷰 통과 | ✅ | 설명에 판단 · 지시 표현 금지 테스트 |
| B10 | /mcp 연결 스크린샷, tool 목록 · 호출 결과 캡처 | 제출물 확보 | 🔶 일부 | 로컬에서 MCP 클라이언트로 연결 · 도구 4개 · 호출 확인. 배포 주소로 찍은 캡처는 없다. `docs/evidence/B10-mcp-연결-도구목록-호출.png`(langchain-mcp-adapters 클라이언트) 있음. 배포 주소로 찍은 캡처인지는 확인하지 못했다 |

## C. 판정 로직, LLM 호출, Skill (Skill 검수: 함정 경험 보유 팀원)

| # | 작업 | 완료 기준 | 상태 | 비고 |
| --- | --- | --- | --- | --- |
| C-1 | `skills/ais-reliability/SKILL.md` + `rules.md`. 신호 7종, 상충 우선순위, 판정 표, 되묻기 조건 | 함정 경험 보유 팀원 검수 | ✅ | 판정 표 예외(깨진 목적지 · 항해상태 불일치), 판매일 없을 때, 날짜 말하기 추가 |
| C-2 | `skills/customs-stages/SKILL.md`: 실제 처리구분 이름, 의미, 다음 단계, 할 일, 관세사 확인 조건 | 단계 전체 확보 | ✅ | 실제 처리구분 10단계. "사용자가 할 일" 칸 함정 경험 보유 팀원 확인 |
| C-3 | `skills/port-busan/SKILL.md`: 부두 · 정박지 개요, 하역 장소 문장 규칙 | 함정 경험 보유 팀원 검수 | ✅ | |
| C-4 | 1층 신호 판정 코드 (`services/judge/signals.py`): rules.md 읽어 7종 판정 → C3 | 단위 테스트 통과 | ✅ | 정박 시간은 워커 위치 이력으로 잰다 |
| C-5 | 선박 식별: 후보 1척이면 코드 확정, 복수면 LLM 판단, uncertain이면 판정 차단 | 동명 선박(B01) 케이스가 uncertain | ✅ | MRN 호출부호 · 세관 국적과 다르면 1척이어도 되묻기 |
| C-6 | `services/llm.py`: LLM 호출 단일 지점, Skill 주입, 모델 A/B 스위치 | 라우터 밖에서 LLM SDK import 없음 | ✅ 완료 | 도구는 코드가 순서대로 부른다(LLM이 도구를 고르지 않음). Vertex(`vertex/`)와 OpenRouter 두 길. 키 없는 데모는 녹화 답 재생. 판정 흐름은 코드가 도구를 순서대로 부르지만, 후속 질문과 채팅 에이전트는 LLM이 읽기 전용 MCP 도구를 골라 쓴다(`services/chat/chat.py`). OpenRouter와 Vertex(`vertex/`) 두 길 |
| C-7 | 출력 검증 V1~V8 + 3단계 재시도 + 폴백 | 위반 응답 주입 시 재시도 트레이스 | ✅ 완료 | V8 등급 검사. 폴백은 판정 표 등급 + 고정 문구로 partial, failed는 통관 조회 실패만. 검증 규칙이 V1~V15까지 늘었다(V9·V10 주입 방어, V11 통관 진행 평가 금지 등) |
| C-8 | days_margin 코드 계산, LLM 덮어쓰기 금지 울타리 | LLM이 다른 값 내도 코드 값 유지 | ✅ | 판매일 없으면 null |
| C-9 | 후속 질의: 근거 범위 밖 질문 거절 | "비트코인 시세" 거절 | ✅ | 후속 답도 V1 · V7 검사 |
| C-10 | 신뢰 경계: 도구 응답 · dest 문자열 속 지시문 무시 | dest에 지시문 넣은 케이스 통과 | ✅ | 평가 주입 3건 통과 |
| C-11 | 프롬프트 작성, Langfuse에 등록 (연동 코드는 D4) | Langfuse에 prompt 존재 | 🔁 바뀜 | 처음엔 judge · pick-vessel · follow-up · judge-eval · doc-extract 5종이었고 지금은 10종이다. 이력은 `docs/prompt_versions.md`: chat-agent · chat-route · chat-title · doc-extract · follow-up · judge · judge-eval · pick-vessel · port-match는 Langfuse, memory-write는 레포 파일(`backend/app/prompts/`). 9개에 Langfuse 라벨 v1 |
| C-12 | 등급은 판정 표 코드로 (`services/judge/verdict.py`), 회색 지대만 LLM이 올리기 | 판정 표와 다른 등급이면 V8, 회색 지대는 표 이상만 | ✅ | 30건 판정 정확도 100% |

## D. 관측, 수집 워커, 평가

| # | 작업 | 완료 기준 | 상태 | 비고 |
| --- | --- | --- | --- | --- |
| D1 | 수집 워커: 부산 입항 예정 컨테이너선 최대 12척 선정 → 6시간마다 위치 저장 (ShipFinder 하루 50회 안) | 기록 쌓임 | 🔶 | 코드 완료. 스케줄러 기본 꺼짐이라 주기 가동은 안 함. 사용자 화물 배 위치를 `watch_positions`(마이그레이션 017)에 쌓는 수집 추가 |
| D2 | 입항 실적 수집: 관제정보 · 선박운항정보 저장 | 입항 완료 선박에 실제 시각 기록 | 🔶 | 코드 완료. D1과 같이 주기 가동 안 함 |
| D3 | Langfuse 트레이스: llm.py 호출마다 generation, session_id, 재시도 · 모델 · 토큰 · 비용 | 대시보드에 trace 1건 | ✅ 완료 | 서버 종료 때 남은 트레이스 전송 |
| D4 | Langfuse Prompt fetch 코드(`get_prompt`), 버전 → 트레이스 링크 | trace에 prompt 버전 표시 | ✅ | |
| D5 | 평가셋 30건: 정상 8, 경계 14(판정 9 · 되묻기 5), 실패 8. 가상 B/L · 통관 · 판매 예정일 | Langfuse Dataset 업로드 | ✅ | `marvia-golden-30`. 평가 실행이 문항별로 연결된다 |
| D6 | 라벨링: 문항마다 판정자 · 사유. 사후 입항 시각으로 예측 적중 별도 | 30건 라벨 완료 | 🔶 | 30건 라벨 완료(판정자 · 사유). 라벨 날짜 비어 있음 · 사후 입항 적중은 안 함. 없는 상황 4개(판매일 없음 · 도착일 모름 · 여유 0~1일 · 회색 지대) 문항은 평가셋에 아직 없다 |
| D7 | 베이스라인 (a) 규칙만 | 30건 실행 결과 | ✅ 완료 | 27/30. (a) 규칙만 `a_20261006_2158.json` exact 29/30, 판정 정확도 1.0 (처음 측정한 원본은 27/30) |
| D8 | 평가 실행기: (a)(b)(c) × 30건, 축 7개 채점 | 결과 표 자동 생성 | ✅ | 결과는 실행마다 새 파일 (`evals/results/<구성>_<시각>.json`) |
| D9 | LLM-as-judge: 통관 해설 채점 모델(gpt-4o-mini) ≠ 생성 모델 | 표본 5건 사람 대조 | ✅ 완료 | 채점 연결 · 20/21 통과. 사람 대조 5건 완료: 채점 모델과 4/5 일치, 어긋난 1건은 표에 없는 단계(검사지정)를 풀어 쓴 문장을 뜻 추측으로 감점. 기록 `evals/results/grader_check_20261001.md`. 채점 모델은 gpt-4o-mini에서 gemini-2.5-flash로 바꿨다. `docs/release_manifest.json`의 eval_grader는 claude-haiku-4.5 |
| D10 | 개선 실험: 한 가지만 바꿔 재측정 | KEEP/DISCARD 기록 | ✅ 완료 | 등급을 판정 표로(27 → 30/30), 생각 끄기 등 실험 여러 번. EVAL_REPORT 형식 정리 남음. EVAL_REPORT 4절에 KEEP/DISCARD 6건 |
| D11 | EVAL_REPORT.md: 평가셋 구성, 베이스라인 비교, 전후 지표, 실패 사례, 판정 방식 · 한계 | 게이트 판정 표시 | ✅ 완료 | 틀만 있음. EVAL_REPORT 1~9절 작성됨. 비용 상한은 "미정"으로 적혀 있다(7절) |
| D12 | 운영 지표: p50/p95, 요청당 비용, 계약 준수율 | README 지표 표 | ✅ 완료 | 숫자는 측정됨(p95 3.8초 · 요청당 약 2.4원), README 표 비어 있음. README 5절 지표 표 + 결과 파일 값 |
| D13 | 계약 준수율 100건 이상 측정 (스키마 · V1~V15 통과율) | 100건 이상 실행 결과 파일 | ✅ 완료 | 가이드 채점 ② "100건+ 준수율". 평가셋 30건은 LLM 호출이 약 30번이라 따로 돌려야 한다. EVAL_REPORT 9-2, (b) 5회 출력 112개 중 위반 2개(98.2%). 출력 단위 기준이고 같은 30종류를 5번 반복한 값 |
| D14 | 재조정 가설 한 줄 (배포 환경 trace를 보고 무엇을 바꾸면 나아질지) | EVAL_REPORT에 한 줄 | ⬜ 남음 | 체크포인트 D10. D11의 "한 가지만 바꾸기"가 이 가설을 검증한다. EVAL_REPORT에서 "재조정 가설" 문구는 찾지 못했다. 8절 약점 목록이 가까운 내용 |

## E. 프론트엔드

`web/`(Next.js 16)가 있다. 처음 계획은 입력 폼 + 결과 화면이었고 실제는 채팅 중심 화면이다. 화면 목업(마누스 시안)은 레포 밖에 있다. 백엔드 응답(C1)은 확정.

| # | 작업 | 완료 기준 | 상태 | 비고 |
| --- | --- | --- | --- | --- |
| E1 | Next.js 프로젝트, Vercel 배포 | URL 확보 | 🔁 바뀜 | Next.js 16 프로젝트 `web/` 있음. 배포는 Vercel이 아니라 Railway `marvia-web` |
| E2 | 입력 폼: B/L(필수), M/H 구분, 판매 예정일(선택), 서류 사진 | 형식 오류 인라인 표시 | 🔁 바뀜 | 판매 예정일은 선택 입력. 입력 폼이 아니라 채팅 입력창(`ChatBar`·`lib/composer.ts`)과 서류 패널(`DocumentPanel`)로 바뀜. 서류는 사진과 PDF |
| E3 | 조회 진행 표시 (식별 → 위치 → 판정 단계) | 로딩 상태 3단계 | ✅ 완료 | `lib/progress.ts`, 단계 표시(`docs/specs/chat-progress.md`) |
| E4 | 결과 화면: 판정 배지(fine/watch/act), 할 일, 지도(stale은 흐리게), 화물 카드, 통관 타임라인, 하역 장소 | C1 응답 전 필드 렌더 | ✅ 완료 | `VerdictCard` · `MapPanel`/`VesselMap` · `CustomsTimeline` · `VesselCard`. 등급 화면 이름은 순항 · 주의 · 긴급 |
| E5 | 근거 카드: evidence 목록 (출처, 값, 조회 시각) | 클릭 시 원본 값 | ✅ 완료 | `EvidenceCards` |
| E6 | 되묻기 화면: 후보 + 근거, missing_inputs 입력 폼 → 재요청 | 동명 선박(B01) 케이스 흐름 | ✅ 완료 | `CandidatePicker` |
| E7 | 실패 화면: partial · failed 원인, 마지막 확인 시각, 다음 행동 | 타임아웃 모의 시 표시 | ✅ 완료 | `FailureBanner` |
| E8 | 채팅 후속 질의 UI | 근거 범위 답변 표시 | 🔁 바뀜 | 별도 후속 질의 UI가 아니라 채팅 화면 자체가 질의 창구(`ChatBar`, `/api/chat/stream`) |
| E9 | 재생 모드 (데모 B/L 3개, "재생" 배지) | API 키 없이도 시연 가능 | 🔶 일부 | 백엔드 재생 완료(키 없는 데모 13건). `TopBar`에 데모 모드는 있으나 "재생" 배지 문구는 코드에서 찾지 못했다 |
| E10 | 소개 페이지 (한 줄 정의, 지표 표, 아키텍처 그림) | Vercel에 공개 | ✅ 완료 | `web/app/about`. 공개는 Railway |
| E11 | 조회 이력 화면 (A12 응답 렌더) | 이력 목록에서 클릭 시 해당 판정으로 | ✅ 완료 | `/history` · `HistoryTable` |

## F. 마감 작업

| # | 작업 | 상태 | 비고 |
| --- | --- | --- | --- |
| F1 | 데모 영상: 정상 · 실패 · 되묻기 | ⬜ | |
| F2 | Langfuse 스크린샷 3장 이상 (트레이스 상세 1장 포함) | 🔶 | 레포에는 Langfuse 집계 파일(`docs/evidence/langfuse_summary.md`)과 MCP 연결 캡처 1장만 있다. 대시보드 · 트레이스 상세 · 재시도 트레이스 · demo 환경 트레이스는 EVAL_REPORT 1절 파일 이름 목록대로 담당자가 찍어 `docs/evidence/`에 넣는다 |
| F3 | README 최종: 한 줄 정의, 지표 표, compose up, 아키텍처 | ✅ 완료 | README에 한 줄 정의 · 지표 표 · compose up · 흐름도 |
| F4 | .env.example 점검, 민감값 커밋 검사 (git log grep) | ⬜ | |
| F5 | 다른 노트북에서 10분 재현 테스트 | ⬜ | |
| F6 | 10/8 자정 태그 `v1.0-freeze` | ⬜ | |

## G. 확장 (최소 범위)

| # | 작업 | 최소 범위 | 상태 | 비고 |
| --- | --- | --- | --- | --- |
| G1 | 서류 사진 1차 | 사진 → OCR(B/L 가림) → LLM이 7칸 채움 | ✅ 완료 | 가공 서류 확인, 옆으로 누운 사진도 읽음. PDF도 받는다(첫 2쪽, 글자층 먼저, 열 수 없으면 400 `invalid_pdf`). 서류에서 출항일(etd) 칸도 읽는다 |
| G3 | 로그인 · 사용자 ID | 간단 로그인, 조회를 사용자에 묶기 | ✅ 완료 | 백엔드 완료(구글 로그인 토큰 확인 · 로그인 필수 · B/L 암호화 · 삭제 3종, 트레이스 user_id). 실제 구글 로그인은 화면 연결 뒤 확인. 화면 로그인 연결됨(`LoginScreen`, `lib/auth.ts`). 실제 구글 로그인 동작은 이 문서 정리 중 확인하지 못했다 |
| G4 | 메모리 | 지난 조회로 "이 B/L 다시 볼까요?" 제안 | 🔁 바뀜 | G3 뒤. "이 B/L 다시 볼까요?" 제안 대신 화물 비서 기억(`/api/memory`, 마이그레이션 014)과 채팅에서 "지켜볼까요?" 제안으로 구현. 일반 대화에서도 기억을 뽑는다 |
| G5 | 등록 · 감시 · 알림 | 등록한 B/L 목록 + 주기 재판정 · 변화 감지 + 다음 접속 때 바뀐 판정 표시 | 🔁 바뀜 | 수집 워커 · 스케줄러는 있음. ShipFinder 하루 50회 안에서 척수 · 주기를 정한다. 등록·감시는 `/api/watch`와 `worker/watch.py`(재판정은 `WATCH_ENABLED` 기본 꺼짐), 알림은 이메일·푸시가 아니라 카카오톡 "나에게 보내기"(`/api/kakao/*`). 다음 접속 때 바뀐 판정을 채팅 첫 말로 보여 준다 |

하지 않는 것과 확장 가능성(이번 범위 밖)은 PRD 4절을 따른다 (알림은 카카오톡으로, 서류는 PDF까지 만들었다. 아래 목록에서 "알림 발송"은 이메일 · 푸시를 뜻하며 만들지 않았다): 어려운 판정을 대형 모델로 넘기기는 하지 않고, 판정 파인튜닝 · 서류 사진 2차(1차가 못 읽은 사진을 모델이 직접 읽기, 배포 뒤 끝까지 측정해서 필요하면 소형 모델 하나 추가) · 알림 발송(이메일 · 푸시) · 부산 외 · 해외 항만 · 대형 화주는 확장 가능성으로 남긴다.

## H. 처음 목록에 없던 것 (코드와 마이그레이션이 있는 것만)

작업 ID 없이 만들어진 기능이다. 근거는 `backend/app/routers/`, `db/migrations/`, `web/app/`, `docs/specs/`. 완료 기준을 따로 세우지 않았고 동작은 이 정리 중 실행해 확인하지 않았다.

| 기능 | 코드 | 비고 |
| --- | --- | --- |
| 대화 목록 (새 대화 · 지난 대화 열기 · 삭제) | `routers/conversations.py`, 마이그레이션 018_conversations | |
| 채팅 에이전트 · 웹 검색 도구 · 스트림 | `routers/chat.py`, `services/chat/chat.py` | |
| 카카오톡 알림 연결 | `routers/kakao.py`, `clients/kakao.py`, 마이그레이션 016_kakao_links, 022 | 연결 · 시험 발송 · 채팅에서 "지금 보내 줘" |
| 내 화물 현황표 · 엑셀 받기 | `routers/cargo_sheet.py`, 마이그레이션 019 | 신용장별 묶음 |
| 품명(goods_name) · 선명 저장 | 마이그레이션 020, 021_cargo_vessel_name | 품명은 채팅 에이전트에만 준다 |
| 컨테이너 번호 가리기와 번호로 화물 찾기 | `services/chat/chat.py` 등 | |
| 운영자 · 고객 관리 · 지표 | `routers/admin.py`, 마이그레이션 009 ~ 013 | 운영자 이메일 암호화 |
| 하루 토큰 한도 | `services/account/quota.py`, 마이그레이션 016_token_usage | 1명당 `DAILY_TOKENS_PER_USER` |
| 안내처(referrals) | `skills/referrals/`, `services/chat/referrals.py` | |
| 서버 마이그레이션 자동 적용 | `backend/app/main.py` → `db.apply_migrations` | 001 ~ 023 |

## I. 실사용 점검 (항목 32~81)

작업 ID 없이 실사용 점검 번호로 받은 일이다. PR #79(병합됨, `26ba901`)와 PR #83(병합됨, `9bed960`). 프롬프트는 Langfuse chat-agent 13 · follow-up 9(라벨 v4)로 등록했고 production 글이 레포 파일과 같음을 Langfuse를 읽어 확인했다 (`docs/release_manifest.json` r4, `docs/prompt_versions.md`). 완료 기준 열의 숫자는 실행한 값이다: pytest backend/tests mcp_server/tests 2145 passed, web tsc 오류 0, verify-contract PASS, e2e 데모 56 PASS (라이브는 SKIP). 실제 모델에서 [E#] 근거 번호가 만들어지는지 확인하지 않았다. Railway는 10-07 ~17:25 KST에 배포했고 `marvia-api`에 MOF_BASE_URL · MOF_RELAY_TOKEN이 설정돼 있다(`docs/release_manifest.json` r5). 항목 80 · 81은 로컬 커밋이고 이 PR들에 들어 있지 않다.

| 항목 | 작업 | 커밋 | 완료 기준 | 상태 | 비고 |
| --- | --- | --- | --- | --- | --- |
| 34·35·38·52·54 | 채팅 답: 도구만 돈 뒤 답이 비거나 검사(V7·V9·V10·V13)에 걸리면 한 번 고쳐 묻고, 그래도 안 되면 도구 결과를 코드로 문장화(lookup_fallback). 입항 검색 답에 가까운 순 5척 이름과 도착 예정일. 해요체. 같은 B/L 결과 없음이 반복되면 마스터·하우스 바꿔 보기, 세 번째엔 포워더·선사 확인 안내 | `480ac64` | pytest backend/tests mcp_server/tests 2099 passed (커밋 시점) | ✅ 완료 | 해요체 프롬프트는 Langfuse 13 · 9로 등록. 실제 모델 답은 확인하지 않았다 |
| 33 | 해수부 연결 실패는 한 번 다시 시도, 차단 60초 → 15초, "잠시 후 다시 시도" 안내 | `00f4e65` | 위 pytest 통과에 포함 | ✅ 완료 | 운영 채팅의 입항 선박 검색이 서울 중계를 거쳐 실제 선박 목록을 돌려줬다. 차단 시간은 `clients/mof.py` `CIRCUIT_OPEN_SEC` 15초 |
| 32·39~47·49·53·55·56 | 화면 정리: 상단바 "대화" 버튼 삭제, 서류 첨부를 입력칸 클립 버튼과 끌어다 놓기로(파일 칩 + 확인 카드, 설명과 함께 바로 조회), 미니 지도 직선 점선 삭제와 캡션, 말풍선 · 대화 열 여백, 대화 제목 표시, 입력칸 안내 문구, 대화 목록 누르면 대화 화면으로, 바뀐 게 없으면 저장 비활성, 결과 없음 제목 "조회 결과를 찾지 못했어요" | `47d7c76` | tsc 통과, e2e 데모 52 PASS (라이브 SKIP, 커밋 시점), verify.mjs 서류 검사를 새 첨부 방식으로 | ✅ 완료 | 마지막 e2e는 56 PASS |
| 48 | 설정 탭 4개로 정리, 조회 이력 탭은 사이드바로, 탭 이름 "알림·판정 기준" | `19ead92` `8cee37d` | verify.mjs 설정 탭 4개 포함(`8cee37d`), web tsc 오류 0 | ✅ 완료 | |
| 36·37 | 채팅에 화면의 배(on_screen)를 함께 보내기, 되묻기 후보를 채팅 칩으로 고르기 | `8cee37d` | 위 pytest · tsc · e2e 통과에 포함 | ✅ 완료 | on_screen 입력은 chat-agent 13. 실제 모델 확인하지 않았다 |
| 57 | B/L 없이 배만 지켜보기: 마이그레이션 023_vessel_watch, `/api/watch/vessels` (GET/POST/DELETE), 워커 위치 수집 포함(판정 · 알림 없음). 채팅 후보 칩과 여러 화물 비교표의 배 옆 지켜보기 버튼. 입항 목록의 배도 호출부호로 선박 번호를 찾아 정확히 1척일 때만 | `28e5dc5` `e3f37ba` `07a4441` | 위 pytest · tsc · e2e 통과에 포함 | 🔶 일부 | 감시한 배의 판정과 알림은 만들지 않았다. 023 마이그레이션을 서버 DB에 적용했는지는 확인하지 않았다 |
| 58 | 답 문장 끝 근거 번호 [E#]: 번호 검사(`citations.py`), 응답의 evidence_items · citations, 대화 저장 포함, 답 속 근거 팝업과 대화별 근거 모음, 체험용 모의 근거 | `1ed63e7` `5834390` `81beee4` | 위 pytest · tsc · verify-contract · e2e 통과에 포함. 채팅 계약은 더하기만 (ChatRequest.on_screen, ChatResponse.evidence_items · citations) | 🔶 일부 | 실제 모델이 [E#]를 만드는지 확인하지 않았다 |
| 64·66 | 지켜보기 배 고르기: 같은 호출부호가 여러 척이면 선명 같은 배, 그다음 최근 신호 배(`vessel_pick.py`, 상세와 같은 규칙). 한도 소진은 503 "오늘 선박 조회 한도를 다 썼어요". 지켜볼 때 상세 캐시의 위치 저장, 목록을 열 때 6시간(rules.md position_stale_hours) 넘은 위치만 새로 받기(최대 5척). ShipFinder 호출 Langfuse span(키·주소 없음) | `5f24e99` | pytest 2163 통과 | 🔶 일부 | 운영 로그에서 many_match로 대부분 실패하던 것. 배포 뒤 실서버 확인은 하지 않았다 |
| 64·66·67·68 | 지켜보기 화면: 상세에서 찾은 MMSI를 눈 버튼이 그대로 사용, 오류는 작은 글 5초, 도착 예정 "10월 8일 08:00", 빈 상자 문구 사실대로, 배만 지켜보기도 지도 표시 | `3fc1120` | web tsc 오류 0, e2e 통과에 포함 | ✅ 완료 | |
| 59·61·62·65 | 나뉜 화면에서도 사이드바 대화 목록, 입항 검색 답을 결론·배 한 줄씩·출처로, 답 끝 근거 표시를 출처 이름으로, 예시 질문 2열 격자 | `19386c2` | pytest · tsc · e2e 통과에 포함 | ✅ 완료 | |
| 접근성 | 소개 페이지 하단 띠 글자 흰색(대비 4.26 → 4.5 이상) | `92989e0` | e2e 56 PASS exit 0 (axe 위반 0) | ✅ 완료 | #78·#81에서 생긴 대비 |
| 60·63 | | | | 나중에 | 60 소개 페이지 화면 사진 교체는 하지 않았다(프론트 확정 뒤로 미뤘다). 63 배 이름 한글·영문 섞임은 해수부 원본 선명 그대로라 고치지 않았다 |
| 50 | | | | 보류 | |
| 51 | | | | 일부 | 서류 확인 뒤 입력칸에 붙여 넣던 것을 바로 조회(채팅 전송)로 바꿈 (`47d7c76`). 서류에서 읽은 항차·포워더 입항일을 채팅 요청에 싣는 것은 건너뜀: 되묻기 화면 미리 채움으로 충분하다. 이후 73번(`15560af`)에서 칩만 두고 보내기에서 B/L만 읽는 방식으로 다시 바뀜 |
| 69 | 지켜보기 지도의 배만 지켜보기 마커를 다른 지도와 같은 방향 화살표 + 작은 이름표로, 자세한 건 팝업, MMSI별 하나만 | `7eb6445` | web tsc 오류 0, e2e 통과에 포함 | ✅ 완료 |마커 모양은 아래 '감시 지도 핀 · 클러스터 맞추기'에서 화물 핀과 같은 알파벳 핀으로 다시 바뀌었다 |
| 70 | 사이드바 '내 화물' 빼기(대화 화면과 같은 곳으로 가는 중복), 경로 표시 앞 '내 화물 /' 삭제, 사이드바 설명 문서 정리 | `5ca12c3` `97e23be` | 위와 같음 | ✅ 완료 | |
| 71 | 서류 붙이기는 칩만, 보내기 전엔 아무것도 안 보냄, 확인 카드는 읽기 전용 + 수정 버튼 하나 | `aba9d2a` | 위와 같음 | ✅ 완료 | 73번에서 확인 카드가 없어졌다 |
| 72 | 서류 B/L 이름표를 못 읽어도 선사 코드 + 숫자 모양 번호가 하나면 B/L로, 입항 예정일 없으면 경고 대신 안내, SEP.25.2026 같은 날짜 인식 | `40762ec` | pytest 통과에 포함 | ✅ 완료 | |
| 73 | 서류 첨부는 칩만 두고 보내기에서 B/L만 코드로 읽어 바로 조회(`POST /api/document/bl`, LLM 없음), 사진만 · 사진 + 글 · 글만 보내기 지원 | `15560af` | pytest · tsc · e2e 통과에 포함 | ✅ 완료 | 51번 참고 |
| 74 | OCR 스레드를 컨테이너 CPU 쿼터에 맞춰 1~4개로 제한(`OCR_THREADS`). 서버에서 사진 한 장 126초 걸리던 문제 | `5c3630e` | pytest 통과에 포함 | ✅ 완료 | 배포 서버 속도는 이 목록에서 다시 재지 않았다 |
| 75 | B/L 구분을 말하지 않으면 하우스로 조회하고 없으면 바로 마스터로 재조회, 구분 되묻기 제거, 못 찾은 화물의 감시 등록은 사실대로 안내 | `b688dc8` | pytest 통과에 포함 | ✅ 완료 | |
| 76 | 메모 저장을 답과 동시에 돌리고 거래처는 역할 없이도 저장한 뒤 역할 · 전화를 되묻기, mini 10초 · 최대 3번 시도, 실패 · 버린 칸은 사용자에게 알림 | `5da58bf` | pytest 통과에 포함 | ✅ 완료 | |
| 77 | 배 목록 답을 상자 없는 한 줄 목록으로(이름 · 도착 시각 한 줄, 아래 직전 기항지), 나머지 N척 전체 보기 버튼 | `574b85b` `a5fe014` | tsc · e2e 통과에 포함 | ✅ 완료 | |
| 78 | 저장된 대화를 다시 열 때 가장 최근 선박 · 화물 답으로 화면을 정해 지도가 사라지지 않게 | `f90501f` | 위와 같음 | ✅ 완료 | |
| 79 | 채팅 딴소리 구조 수정과 채팅으로 배 감시(`watch_vessel`), chat-agent 14 프롬프트(정리본 3758 → 3030 단어) | `d715999` `00cb06a` | 실행: pytest 2242 passed, tsc 오류 0, verify-contract PASS, e2e 데모 PASS (라이브 SKIP). 지시문 A/B는 EVAL_REPORT 4-2절 | ✅ 완료 | Langfuse chat-agent 14 등록(10-07 17:23 KST) |
| 80 | 새 대화 첫 질문을 보내는 즉시 활성 대화 · 사이드바 임시 항목으로, 돌아오면 저장될 때까지 다시 열기 | `da0b4dc` (로컬 커밋) | 이 목록에서 다시 실행하지 않음 | 🔶 일부 | 병합하지 않은 로컬 커밋 |
| 81 | 채팅에서 저장한 메모 꺼내 보기 `recall_memo`, 메모 질문은 웹으로 보내지 않음 | `787593a` (로컬 커밋) | 이 목록에서 다시 실행하지 않음 | 🔶 일부 | 병합하지 않은 로컬 커밋. 레포 chat-agent 파일은 15 후보(recall_memo 2줄)이고 Langfuse에는 등록하지 않았다. 운영 production은 14 |
| 감시 지도 핀 · 클러스터 맞추기 | 배만 지켜보는 배도 화물과 같은 동그라미 알파벳 핀(화물 다음 글자)과 같은 클러스터 · 상세 창으로. 판정 없음은 흰 바탕 회색 점선 핀, 오른쪽 내 화물 목록에는 넣지 않음. 말풍선 · 상세 창 글자 줄바꿈 | `ec506b6` `b93ba50` (PR #85) | web tsc 오류 0. 로컬 가짜 API(모의값 화물 3 · 배 2)로 클러스터 · 점선 핀 · 상세 창 · 말풍선 화면 확인 | 🔶 일부 | 실제 모드 화면은 확인하지 않았다. 69번의 방향 화살표를 바꾼다 |
| 조회 이력 원본 B/L 검색 | 가린 값(bl_masked)의 * 자리는 아무 글자와 맞는 자리로 보고 보이는 글자끼리 비교해 원본 B/L · 앞뒤 일부로도 찾기. 안내 문구 "B/L 번호 검색" | `f39ac7f` (PR #85) | web tsc 오류 0, 일치 · 불일치 예를 node로 확인 | ✅ 완료 | 원본은 서버 밖으로 나가지 않는다. 가린 값이 같은 다른 화물은 같이 보일 수 있다 |

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
A4 배포(Railway) ──> B10 MCP 캡처 · E1 화면 배포 연결
```

## Claude Code에 넘길 때

각 항목마다 이렇게 넘기면 SDD 흐름에 맞는다.

1. 계약 파일(C1~C8) 경로와 PRD 해당 장 번호를 함께 준다
2. "완료 기준" 열을 그대로 테스트 조건으로 쓴다
3. 금지 사항을 명시한다: langgraph 설치 금지, 벡터 검색 · 청킹 금지, 라우터에서 LLM SDK import 금지, 프롬프트 문자열 코드 하드코딩 금지(Langfuse Prompt)
4. 외부 API 응답은 실제와 형식만 같은 가공 JSON을 fixture로 준다. 실제 응답 원본은 약관상 레포에 올리지 않는다 (SDD 7절)
