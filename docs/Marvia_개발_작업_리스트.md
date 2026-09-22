# Marvia 개발 작업 리스트

기준: PRD (2026-09-22). 코드 동결 10/8 자정. 작업일 12일.
팀원 4명 병행을 전제로 A~E 다섯 묶음. 묶음 사이는 **계약(인터페이스)**으로만 이어지고, 계약을 먼저 고정하면 서로 기다리지 않고 개발할 수 있다.

## 0. 먼저 고정할 계약 (9/23, 전원)

병행 개발의 전제다. 이게 없으면 나중에 맞추는 데 하루가 간다.

| 계약 | 내용 | 파일 |
| --- | --- | --- |
| C1 응답 스키마 | PRD 12장 Pydantic 모델. status, verdict, vessel_match, reasons, conflicts, actions, days_margin, evidence 등 | `app/schemas/agent.py` |
| C2 요청 스키마 | bl_no, bl_type(M/H), sale_due_date, session_id, follow_up_question | `app/schemas/agent.py` |
| C3 1층 신호 출력 | 신호 6종 각각 triggered / clear / unknown + 값 + 출처 | `app/schemas/signals.py` |
| C4 MCP 도구 4종 입출력 | PRD 11장 표 그대로. 모든 출력에 source, fetched_at 포함 | `mcp_server/schemas.py` |
| C5 UNI-PASS 정제 결과 | ship_name, ship_nat, voyage, entry_date, stage_history, shed_name. LLM에 안 넘기는 필드(품명, 중량) 제외 | `app/schemas/customs.py` |
| C6 Skill 임계값 | 6시간, 12시간, 0.5노트, 24시간, 부산 반경 | `skills/ais-reliability/rules.md` 프론트매터 |
| C7 평가 레코드 | 스냅샷 1건 = 입력(C2) + 신호(C3) + 정답 verdict + 정답 vessel_match + 라벨러 + 사유 | `eval/schema.py` |
| C8 환경변수 | .env.example 키 목록 | `.env.example` |

레포 구조도 이날 만든다.

```
repo/
  app/            FastAPI (라우터, 서비스, 스키마)
  mcp_server/     FastMCP
  skills/         Skill 문서
  worker/         수집 워커
  eval/           평가셋, 베이스라인, 리포트
  web/            Next.js
  docker-compose.yml  Dockerfile  .env.example  README.md
```

## A. 백엔드 골격과 배포 (담당 1명)

인터뷰·판정 로직과 무관. 9/22부터 착수.

| # | 작업 | 완료 기준 | 시점 |
| --- | --- | --- | --- |
| A1 | FastAPI 프로젝트 생성, `GET /health`, `/docs` | 로컬에서 200 | 9/22 |
| A2 | Pydantic 스키마 C1·C2·C5 코드화 | import 되고 예시 JSON이 검증 통과 | 9/23 |
| A3 | Dockerfile, docker-compose.yml (app + postgres + mcp) | `docker compose up` 한 줄로 전체 기동 | 9/23 |
| A4 | Cloud Run 빈 배포, URL 확보 | 외부에서 /health 200 | 9/25 |
| A5 | 구조화 로그 미들웨어 (요청 ID, 모델, 토큰, 지연) | 로그 1건에 4필드 | 9/29 |
| A6 | `POST /api/agent` 라우터. 서비스 계층 호출만, LLM SDK import 금지 | 라우터에 openai/anthropic import 없음 | 9/30 |
| A7 | B/L 형식 검증, 범위 밖 입력 거절 | 잘못된 형식 400, 정상 통과 | 9/30 |
| A8 | UNI-PASS 클라이언트 (`unipass.customs.go.kr:38010`, TLS 1.2, 도메인 호출), 응답 → C5 정제, 필드 마스킹 | 실제 B/L 1건 조회 성공 또는 모의 응답으로 파싱 통과 | 10/1 |
| A9 | 실패 경로: 외부 API 타임아웃·5xx 재시도 2회 + 백오프, partial 응답 | 모의 지연으로 재시도 로그 확인 | 10/2 |
| A10 | CORS, /mcp 토큰 인증, 비밀값 서버 환경변수만 | 브라우저에서 키 노출 없음 | 10/2 |
| A11 | README 실행 절차 (clone → .env → compose up, 10분) | 팀원 다른 사람이 처음 클론해서 재현 | 10/7 |

## B. MCP 서버와 데이터 소스 (담당 1명)

| # | 작업 | 완료 기준 | 시점 |
| --- | --- | --- | --- |
| B1 | FastMCP 서버 뼈대, Streamable HTTP `/mcp` | MCP 클라이언트(Claude Desktop 또는 langchain-mcp-adapters)로 tool 목록 조회 | 9/23 |
| B2 | ShipFinder 클라이언트: VesselSearch, VesselPositionSingle. status 코드 매핑(0, 3, 9, 21, 23, 29) | 오늘 확인한 MMSI 440063450 조회 성공 | 9/23 |
| B3 | 도구 `get_vessel_candidates`: 후보 목록 + 유사도 + last_time. 같은 IMO면 최신 MMSI만 | PANSTAR 검색 시 후보 복수 반환 | 9/29 |
| B4 | 도구 `get_live_position`: 원본 값과 last_time 반환 (freshness 판정은 C-4가 함) | MMSI 440063461 조회 시 last_time이 7월 값으로 반환 | 9/29 |
| B5 | 해수부 클라이언트: 관제정보(`CntlVssl2/Info`, 부산 prtAgCd), 선박운항정보. 호출부호·선명으로 조회 | 부산항 입항 예정 목록 1회 수신 | 9/30 |
| B6 | 도구 `get_port_schedule`: 입항 예정·실적, 접안 시설(fcltyNm) | 실제 선박 1척 매칭 | 10/1 |
| B7 | searoute 도구 `estimate_distance` (Docker 안에서 빌드) | 부산까지 해리 반환 | 9/30 |
| B8 | ShipFinder 23·29 대응 캐시 (최근 값 + 캐시 시각) | 빈도 초과 모의 시 캐시 응답 | 10/2 |
| B9 | tool_description 다듬기: 언제 쓰는 도구인지 한 문장 | 팀원 리뷰 통과 | 10/2 |
| B10 | /mcp 연결 스크린샷, tool 목록·호출 결과 캡처 | 제출물 확보 | 10/7 |

## C. 판정 로직, LLM 호출, Skill (담당 1명 + 함정 경험 팀원 검수)

C1~C6 계약 고정 뒤 착수. 9/28부터 본격.

| # | 작업 | 완료 기준 | 시점 |
| --- | --- | --- | --- |
| C-1 | `skills/ais-reliability/SKILL.md` + `rules.md`(임계값 프론트매터). 신호 6종 정의, 상충 우선순위, 2층 판정 원칙, 되묻기 조건 | 팀원 검수 서명 | 9/27 |
| C-2 | `skills/customs-stages/SKILL.md`: 단계 코드(CAGE12 등) 목록, 의미, 다음 단계, 할 일, 관세사 확인 조건 | 단계 코드 전체 확보 | 9/29 |
| C-3 | `skills/port-busan/SKILL.md`: 부두·정박지 개요, 하역 장소 문장 규칙 | 팀원 검수 | 9/30 |
| C-4 | 1층 신호 판정 코드 (`app/services/signals.py`): rules.md 읽어 6종 판정 → C3 | 단위 테스트 12건 통과 | 9/29 |
| C-5 | 선박 식별 로직: 후보 1척이면 코드 확정, 복수면 LLM 판단, uncertain이면 판정 차단 | PANSTAR 케이스가 uncertain | 9/30 |
| C-6 | `services/llm.py`: OpenRouter 호출 단일 지점, Skill 주입, tool call 루프, 모델 A/B 스위치 | 라우터 밖에서 LLM SDK import 없음 | 9/30 |
| C-7 | 출력 검증 7규칙 (PRD 12장) + 3단계 재시도 + 폴백 | 위반 응답 주입 시 재시도 트레이스 | 10/1 |
| C-8 | days_margin 코드 계산, LLM 덮어쓰기 금지 울타리 | LLM이 다른 값 내도 코드 값 유지 | 10/1 |
| C-9 | 후속 질의: 근거 범위 밖 질문 거절 | "비트코인 시세" 거절 | 10/2 |
| C-10 | 신뢰 경계: 도구 응답·dest 문자열 속 지시문 무시 | dest에 지시문 넣은 케이스 통과 | 10/2 |
| C-11 | 프롬프트 v1 내용 작성, Langfuse에 등록 (연동 코드는 D4) | Langfuse에 prompt v1 존재 | 10/1 |

## D. 관측, 수집 워커, 평가 (담당 1명)

**D1은 9/22 최우선.** 라벨이 입항 결과에서 나오므로 하루 늦으면 평가셋이 준다.

| # | 작업 | 완료 기준 | 시점 |
| --- | --- | --- | --- |
| D1 | 수집 워커: 해수부 입항 예정에서 부산행 20~30척 선정 → MMSI 확정 → 3~6시간마다 위치 저장 (Postgres) | 9/22 밤부터 기록 쌓임 | 9/22 |
| D2 | 입항 실적 수집: 관제정보 aprtfEtryptDt 저장 | 입항 완료 선박에 실제 시각 기록 | 9/23 |
| D3 | Langfuse 트레이스 데코레이터·미들웨어를 C-6 llm.py와 MCP 호출에 적용, user_id·session_id, 재시도 표시 (C-6 완료 다음 날) | 대시보드에 trace 1건 | 10/1 |
| D4 | Langfuse Prompt fetch 코드(`get_prompt`), 버전 → 트레이스 링크 (프롬프트 내용은 C-11) | trace에 prompt 버전 표시 | 10/1 |
| D5 | 평가셋 30건 구성 (C7 스키마): 정상 10, 경계 12(판정형 7·보류형 5), 실패 8. 가상 B/L·통관·판매 예정일 부여 | Langfuse Dataset 업로드 | 10/6 |
| D6 | 라벨링: 팀원이 스냅샷 보고 verdict·vessel_match 정답, 사유 기록. 사후 입항 시각으로 예측 적중 별도 | 30건 라벨 완료 | 10/6 |
| D7 | 베이스라인 (a) 규칙만: 1층 결과 → verdict, 유사도 최고 후보 자동 선택 | 30건 실행 결과 | 10/1 |
| D8 | 평가 실행기: (a)(b)(c) 세 구성 × 30건, 축 7개 채점 (verdict_accuracy, act_recall, insufficient_precision, vessel_match_accuracy, customs_explanation judge, grounded, schema_pass) | 결과 표 자동 생성 | 10/6 |
| D9 | LLM-as-judge: customs_explanation 판정 모델 ≠ 생성 모델, judge trace 연결 | 표본 5건 사람 대조 | 10/6 |
| D10 | 개선 실험 1회: prompt v2 (한 가지만 변경) → 재측정 | KEEP/DISCARD 기록 | 10/7 |
| D11 | EVAL_REPORT.md: 평가셋 구성, 베이스라인 비교, 전후 지표, 회귀 문항, 실패 사례, 판정 방식·한계 | 게이트 5개 판정 표시 | 10/8 |
| D12 | 운영 지표: p50/p95, 요청당 비용, 계약 준수율 | README 지표 표 | 10/8 |

## E. 프론트엔드 (담당 1명, A6 API 계약 확정 후)

| # | 작업 | 완료 기준 | 시점 |
| --- | --- | --- | --- |
| E1 | Next.js 프로젝트, Vercel 빈 배포 | URL 확보 | 9/25 |
| E2 | 입력 폼: B/L, M/H 구분, 판매 예정일. 입력 가이드 문구 | 형식 오류 인라인 표시 | 9/30 |
| E3 | 조회 진행 표시 (식별 → 위치 → 판정 단계) | 로딩 상태 3단계 | 10/1 |
| E4 | 결과 화면: 판정 배지(fine/watch/act), 할 일, 지도(stale은 흐리게), 화물 카드, 통관 타임라인, 하역 장소 | C1 응답 전 필드 렌더 | 10/3 |
| E5 | 근거 카드: evidence 목록 (출처, 값, 조회 시각) | 클릭 시 원본 값 | 10/3 |
| E6 | 되묻기 화면: vessel_candidates 후보 + 근거, missing_inputs 입력 폼 → 재요청 | PANSTAR 케이스 흐름 | 10/6 |
| E7 | 실패 화면: status failed/partial 원인, 마지막 확인 시각, 다음 행동 | 타임아웃 모의 시 표시 | 10/6 |
| E8 | 채팅 후속 질의 UI | 근거 범위 답변 표시 | 10/6 |
| E9 | 저장 데이터 재생 모드 (데모용 B/L 3개, "재생" 배지) | API 장애 시에도 시연 가능 | 10/7 |
| E10 | 소개 페이지 (한 줄 정의, 지표 표, 아키텍처 그림) | Vercel에 공개 | 10/8 |

## F. 마감 작업 (전원, 10/6~10/8)

| # | 작업 | 담당 |
| --- | --- | --- |
| F1 | 데모 영상: 정상(장면 1), 실패(장면 3), 되묻기(장면 2) | E + C |
| F2 | Langfuse 스크린샷 3장 (트레이스 상세 1장 포함) | D |
| F3 | README 최종: 한 줄 정의, 지표 표, compose up, 아키텍처 | A |
| F4 | .env.example 점검, 민감값 커밋 검사 (git log grep) | A |
| F5 | 다른 팀원 노트북에서 10분 재현 테스트 | 전원 |
| F6 | 10/8 자정 태그 `v1.0-freeze` | A |

## 경계 정리 (겹치기 쉬운 곳)

| 경계 | 누가 | 누가 아님 |
| --- | --- | --- |
| freshness 판정 | C-4 signals.py | B4는 last_time만 반환 |
| 프롬프트 | C-11 내용·등록 | D4 fetch 코드·버전 링크 |
| Langfuse 트레이스 | D3 데코레이터 | C-6은 llm.py 본체만 |
| UNI-PASS | A8 클라이언트·정제 | C는 정제 결과(C5)만 소비 |
| days_margin | C-8 evidence.py 코드 계산 | LLM 출력값은 덮어씀 |

## 의존 관계 (누가 누굴 기다리나)

```
계약 C1~C8 (9/23) ─┬─> A6 라우터 ──> E4 결과 화면
                   ├─> B3~B7 도구 ──> C-5, C-6 판정 ──> D8 평가 실행
                   ├─> C-4 신호 판정 ──> D7 베이스라인 (a)
                   └─> D1 워커 ──> D2 실적 ──> D5, D6 평가셋·라벨
```

- D1 워커는 계약을 기다리지 않는다. 9/22에 바로.
- E는 A6 전까지 C1 스키마의 모의 JSON으로 화면을 만든다.
- C-6 LLM 호출은 B 도구가 없어도 모의 도구로 먼저 짤 수 있다.

## Claude Code에 넘길 때

각 항목마다 이렇게 넘기면 SDD 흐름에 맞는다.

1. 계약 파일(C1~C8) 경로와 PRD 해당 장 번호를 함께 준다
2. "완료 기준" 열을 그대로 테스트 조건으로 쓴다
3. 금지 사항을 명시한다: langgraph 설치 금지, 벡터 검색·청킹 금지, 라우터에서 LLM SDK import 금지, 프롬프트 문자열 코드 하드코딩 금지(Langfuse Prompt)
4. 외부 API 응답은 저장한 실제 JSON을 fixture로 준다 (오늘 받은 ShipFinder 응답 5건이 첫 fixture)
