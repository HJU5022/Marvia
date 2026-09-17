# Converge

현장이 움직이는 유지보수·배포 작업(함정 정비 미팅, SI 야간 배포)에서 현장 담당자와 업체·고객사가 집결 장소·시각을 정하는 에이전트. KDT AI Human 7기 2차 팀 프로젝트(5조).

이 파일은 요약이다. 기준 문서는 docs/SDD.md, 구조는 CONVERGE.md, 배경은 docs/PRD.md.

## 먼저 읽을 것

언제 여는가. 하나라도 걸리면 연다.

- 어느 폴더를 고칠지 모르겠다 → CONVERGE.md
- 폴더가 정해졌다 → 그 폴더의 `*_GUIDE.md`
- 스키마·필드를 만진다 → docs/SDD.md 2절(요청·응답), 3절(슬롯), 4절(결과)
- 파이프라인 단계·라우팅을 만진다 → SDD 5절
- MCP 도구를 만진다 → SDD 6절
- 규칙값이 필요하다 → skills/converge/rules/ (SDD 7절은 목록만)
- 프롬프트를 만진다 → SDD 8절
- 환경변수가 필요하다 → SDD 9절
- DB 컬럼·암호화 → docs/TABLES.md
- 왜 만드나, 하지 않을 것 → docs/PRD.md 2·3절
- 새 결정을 해야 한다 → 만들지 않는다. 물어보고, 정해지면 SDD를 먼저 고친다

질문에 답만 하고 파일을 고치지 않으면 아무것도 안 열어도 된다.

## 하지 말 것

- LangGraph를 쓰지 않는다. 문서를 청킹해 검색하고 프롬프트에 붙이는 RAG를 만들지 않는다. 지식은 skills/converge/ 문서를 통째로 넣고, 데이터는 MCP 도구로 가져온다
- 상식 수준 규칙(공평성, 막차, 중간 지점)을 만들지 않는다. 규칙은 출입조치·인솔·입항 일정·배포 창·을 관례처럼 현장 절차에서만 나온다
- 부대명·항만 세부·고객사명을 코드나 문서에 예시로 쓰지 않는다. 테스트 데이터도 "진해 기지", "여의도 고객사" 수준까지만
- docs/SDD.md에 없는 결정을 만들지 않는다. 필요하면 물어보고, 정해지면 SDD를 먼저 고친다
- Pydantic 스키마(backend/app/schemas/)를 임의로 바꾸지 않는다. 바꾸면 파인튜닝 데이터와 평가셋이 같이 깨진다
- 규칙값을 코드에 하드코딩하지 않는다. skills/converge/rules/*.md의 프론트매터가 기준이고 backend/app/domain/rules.py가 그걸 읽는다
- 프롬프트를 코드에 문자열로 두지 않는다. Langfuse Prompt에서 이름으로 가져온다 (SDD 8절)
- LLM 호출은 backend/app/services/llm.py, 외부 API 호출은 services/geo.py와 routes.py에만 둔다. 라우터·프론트가 직접 부르지 않는다
- backend/app/domain/에 네트워크 호출이나 LLM 호출을 넣지 않는다. 계산만 둔다
- frontend/lib/api-types.ts를 손으로 고치지 않는다. scripts/gen_types.sh가 만드는 생성물이다
- 참석자 이름·출발지·좌표·경로를 평문으로 DB에 넣지 않는다 (docs/TABLES.md 7절)
- .env, 키, 카톡 캡처 원본을 커밋하지 않는다
- 평가셋(evals/dataset.jsonl)의 입력과 정답을 LLM으로 생성하거나 고치지 않는다. 사람이 쓴다
- 실행하지 않은 결과 숫자를 문서에 적지 않는다
- 파일 안에서 em dash(—)를 쓰지 않는다
- 하나의 작업에서 다른 사람 담당 폴더(SDD 12절)를 고쳐야 하면 먼저 알린다

## 할 것

- 파이프라인은 순차 실행이고 루프가 없다 (SDD 5절). 단계마다 Langfuse span을 남긴다
- 모든 외부 호출은 실패 경로가 있어야 한다 (SDD 5절 표의 "실패 시" 열)
- LLM이 만드는 건 슬롯 JSON과 집결지 순위·이유·전환 판정뿐이다. 소요시간·출발 시각·절차 소요 반영·access_ok는 코드가 계산한다
- 새 기능을 붙이기 전에 docs/PRD.md 3절 "하지 않을 것"을 확인한다
- 파일을 만들거나 고칠 때마다 무엇을 왜 했는지 한두 줄로 보고한다
- 모르는 것은 추측하지 않고 물어본다

## 고쳤으면 같이 볼 것

| 고친 것 | 같이 할 것 |
|---|---|
| backend/app/schemas/ | `bash scripts/gen_types.sh` |
| backend/app/domain/ | `pytest backend/tests` |
| skills/converge/rules/ | `pytest backend/tests` (규칙값을 읽어 쓴다) |
| services/pipeline.py | SDD 5절 표와 맞는지 확인 |

가이드 동기화:

- 폴더 안에 파일을 만들거나 옮기거나 지웠다 → 그 폴더의 `*_GUIDE.md`와 docs/SDD.md 1절, CONVERGE.md 5절
- 폴더의 책임이나 지킬 것이 바뀌었다 → 그 폴더의 `*_GUIDE.md`
- 함수 내용만 고쳤다 → 가이드는 안 건드린다
- 가이드를 고쳤으면 무엇을 왜 고쳤는지 한 줄 보고한다

## 실행

```
cp .env.example .env
docker compose up            # backend :8000 (/api/agent, /health, /mcp)
cd frontend && npm run dev   # :3000
```

## 테스트

- backend: `pytest backend/tests` (키 없이 돌아야 한다)
- 평가셋: `python evals/run_eval.py --dataset evals/dataset.jsonl`
