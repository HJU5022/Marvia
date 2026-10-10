# backend

FastAPI 서버다. 요청을 검증하고 서비스를 불러 판정(순항·주의·긴급)과 화면 기능을 돌려준다. 레포 루트가 Docker 빌드 컨텍스트다. 지켜야 할 규칙(LLM SDK는 `services/llm.py`에서만, 프롬프트는 Langfuse, 임계값은 `skills/*/rules.md`)은 [CLAUDE.md "하지 말 것"](../CLAUDE.md#하지-말-것)에 있다.

## 지도

| 경로 | 역할 |
|---|---|
| `app/main.py` | 진입점. 라우터 등록, 미들웨어, `/health`, `/mcp` 연결. 켜질 때 `DATABASE_URL`이 있으면 마이그레이션을 자동 적용한다 |
| `app/auth.py`, `app/crypto.py` | 로그인 토큰(JWT) 확인, B/L 원본과 개인정보(회원 정보·운영자 이메일) 암호화, 이메일 지문 |
| `app/routers/` | 요청 검증, 서비스 호출, 응답. 판정과 LLM 호출은 하지 않는다 (아래 표) |
| `app/services/` | 업무 로직 (아래 표) |
| `app/schemas/` | 출력 계약 원본: `agent.py`, `signals.py`, `customs.py`, `document.py`, `memory.py` |
| `app/clients/` | 외부 API(`shipfinder`, `mof`, `kakao`, `supabase_admin`)와 `cache`, `retry`, `replay`(REPLAY_MODE 재생) |
| `app/observability/` | `langfuse.py`(span, 프롬프트 가져오기), `logging.py`(구조화 JSON 로그) |
| `app/db/migrations/` | 번호 001~023, 파일 27개. 016, 017, 018, 021은 번호마다 파일이 2개다. 이름 순서대로 한 번씩 적용한다(`app/db/__init__.py`의 `apply_migrations`). 표 설명은 [docs/ERD.md](../docs/ERD.md) |
| `app/prompts/` | Langfuse에서 못 가져올 때 쓰는 프롬프트 사본 10개(`marvia-*.md`) |
| `tests/` | pytest. 키 없이 돈다. `unit/`(함수·모듈), `integration/`(라우터·채팅 경로), `contract/`(스키마·프롬프트 파일), `fixtures/`, `conftest.py` |

## 라우터 (`app/routers/`)

| 파일 | 엔드포인트 |
|---|---|
| `agent.py` | `POST /api/agent`. 등급 검사 V8도 여기서 한다 |
| `chat.py` | `POST /api/chat`, `POST /api/chat/stream`(SSE), `GET /api/vessels/detail` |
| `history.py` | `GET`·`DELETE /api/history`, `GET /api/usage` |
| `conversations.py` | `GET /api/conversations`, `GET`·`DELETE /api/conversations/{conv_id}` |
| `document.py` | `POST /api/document`, `POST /api/document/bl` |
| `memory.py` | `GET`·`DELETE /api/memory`, `DELETE /api/memory/items/{item_id}`, `POST /api/memory/document-facts` |
| `profile.py` | `GET`·`PUT /api/profile` |
| `account.py` | `DELETE /api/account` |
| `admin.py` | `GET /api/me`, `/api/admin/*`(고객 조회·수정·정지·재개·탈퇴·마스킹 해제, 운영자 등록·해제, 작업 이력), `GET /api/metrics` |
| `kakao.py` | `GET /api/kakao/status`, `POST /api/kakao/connect`·`callback`·`test`, `DELETE /api/kakao/link` |
| `watch.py` | `GET /api/watch`, `GET /api/watch/changes`, `POST /api/watch/changes/seen`, `GET`·`POST /api/watch/vessels`, `DELETE /api/watch/vessels/{mmsi}`, `PUT /api/cargo/watch`, `POST /api/cargo/watch/state` |
| `cargo_sheet.py` | `GET /api/cargo/sheet`, `GET /api/cargo/sheet.xlsx`, `PUT /api/cargo/sheet/{cargo_key}/lc`·`departed` |

## 서비스 (`app/services/`)

| 위치 | 맡는 일 | 주요 파일 |
|---|---|---|
| 맨 위 | LLM 호출 단일 지점과 MCP 도구 호출 | `llm.py`(SDK import는 여기서만, 프롬프트별 Skill 묶음), `llm_config` `llm_types` `llm_schemas` `llm_support`, `mcp_client.py` |
| `judge/` | B/L 한 건을 판정하는 흐름 전체와 그 앞뒤 처리 | 조회 `customs`, 선박 식별 `identify` `vessel_match` `mrn_fallback` `bl_parse`, 1층 신호 `signals`, 2층 판정 표 `verdict`, 출력 검증 `validate`, 근거·여유 일수 `evidence`, rules.md 읽기 `rules`, 프롬프트 주입 걸러내기 `guard`, 고정 문구·응답 조립 `answers` `builders`, 지난 응답 값 `saved` |
| `chat/` | 자연어 창구와 서류 사진 | `chat.py`(채팅 에이전트), `tools.py`(에이전트 도구 `AGENT_TOOLS`), `referrals.py`(확인처 줄), `doc_ocr.py`(서류 사진 읽기), `progress.py`, `citations.py`, `conversations.py`. 나머지는 `chat.py`에서 나눈 문구·정규식·상수·순수 함수다 |
| `account/` | 회원, 기억, 하루 토큰 한도, 운영자 | `memory`, `profile`, `account`, `quota`, `pii_patterns`, `operators`, `customers`, `metrics` |
| `watch/` | 화물 현황 표, 지켜보기, 알림 | `cargo`, `cargo_sheet`, `watch`, `vessel_watch`, `vessel_pick`, `vessel_detail`, `kakao` |

출력 검증 규칙 V1~V15의 뜻은 [docs/Marvia_SDD.md](../docs/Marvia_SDD.md) 5.7절에 있다. V8(등급이 판정 표와 같은지)만 `routers/agent.py`에 있고 나머지는 `services/judge/validate.py`에 있다.

## 실행과 테스트

```bash
docker compose up                      # api :8000, worker, postgres
pytest backend/tests mcp_server/tests  # 키 없이 fixture로. .github/workflows/tests.yml과 같은 범위
```

설정은 루트 `.env.example`을 따른다. `REPLAY_MODE=true`면 `evals/fixtures/`의 가공 응답으로 키 없이 동작한다. 전체 실행 방법은 [CLAUDE.md "실행"](../CLAUDE.md#실행)에 있다.
