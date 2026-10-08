# backend

FastAPI 서버. 요청을 검증하고, 서비스를 불러 판정(순항·주의·긴급)과 화면 기능을 돌려준다. 레포 루트가 Docker 빌드 컨텍스트다.

| 구분 | 내용 |
|---|---|
| 책임 | 판정 흐름(조회, 선박 식별, 신호 계산, 판정 표, LLM 설명, 검증, 근거 조립)과 채팅, 기억, 지켜보기, 알림, 운영자 화면의 API |
| 하지 않는 것 | LLM SDK import는 `app/services/llm.py`에서만. 프롬프트를 코드에 문자열로 두지 않는다(Langfuse Prompt). 임계값을 숫자로 적지 않는다(`skills/*/rules.md`) |

## 지도

| 경로 | 역할 |
|---|---|
| `app/main.py` | FastAPI 진입점. 라우터 등록, 미들웨어, `/health`, `/mcp` 마운트. 서버가 켜질 때 `DATABASE_URL`이 있으면 `db.apply_migrations`로 마이그레이션을 자동 적용 |
| `app/auth.py`, `app/crypto.py` | 로그인 토큰(JWT) 확인, B/L 원본 암호화 |
| `app/routers/` | 요청 검증, 서비스 호출, 응답. 판정과 LLM 호출은 하지 않는다 |
| `app/schemas/` | 출력 계약 원본(`agent.py`, `signals.py`, `customs.py`, `document.py`, `memory.py`) |
| `app/services/` | 업무 로직. `llm*.py`·`mcp_client.py`와 네 묶음 폴더 `judge/` `chat/` `account/` `watch/` (아래) |
| `app/clients/` | 외부 API 클라이언트(`shipfinder`, `mof`, `kakao`, `supabase_admin`)와 `cache`, `retry`, `replay`(REPLAY_MODE 재생) |
| `app/observability/` | `langfuse.py`(span), `logging.py`(구조화 JSON 로그) |
| `app/db/migrations/` | `001`~`023` `*.sql`, 이름 순서대로 한 번씩 적용 |
| `app/prompts/` | Langfuse에서 못 가져올 때 쓰는 프롬프트 사본(`marvia-*.md`) |
| `tests/` | pytest. 키 없이 돈다. `unit/`(함수·모듈), `integration/`(라우터·채팅 경로), `contract/`(스키마·프롬프트 파일), 공통 `conftest.py`, `fixtures/` |

## 라우터와 엔드포인트

| 파일 | 엔드포인트 |
|---|---|
| `agent.py` | `POST /api/agent` (V8 등급 검사도 여기) |
| `chat.py` | `POST /api/chat`, `POST /api/chat/stream`(SSE), `GET /api/vessels/detail` |
| `history.py` | `GET`·`DELETE /api/history`, `GET /api/usage` |
| `conversations.py` | `GET /api/conversations`, `GET`·`DELETE /api/conversations/{conv_id}` |
| `document.py` | `POST /api/document`, `POST /api/document/bl` |
| `memory.py` | `GET`·`DELETE /api/memory`, `DELETE /api/memory/items/{item_id}`, `POST /api/memory/document-facts` |
| `profile.py` | `GET`·`PUT /api/profile` |
| `account.py` | `DELETE /api/account` |
| `admin.py` | `GET /api/me`, `/api/admin/*`(고객, 운영자, 작업 이력), `GET /api/metrics` |
| `kakao.py` | `/api/kakao/status`, `connect`, `callback`, `test`, `link` |
| `watch.py` | `GET /api/watch`, `/api/watch/changes`, `/api/watch/vessels`, `PUT /api/cargo/watch` 등 |
| `cargo_sheet.py` | `GET /api/cargo/sheet`, `/api/cargo/sheet.xlsx`, `PUT /api/cargo/sheet/{cargo_key}/lc`·`departed` |

## 서비스 (`app/services/`)

| 위치 | 파일 |
|---|---|
| 맨 위 | `llm`(LLM 호출 단일 지점, SDK import는 여기서만), `llm_config`(주소·상한), `llm_types`(결과·오류), `llm_schemas`(프롬프트 이름·출력 스키마), `llm_support`(입력 조립·정제 순수 함수), `mcp_client`(MCP 도구 호출) |
| `judge/` 판정 흐름 | `customs`(UNI-PASS 조회), `identify`(선박 식별), `bl_parse`, `mrn_fallback`, `signals`(1층 신호 7종), `verdict`(판정 표), `validate`(검증 V1~V7, V9~V15), `evidence`(근거, 여유 일수), `rules`(`rule(key)`로 rules.md 값 읽기), `guard`(프롬프트 주입 걸러내기), `answers`(고정 문구), `builders`(응답 조립), `saved`(지난 응답 값), `vessel_match`(호출부호·국적 대조) |
| `chat/` 채팅·서류 | `chat`(자연어 창구), `texts` `patterns` `limits`(문구·정규식·상수), `models` `ids` `map_card` `memo` `screen` `tools` `replies` `watch_chat`(chat에서 나눈 순수 부분), `citations`, `conversations`, `progress`, `referrals`, `doc_ocr` |
| `account/` 회원·기억·운영 | `memory`, `quota`, `pii_patterns`, `profile`, `account`, `operators`, `customers`, `metrics` |
| `watch/` 화물 현황·지켜보기 | `cargo`, `cargo_sheet`, `watch`, `vessel_watch`, `vessel_pick`, `vessel_detail`, `kakao` |

검증 규칙 V1~V7, V9~V15는 `app/services/judge/validate.py`, V8(등급 검사)은 `app/routers/agent.py`에 있다.

## 실행과 테스트

```bash
docker compose up                              # api :8000 (/api/agent, /health, /docs, /mcp), worker, postgres
pytest backend/tests mcp_server/tests          # 키 없이, fixture로 (.github/workflows/tests.yml이 같은 범위)
```

로컬 실행 설정은 루트 `.env.example`을 따른다. `REPLAY_MODE=true`면 `evals/fixtures/`의 가공 응답으로 키 없이 동작한다.
