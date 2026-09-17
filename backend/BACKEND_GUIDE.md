# BACKEND_GUIDE

FastAPI 서버. Cloud Run 서비스 하나에 API와 MCP(/mcp)가 같이 뜬다.

## 이 폴더의 경계

| 폴더 | 무엇 | 인터넷 | API 키 |
|---|---|---|---|
| `app/services/` | 바깥과 통신하는 것 (LLM, 지도, 경로, DB, 비전) | 씀 | 필요 |
| `app/domain/` | 계산만 (규칙 적용, 역산, 라우팅 판단) | 안 씀 | 필요 없음 |

`domain/`에 `httpx`, `openai`가 import되면 잘못된 것이다.
이 경계가 "LLM은 입구와 출구에만, 가운데는 결정적"을 폴더로 증명한다 (docs/PRD.md 3절).

## 파이프라인

`services/pipeline.py`가 0~8단계를 순서대로 부른다. 루프 없음. 단계마다 Langfuse span 하나.
단계 표와 실패 경로는 docs/SDD.md 5절이 기준이다.

## 지킬 것

- 출력은 `app/schemas/`의 모델로 검증한다. 필드는 거기서만 정의한다 (SDD 3·4절)
- LLM 호출은 `services/llm.py`에만. 외부 API 호출은 `services/geo.py`, `routes.py`에만
- 프롬프트를 코드에 문자열로 두지 않는다. Langfuse Prompt 이름으로 가져온다 (SDD 8절)
- 규칙값을 코드에 적지 않는다. `domain/rules.py`가 `skills/converge/rules/`의 프론트매터를 읽는다 (SDD 7절)
- 참석자 이름·출발지·좌표·경로를 평문으로 DB에 넣지 않는다 (docs/테이블정의서.md 7절)
- 로그에 요청 ID, 모델, 토큰, 지연을 남긴다 (테이블정의서.md 3절 request_logs)
- `/health`를 지우지 않는다

## 고쳤으면

| 고친 것 | 할 것 |
|---|---|
| `app/schemas/` | `bash scripts/gen_types.sh` (frontend 타입 재생성) |
| `app/domain/` | `pytest backend/tests` |
| `services/pipeline.py` | SDD 5절 표와 맞는지 확인 |

## 실행

`docker compose up`으로 뜬다. 진입점은 `backend.app.main:app` (Dockerfile CMD).
