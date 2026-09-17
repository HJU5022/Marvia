# CONVERGE

"어디에 뭐가 있나"를 담는 지도다. 규칙은 CLAUDE.md, 실행법은 README.md, 상세 설계는 docs/SDD.md.

## 1. 한 장 흐름

```
사용자 (브라우저)
  │  문장 또는 카톡 캡처
  ▼
frontend/            Next.js. 지도 + 채팅
  │  app/api/agent/route.ts 가 대신 호출 (키가 여기서 멈춤)
  ▼
backend/app/         FastAPI. POST /api/agent
  │
  ├─ services/pipeline.py 가 0~8단계를 순서대로 부른다 (SDD 5절)
  │    0 vision      캡처 → 텍스트                 [LLM]
  │    1 extract     텍스트 → Slots                [소형 LLM]
  │    2 geocode     지명 → 좌표. 확신 낮으면 사용자 핀 확인
  │    3 candidates  집결 후보 (위병소·로비·랜드마크)
  │    4 routes      참석자 × 후보 소요시간
  │    5 rules       절차 소요·전환 조건·access_ok  [domain/, 계산]
  │    6 judge       순위·이유                     [대형 LLM, 라우팅 시만]
  │    7 departure   출발 시각 역산                  [domain/, 계산]
  │    8 store       암호화 저장
  │
  ├─ services/       바깥과 통신 (LLM, 카카오, TMAP, Postgres)
  ├─ domain/         계산만. 네트워크·LLM 없음
  └─ mcp_server/     같은 프로세스에 /mcp 로 마운트. 2·3·4단계가 쓰는 도구
  │
  ▼
AgentResponse (stage: need_confirm | need_info | done | out_of_scope | failed)
  ▼
지도에 핀·경로선·표
```

LLM은 0·1·6단계에만 있다. 나머지는 코드다. 이것이 이 프로젝트의 핵심 주장이다 (PRD 3절).

## 2. 폴더 → 책임 → 여는 파일

| 폴더 | 한 줄 책임 | 먼저 여는 파일 | SDD |
|---|---|---|---|
| `backend/` | API·파이프라인·관측 | `backend/BACKEND_GUIDE.md` | 2·5절 |
| `backend/app/schemas/` | 출력 계약 원본. 필드는 여기서만 | (BACKEND_GUIDE) | 3·4절 |
| `backend/app/services/` | 바깥과 통신하는 것만 | (BACKEND_GUIDE) | 5절 |
| `backend/app/domain/` | 계산만. 규칙 적용·역산·라우팅 판단 | `backend/app/domain/CLAUDE.md` (자동 로드) | 5·7절 |
| `backend/tests/` | 키 없이 도는 자동 테스트, fixtures | `backend/tests/TEST_GUIDE.md` | |
| `mcp_server/` | 지도·경로·시각표 API를 MCP 도구 7개로 | `mcp_server/MCP_GUIDE.md` | 6절 |
| `frontend/` | 화면, 백엔드 프록시, 소개 페이지, 공유 링크 | `frontend/FRONTEND_GUIDE.md` | 2절 |
| `skills/converge/` | 현장 규칙과 규칙값의 원본, 프리셋 2개 | `skills/converge/SKILL.md` | 7절 |
| `evals/` | 평가셋 30건, 실행 | `evals/EVAL_GUIDE.md` | 8절 |
| `finetune/` | 소형 모델 학습. 배포 이미지에 안 들어감 | `finetune/FINETUNE_GUIDE.md` | |
| `docs/` | PRD·SDD·테이블정의서, 제출 증거물(`evidence/`) | `docs/SDD.md` | |
| `scripts/` | 손으로 돌리는 것. 타입 생성 등 | 파일 상단 주석 | |

루트: `README.md`(채점자) · `CLAUDE.md`(AI 규칙) · `EVAL_REPORT.md`(제출물) · `Dockerfile`(빌드 컨텍스트는 루트, skills/·mcp_server/ 포함).

## 3. 경계 세 개

이 구조의 전부다. 나머지는 이 셋의 결과다.

### services/ 와 domain/

| | `services/` | `domain/` |
|---|---|---|
| 네트워크 | 씀 | 안 씀 |
| API 키 | 필요 | 필요 없음 |
| 테스트 | `fixtures/`로 대체 | 그냥 돌아감 |

`domain/`의 import 목록에 `httpx`·`openai`가 없어야 한다. 이게 "가운데는 결정적"의 증명이다.

### tests/ 와 외부 API

테스트는 진짜 카카오·TMAP을 부르지 않는다. 무료 한도를 먹고 CI에 키가 없다. `backend/tests/fixtures/`의 저장된 응답을 쓴다. 진짜 호출은 `scripts/`.

### 원본과 사본

| 원본 | 사본 | 맞추는 법 |
|---|---|---|
| `backend/app/schemas/` | `frontend/lib/api-types.ts` | `scripts/gen_types.sh`. CI가 어긋남 검사 |
| `skills/converge/rules/*.md` 프론트매터 | 코드가 쓰는 규칙값 | `backend/app/domain/rules.py`가 읽는다 |
| `docs/SDD.md` | 이 파일, 각 `*_GUIDE.md` | 사람이 맞춘다. SDD를 먼저 고친다 |

사본을 손으로 고치지 않는다.

## 4. 무엇을 고치면 어디를 봐야 하나

| 하려는 것 | 지나가는 곳 |
|---|---|
| 응답 필드 추가·변경 | SDD 3·4절 → `schemas/` → `scripts/gen_types.sh` → `frontend/components/` |
| 규칙값 바꾸기 | `skills/converge/rules/*.md` 프론트매터 → `backend/tests/` (domain 테스트) |
| 새 외부 API | `services/`에 함수 → `mcp_server/tools/`에 도구 → `MCP_GUIDE.md` 표 |
| 파이프라인 단계 | SDD 5절 표 → `services/pipeline.py` → `backend/tests/` |
| 프롬프트 | Langfuse Prompt에서 (코드 아님). 이름은 SDD 8절 |
| 화면 상태 | `AgentResponse.stage` (SDD 2절) → `frontend/FRONTEND_GUIDE.md` 표 |
| DB 컬럼 | `docs/테이블정의서.md` → `services/store.py` |

## 5. 아직 없는 것

SDD 1절이 가리키지만 아직 안 만든 파일. 만들면 여기서 지운다.

- `backend/app/`: `routers/` `schemas/` `observability/` 안의 `.py`, `services/`의 vision·geo·routes·judge·pipeline·store·auth, `domain/`의 rules·router
- `mcp_server/tools/` 7개
- `frontend/` 전부 (`app/` `components/` `lib/`)
- `skills/converge/`: `failures.md` `output-contract.md` `rules/` 5개 `presets/` 2개
- `evals/run_eval.py`
- `finetune/`: `gen_dataset.py`, `data/finetune_dataset.jsonl` (Info/에 있음, 아직 안 옮김)
- `scripts/gen_types.sh`
- `backend/tests/` 테스트 파일
- `README.md` Converge 내용 (지금은 스캐폴딩 그대로)
