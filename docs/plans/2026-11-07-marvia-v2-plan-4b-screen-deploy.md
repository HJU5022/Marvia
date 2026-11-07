# Marvia v2 계획 4b: 배포 전 문 넷, AG-UI 화면, Playwright, Docker 이미지, 배포 준비

> 진행 방법: 태스크를 T0부터 차례로 하고, 단계마다 체크박스(`- [ ]`)로 표시한다. 커밋 하나는 동작 하나다. 서버 쪽 문(R-035, R-066, 트레이스 가림, R-048)을 화면보다 먼저 닫는다.

**Goal:** 실제 데이터와 배포 앞에 남은 문 넷(R-035 체크포인트 평문, R-066 idle in transaction, 트레이스 가림 R-010·R-022·R-039, R-048 사용자 없는 요청)을 닫고, AG-UI 이벤트로 계획 진행·"이렇게 읽었어요"·선택지·승인·답과 근거·화물 카드를 보이는 Next.js 화면을 붙인다. 화면의 주요 흐름은 공식 Playwright 이미지 안에서 시험하고, API는 멀티스테이지 non-root 이미지로 compose에서 돌며, Cloud Run·Vercel·Supabase·AuraDB 배포는 계정 없이 로컬에서 확인할 수 있는 것까지 준비한다 (done 4.1~4.4, 1.4의 남은 것, 3.9의 가림 문).

**Architecture:** 화면 서버(`src/marvia/server.py`, Starlette)는 ag-ui-langgraph 어댑터 없이 `ag-ui-protocol`의 이벤트 타입과 인코더로 엔드포인트 하나(`POST /agui`)를 직접 쓴다. 받는 값은 마지막 사용자 글과 재개 값뿐이고, 보내는 값은 `view.py`의 허용 목록뿐이다. 동기 그래프는 작업 스레드 하나에서 `graph.stream(..., subgraphs=True)`로 끝까지 돌고 이벤트는 큐로 넘어가 SSE가 된다. 사용자는 서명을 확인한 토큰(Supabase ES256, 로컬은 개발 토큰)에서만 꺼내고, 대화는 서버가 "사용자/이름"으로 묶는다.

```
브라우저(Next.js, web/) ──POST /agui (RunAgentInput: threadId, runId, 마지막 사용자 글 | resume[])──▶ server.py
   ◀── SSE: RUN_STARTED → STATE_SNAPSHOT(plan, reading, cargos, evidence)* → TEXT_MESSAGE_* | (카드) → RUN_FINISHED
server.py: auth.user_from_header → thread 잠금(409) → turn_input(새 질문 {"text"} | Command(resume=정리·다시 가린 값))
         → 작업 스레드: graph.stream(updates, subgraphs) → view.screen_view / view.interrupt_card → 큐 → SSE
그래프 공책: text·answer는 UntrackedValue(저장 안 함, R-035) / 읽기 연결은 psycopg_pool autocommit 풀(R-066)
트레이스: trace.scrub(값) → 번호 덩어리를 [가림]으로 (Langfuse mask= 훅 모양, 트레이서는 아직 끔)
compose: db·neo4j / profile app: prepare(표 준비) → api(:8080) · web(:3000) / profile e2e: api-e2e(가짜 모델) · web-e2e · playwright (바깥 막힌 망)
```

**Tech Stack:** Python 3.12, uv, LangGraph 1.2.18, langgraph-checkpoint-postgres 3.2.0, psycopg 3.3.6 + psycopg-pool 3.3.3(이미 잠금 파일에 있음). 새 직접 의존성: `ag-ui-protocol` 1.0.0(09-17, pydantic만 필요) [문서 11-07 PyPI, 휠 소스 읽음], `pyjwt[crypto]` 2.15.1·`starlette` 1.10.0·`uvicorn` 0.54.0(셋 다 mcp 2.3.0을 따라 이미 잠금 파일에 있어 잠금 파일에는 ag-ui-protocol 한 묶음만 더해진다) [실측 11-07]. 화면: Next.js 16.4.3(10-23), React 19.3.1(10-14), TypeScript 5.9.3(create-next-app 16.4.3이 `^5`를 쓴다), `@fontsource-variable/noto-sans-kr` 5.3.1, `@supabase/supabase-js` 2.118.0(10-15), npm 잠금 파일 v3 [문서 11-07 npm 레지스트리]. 시험: `@playwright/test`·`playwright-core` 1.64.1(10-14), `@axe-core/playwright` 4.14.0(10-15, node≥22.12) [문서 11-07 npm]. 이미지(모두 digest 고정, 11-07 레지스트리 조회) [문서 11-07]: `python:3.12-slim-bookworm@sha256:935c3c5b…`, `ghcr.io/astral-sh/uv:0.9.30@sha256:538e0b39…`(CI와 같은 uv), `node:22-bookworm-slim@sha256:5ec23b7c…`(Node 22.23.4), `mcr.microsoft.com/playwright:v1.64.1-noble@sha256:2f05f8a7…`(amd64·arm64, 이미지 안 Node 26), `pgvector/pgvector@sha256:0dd3149a…`(pg16, CI와 같다), `rhysd/actionlint@sha256:b1934ee5…`(1.7.12). 배포 액션: `google-github-actions/auth` v3.0.0(`7c6bc770…`), `setup-gcloud` v3.0.1(`aa5489c8…`) [문서 11-07 GitHub].

**Spec:** `docs/specs/2026-10-28-marvia-v2-design.md` (3 전체 구조, 6.1~6.5, 8 데이터와 기억, 10 화면, 12 신뢰 경계, 13 개발·배포, 14 빼는 순서). 사전 부검 `.superpowers/sdd/plan-4b/premortem.md`(11-07)의 순위표·결정 D1~D5·태스크 순서·확인점·자를 순서·검사 C1~C12를 따른다. 따르지 않은 곳은 "결정과 근거"에 이유를 적었다.

## 계획 나눔

| 계획 | 범위 | 상태 |
|---|---|---|
| 3a, 3c, 3d, 4a, 4a-2, 4a-3 | 답, 도구 루프, 기억·조사·감시, 평가셋·지표·튜닝 | 완료 (11-02, 11-06) |
| 3b | 별표 단위, GraphRAG, UNI-PASS 실제 조회, MCP 서버 | 완료, 유료 측정만 충전 뒤 |
| **4b (이 문서)** | 배포 전 문 넷, 재개 값 다시 가림, 감시 끄기·계정 삭제, AG-UI 화면, Playwright, Docker 이미지, 배포 준비 | 11-07 시작, 11-13 끝, 문서 11-14~15 |
| 5.x | README, 설계 정리, 위키, 직접 할 일 묶음 | 11-14~15 |

## 결정과 근거 (11-07)

| 결정 | 이유 | 틀렸을 때 비용 |
|---|---|---|
| D1. AG-UI 엔드포인트를 `ag-ui-protocol` 1.0.0으로 직접 쓴다. `ag-ui-langgraph` 어댑터는 쓰지 않는다. 받는 값은 `threadId`, `runId`, 마지막 사용자 글, `resume[0]`뿐이다 | 어댑터 0.0.47은 화면이 보낸 메시지를 가리지 않고 `messages` 칸에 넣고, `state`·`forwardedProps`를 그래프 입력에 합치고, 출력 스키마가 없으면 공책 전체(가림 표 포함)를 `STATE_SNAPSHOT`으로 보내고, 비동기 저장기 메서드를 요구한다(사전 부검 1번, 소스 읽음) | 어댑터가 주는 이벤트(도구 호출 흐름, 메시지 스냅숏)가 없다. 설계 14절의 "단순 SSE" 대체 길과 모양이 같아 자를 때 비용이 없다 |
| 서버 틀은 Starlette 1.10.0이다. 설계 3절의 FastAPI는 쓰지 않는다 | Starlette는 mcp를 따라 이미 잠금 파일에 있다. FastAPI 0.162.0은 `opentelemetry-api`·`annotated-doc`·`typing-inspection`을 새로 끌어온다 [문서 11-07 PyPI]. 길은 셋(`/agui`, `/account`, `/health`)뿐이다 | 의존성 주입 같은 FastAPI 편의가 없다. 설계 3절에 날짜와 함께 고쳐 적는다(T11) |
| D2. R-035는 `text`·`answer`를 `Annotated[str, UntrackedValue(str)]`(체크포인트에 저장하지 않는 칸)로 바꿔 닫는다 | 계획을 쓸 때 스파이크를 돌려 사전 등록 6항목을 모두 넘었다 [실측 11-07, 아래 사전 등록]. 바뀌는 곳은 `state.py` 두 줄, 평가 실행기 `drive` 한 곳, 시험 두 곳이다(전체 시험에서 깨진 것 3개) [실측]. scope의 방법(실행 context + 가린 답)은 시험의 `{"text": …}` 154곳을 건드린다 | `get_state()`로 답을 읽던 바깥 코드는 `invoke` 결과에서 읽어야 한다. 저장소 안에서는 `drive`, `compare_loops.py`(이미 그렇게 읽음), 시험 한 곳뿐이다 [실측 grep] |
| R-066은 읽기 연결을 `psycopg_pool.ConnectionPool(kwargs={"autocommit": True})`로 바꾸고 검색·조문 조회가 부를 때마다 빌린다. 감시 연결은 따로 둔다 | 지금의 공유 연결은 검색 한 번 뒤 idle in transaction 1개를 남긴다 [실측 11-07 HEAD]. 풀은 연결마다 autocommit이라 열린 트랜잭션이 없고, 한 요청의 DB 오류가 다른 요청을 실패 상태로 만들지 않고, 끊긴 연결을 바꾼다. 감시 연결을 나눈 R-041 이유와 시험은 그대로다 | 풀 크기(8)는 Supabase 풀러 한도와 맞춰 보지 않았다 [추정] |
| `live_deps`·`agent_deps`의 연결 인자를 풀로 바꾸는 일과 부르는 스크립트 7곳은 한 커밋(10파일)이다. 풀 만들기(`read_pool`)와 300자 자르기는 따로 커밋한다 | 함수 서명이 바뀌어 나눠 커밋하면 사이 커밋에서 스크립트가 깨진다. R-067의 "클라이언트와 부르는 곳을 따로"는 `read_pool`(2a)과 연결(2b)로 지킨다. 바뀌는 줄은 스크립트마다 같은 두 줄 꼴이다 | 리뷰 한 번에 볼 파일이 10개다(15개 선 안) |
| 300자 넘는 검색 질의는 RAG의 `retrieve`에서 `rules/rag.yaml mcp.max_query`까지 자른다(계획 3b 넘어온 일) | 질의 분석 LLM이 쓴 질의가 상한을 넘으면 MCP 서버가 거절해 검색 전체가 실패했다. 두 길(direct, mcp)이 같은 질의를 쓰게 한 곳에서 자른다. MCP 서버의 거절 시험은 그대로 둔다 | 긴 질의의 뒷부분이 검색에 쓰이지 않는다 |
| 트레이스 가림(`trace.scrub`)은 상태 없이 글 모양으로 번호 덩어리를 찾는다(`identify.parse.find_spans`) | 콜백에는 그 대화의 가림 표가 오지 않는다. Send 묶음, 도구 안 서브그래프, pydantic 객체, 오류 객체 어디에든 번호가 들 수 있다. Langfuse `mask=` 훅 모양(값 하나 → 가린 값)이라 연결할 때 그대로 끼운다 | 8자 이상 영문·숫자 덩어리(MRN, 도구 호출 id)도 함께 가린다. 트레이스에서는 덜 가리는 것보다 낫다 |
| R-048: `user_of`는 `configurable.surface == "server"`면 user_id가 없을 때 `MissingUser`를 낸다. `build_app`이 그래프에 `with_config(configurable={"surface": "server"})`를 붙인다. CLI·시험은 "local"을 그대로 쓴다 | 서버가 붙인 표시는 호출 config가 빠뜨려도 남는다(`with_config`가 합친다). 시험·스크립트의 "local" 쓰임(시험 cfg 도우미 여러 곳)을 바꾸지 않는다 | 서버가 아닌 새 진입점을 만들면 그쪽도 표시를 붙여야 한다 |
| 대화 소유는 서버가 thread 키를 `"{사용자}/{threadId}"`로 만들어 지킨다. 사전 부검의 "남의 thread 404" 대신이다 | 표 없이 남의 대화 키를 만들 길 자체가 없다. B가 A의 threadId를 보내면 B 자신의 빈 대화가 된다(C4를 이 기준으로 바꿨다) | 같은 사람이 같은 이름을 두 탭에서 쓰면 한 대화다(잠금이 막는다) |
| 같은 thread가 돌고 있으면 409, 지난 카드에 답하면(interrupt id가 다르면) 409. 멈춘 thread에 새 질문은 받는다 | 새 질문은 깨끗한 차례로 시작한다는 것을 이미 시험한다(`test_new_message_after_an_unanswered_question_starts_a_clean_turn`) [실측]. 409로 막으면 화면이 카드를 잃었을 때 대화가 막힌다 | 답하지 않은 카드는 버려진다(화면은 새 차례에서 카드를 닫는다) |
| 재개 값 다시 가리기: `approval_reply`로 모양을 본 뒤 `remask_reply`가 고친 인자와 거절 글을 이 대화의 가림 표로 다시 가린다. 표에 없던 번호가 나오면 고치기는 거절로, 거절 글은 정해 둔 글로 바꾼다 | 화면은 토큰을 실제 번호로 되돌려 보인다. 승인 미들웨어는 고친 인자로 도구 호출 메시지를 바꾸고 거절 글을 도구 결과로 모델에 준다(done 1.4). 새 토큰을 공책에 넣을 길은 서버에 없다 | 같은 차례에 `ask_user` 직접 입력으로 들어온 번호는 아직 부모 가림 표에 없어 고치기가 거절된다(안전 쪽) |
| 승인 카드의 고치기는 `save_preference`(선택 상자)와 `save_item_card`(이름 칸)만 연다. 나머지는 승인·거절만 | 자유 JSON 편집은 모르는 인자를 도구에 보낸다. 사전 부검 자를 순서 6을 반쯤 미리 적용했다 | 감시 카드는 고칠 수 없다(승인·거절로 충분) |
| 바깥 메시지 발송 도구는 만들지 않는다(자를 순서 1을 지금 적용) | 보낼 통로가 없고 설계 6.3에서 2차다. 생기면 `approval.always_ask`에 넣는다는 규칙 주석이 이미 있다 | done 1.4의 "outbound tool in always_ask"는 이유를 적고 닫는다 |
| 계정 삭제는 `forget_user`(감시) + Store의 `("users", uid, "items"|"prefs")` + 그 사용자의 대화 기록(`checkpoints`·`checkpoint_blobs`·`checkpoint_writes`의 `uid/` 앞머리)을 지운다 | 사전 부검 4번: `forget_user`만으로는 기억과 대화(가림 표 포함)가 남는다. 키 앞머리를 서버가 정하므로 SQL 세 줄이면 된다 | Postgres 저장기에만 맞는 SQL이다(시험은 실제 Postgres) |
| D3. 화물 카드는 단계·항구·단계 시각·출처·조회 시각만 보이고 ETA·등급 칸은 "선박 위치 조회 뒤(2차)"로 적는다 | `CargoFacts`에 ETA가 없고 `verdict.grade`는 시험에서만 불린다 [실측] | 카드가 done 4.1 문구보다 얇다(T11에 이유) |
| D4. 화면 패키지 관리자는 npm이다. 잠금 파일은 Docker(`node:22`)에서 만들고, 설치·빌드·시험도 컨테이너 안에서 한다 | 호스트에는 node·npm만 있다. 호스트 `node_modules`의 SWC 바이너리는 리눅스 컨테이너에서 맞지 않는다 | 호스트에서 `npm run dev`로 고쳐 보려면 `web/node_modules`를 따로 깔아야 한다(허용된 일) |
| D5. CopilotKit과 `@ag-ui/client` 없이 `fetch` 스트림으로 SSE를 읽고 이벤트 타입은 `web/lib/agui.ts`에 적는다 | `@ag-ui/client` 1.0.3은 rxjs·zod·uuid·proto·fast-json-patch를 끌어오고 `@ag-ui/core`도 zod가 필요하다 [문서 11-07 npm]. 화면이 쓰는 이벤트는 일곱 가지다. 서버 쪽 모양은 공식 Python 패키지(pydantic)가 지킨다 | 프로토콜이 바뀌면 타입을 손으로 고친다 |
| 버전은 정확히 고정하고 보안 수정이 아니면 7일 넘은 출시만 쓴다: next 16.4.3(16.4.4·16.4.5는 11-02·11-03), `@playwright/test` 1.64.1(1.65.0은 11-05), supabase-js 2.118.0(2.119.0은 11-04) | 사전 부검 버전 규칙. 새 출시의 문제를 마감 직전에 떠안지 않는다 | 며칠 늦은 버그 수정을 못 받는다 |
| `playwright-core`를 `@playwright/test`와 같은 1.64.1로 직접 고정한다 | `@axe-core/playwright`의 peer(`playwright-core >= 1.0.0`) 때문에 npm이 1.65.0을 따로 깔아 `next build` 타입 검사가 실패했다 [실측 11-07] | 없음 |
| 화면 이미지 바탕은 `node:22-bookworm-slim`이다. Playwright는 공식 이미지(Node 26) 안에서만 돈다 | Next 16.4.3은 node≥20.9, axe는 node≥22.12를 요구하고 axe는 Playwright 이미지 안에서만 돈다 [문서 npm] | 없음 |
| 표 만들기(`migrations/*.sql`, 저장기 `setup()`)는 `python -m marvia.prepare_db`(compose `prepare`, Cloud Run 작업)로 뗀다 | 운영 서버 시작에서 CREATE INDEX CONCURRENTLY가 다른 트랜잭션을 기다리면 시작 탐침이 실패한다(사전 부검 3번). 서버의 `setup()`은 표가 있으면 아무것도 하지 않는다 | 배포 순서가 하나 는다(워크플로가 한다) |
| 가짜 API(`e2e/fake_api.py`)는 Dockerfile의 `e2e` 단계에만 복사하고 운영 단계(`runtime`)가 마지막(기본) 단계다. e2e compose 망은 `internal: true`다 | 가짜 모드가 운영 이미지에 들어갈 길이 없다. 바깥으로 못 나가는 망이라 시험 중 모델·임베딩 호출은 0건일 수밖에 없다 | 가짜 모드를 끄는 환경 변수 검사는 따로 두지 않았다(코드가 없으니 켤 것이 없다) |
| 서버는 로그인 설정(supabase면 주소·소유자 목록, dev면 토큰, Cloud Run에서 dev 거절)과 키 셋(Anthropic, Voyage, DATA)이 없으면 뜨지 않는다 | 배포 확인(dry-run)에서 바로 보이고, 키 없이 떠서 차례마다 실패하지 않는다(fail-closed) | 없음 |
| 배포 워크플로는 `workflow_dispatch`만이고 저장소 변수 `MARVIA_DEPLOY_ENABLED == 'true'`가 아니면 아무것도 안 한다 | push로 돌면 비밀값 없이 실패해 CI가 빨개진다(사전 부검 12번) | 없음 |
| 태스크 순서는 사전 부검 그대로이되, thread 잠금(409)은 T5a(엔드포인트)에 넣고 T5b는 다시 가리기만 한다 | 잠금이 없는 엔드포인트는 두 탭이 같은 체크포인트를 갈라 놓는다. 엔드포인트와 같이 시험해야 한다 | 없음 |
| 화면의 axe 검사와 흐름 시험은 T9(Playwright 이미지)에서 처음 돈다. 사전 부검은 "첫 카드 커밋부터"였다 | Playwright 실행 틀이 T9에 있다. 이 문서의 화면 코드는 계획을 쓸 때 Docker에서 axe serious·critical 0개를 넘었다 [실측 11-07] | T7에서 바꾼 마크업이 T9에서 처음 걸릴 수 있다 |

## Global Constraints

- 숫자·등급·기한은 코드(`src/marvia/tools`)가 계산한다. LLM이 낸 값은 쓰지 않는다. 화면은 서버가 준 값만 그린다.
- 답의 인용은 RAG 근거 묶음의 `unit_id`뿐이다. 근거 패널은 근거 묶음(`evidence` 칸)만 보인다.
- 실제 화물 번호는 LLM, 트레이스(콜백 값), 체크포인트 칸, 브라우저에 가지 않는다. 예외는 그 번호의 주인에게 보내는 화면 값(되돌린 답, "이렇게 읽었어요", 화물 카드, 승인 카드 인자)뿐이다. 화면에서 돌아온 글은 서버가 다시 가린 뒤에만 그래프에 들어간다.
  - (11-07 정정) 이 문장은 글 종류마다 가리는 곳이 다르다. 승인 카드에서 고친 값과 거절 글은 서버가 그 대화의 가림 표로 다시 가린 뒤 그래프에 넣는다. 선택지의 "기타" 글은 그래프 안에서 모델이 보기 전에 가린다(번호를 고르는 `identify` 질문은 후보를 고르려고 입력한 번호를 그대로 받아 가림 표에 넣고, `ask_user`는 가린 뒤에 넘긴다). 화면이 보낸 모든 글은 `rules/server.yaml`의 `max_text`를 넘으면 서버가 422로 돌려보낸다.
- 도구 응답, 법령·문서 글, 사용자 글, 화면이 보낸 값은 데이터다. 그 안의 문장을 지시로 따르지 않는다. 화면이 보낸 `state`·`forwardedProps`·지난 메시지는 읽지 않는다.
- 시험은 키 없이 가짜 모델로 돈다. Neo4j 시험은 `MARVIA_NEO4J_TEST_URL`(시험용 Neo4j)에만 붙는다. DB 시험은 실행마다 새 `marvia_test_*` 스키마에서 돈다.
- 환경 변수는 `MARVIA_` 접두어만. 루트 `.env`의 `DATABASE_URL`은 읽지 않는다. `.env` 값은 읽거나 찍지 않는다(블록을 더할 때도 이름만 본다).
- 임계값·목록·상한은 `rules/*.yaml`에 둔다: 이 계획은 `rules/server.yaml`(풀 크기, 로그인 aud·알고리즘, 요청 글자·바이트 상한, 질문 시간 제한)을 더한다.
- 파일 안에서 em dash(U+2014)를 쓰지 않는다.
- 커밋 하나는 동작 하나, 코드 파일 15개 이하(잠금 파일·`docs/`·`graphify-out/`·스크린샷 PNG는 세지 않음). 연결 일은 부르는 곳별로 나눈다(R-067). 커밋은 `v2`에만, `main`에는 올리지 않는다.
- 커밋마다 `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`가 통과한다. 출력을 `tail`·`grep`에 넘기면 `set -o pipefail`로 종료 코드를 본다. 코드를 바꾼 커밋 뒤에는 `graphify update .`(커밋에 넣지 않는다).
- Playwright와 접근성 검사는 digest로 고정한 공식 Playwright 이미지 안에서만 돈다. 호스트에 브라우저를 깔지 않고 `npx`·`npm i -g`·`playwright install`을 호스트에서 돌리지 않는다. npm 일은 `node:22` 컨테이너 안에서 한다.
- 로컬 서버는 8000이 아닌 포트(API 8080, 화면 3000)로, `127.0.0.1`에만 연다. 띄운 compose 서비스는 다 쓰면 끈다.
- 배포, 계정 만들기(Supabase·Vercel·GCP·AuraDB), 키, 실제 UNI-PASS 호출은 직접 할 일이다. 배포 준비는 계정 없이 로컬에서 실제로 돌린 명령만 "dry-run"이라 적는다.
- 지금은 유료 모델 호출을 할 수 없다(충전 전). 모든 시험과 Playwright 흐름은 가짜 모델로 돈다. 스크린샷은 가짜 모델 화면이라고 적는다.
- 문서 안의 파이썬 조각은 `ruff format`이 고치지 않게 `<!-- fmt: off -->`로 감쌌다.
- 태스크가 부르는 명령 셋 (태스크마다 이 이름으로 부른다):

명령 A (파이썬 검사, 저장소 뿌리에서):

```bash
set -o pipefail
uv run pytest -q 2>&1 | tail -2 && uv run ruff check . && uv run ruff format --check . && uv run pyright | tail -1
```

명령 B (화면 타입 검사·빌드):

```bash
# 타입 검사와 빌드. web/을 읽기 전용으로 붙이고 컨테이너 안 복사본에서 돈다(호스트에 node_modules·.next를 남기지 않는다)
docker run --rm -v "$PWD/web":/src:ro -v marvia-npm-cache:/root/.npm -e NEXT_TELEMETRY_DISABLED=1 \
  node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d \
  sh -c "mkdir /app && tar -C /src --exclude=./node_modules --exclude=./.next -cf - . | tar -C /app -xf - && cd /app \
         && npm ci --no-audit --no-fund >/dev/null && npx tsc --noEmit && npx next build >/dev/null && echo web-ok"
```

명령 C (화면 잠금 파일 다시 만들기):

```bash
# [왜] npm은 컨테이너 안에서만 돌린다(호스트 청결 C12). 캐시는 이름 붙인 볼륨에 둔다
docker run --rm -v "$PWD/web":/app -w /app -v marvia-npm-cache:/root/.npm \
  node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d \
  npm install --package-lock-only --ignore-scripts
```

- 코드 블록 검증: v2 HEAD(`336ff73`)를 내보낸 깨끗한 사본에 이 문서의 코드를 모두 넣고 Docker(`ghcr.io/astral-sh/uv@sha256:e5b65587…`, compose의 Postgres, 시험용 Neo4j)에서 `MARVIA_REQUIRE_DB=1`, `MARVIA_REQUIRE_NEO4J=1`로 돌렸다: 시험 679개 통과(626 → 679, 건너뜀 0), `ruff check`·`ruff format --check`·`pyright` 오류 0, actionlint 오류 0 [실측 11-07]. 중간 단계 중 T2a·T5a·T5b·T8 상태도 그 태스크의 시험 파일로 따로 돌려 통과했다(T2a 1개, T5a 14개, T5b 15개, T8 3개). 화면은 단계마다 `tsc --noEmit`(네 단계 모두 통과), 마지막 상태로 `next build`, compose e2e에서 Playwright 4개 흐름 통과·axe serious·critical 0·스크린샷 3장 [실측 11-07]. 아래 Expected의 수는 626에서 시작해 태스크마다 더한 시험 수다.

---
## 사전 등록: 검사 C1~C12 (구현 전에 고정)

이 절은 첫 구현 커밋 전에 이 문서와 함께 커밋하고, 결과를 본 뒤 기준을 고치지 않는다. 고칠 일이 생기면 이유와 시각을 따로 적고 원래 기준의 판정도 함께 적는다. 사전 부검 C1~C12를 그대로 쓰되 C4·C12는 아래 이유로 문구를 바꿨다.

| # | 검사 | 통과 기준 | 시험·명령 | 지금 HEAD |
|---|---|---|---|---|
| C1 | R-035 DB 스캔 | 끼어들기(승인)와 재개(고친 인자에 `DEMO0002`)가 든 차례 뒤, 같은 키로 다시 연 저장기의 `get_state()`에 `text`·`answer`가 없고, `checkpoint_blobs`·`checkpoint_writes`의 바이트와 `checkpoints` 줄 전체(인라인 값과 metadata)에 `DEMO0001`·`DEMO0002`가 0줄. 허용하는 평문 칸 없음 | `tests/graph/test_postgres_memory.py::test_no_checkpoint_row_holds_a_real_number` | 실패 [실측 11-07: `assert ('text' not in {'text': 'DEMO0001 언제까지 수입신고 해야 해요?', …})`] |
| C2 | R-066 | 실제 Postgres와 실제 검색 길(가짜 임베딩·리랭커)로 검색 뒤, 그리고 MCP `search_regulations` 8개 동시 호출(그중 하나는 일부러 DB 오류) 뒤 이 시험의 연결(`application_name`) 중 idle in transaction 0개, 고장 낸 질의 하나만 실패 | `tests/rag/test_read_pool.py` 두 시험 | 같은 길을 지금의 공유 연결로 돌리면 idle in transaction 1개 [실측 11-07] |
| C3 | 트레이스 가림 | `news`(DEMO0004 감시 변화), Send 두 갈래(DEMO0001·DEMO0002), `lookup_cargo`, `ask_user` 직접 입력(DEMO0003), 조사 서브에이전트, 작성자, 답을 지나는 대화에서 기록 콜백(on_chain_start/end/error, on_tool_start/end, on_chat_model_start, on_llm_end)의 값 전체를 `scrub`한 JSON에 DEMO 번호 0개. 같은 값을 `scrub` 없이 두면 네 번호가 모두 있다 | `tests/graph/test_trace.py` | 가리기 전 값에 `DEMO0001~0004` 넷 모두 있음 [실측 11-07] |
| C4 | 인증 | 헤더 없음·틀린 토큰 401이고 그래프 안 부름(그 thread에 체크포인트 없음); 서명 틀림·만료·다른 iss·다른 aud·exp 없음·쓰레기 401(사유 글 없음); 소유자 목록 밖 403; B가 A의 threadId를 보내면 B 자신의 thread("user-b/…")로 가서 A의 가림 표·번호가 B의 이벤트에 없음; 서버 표시가 붙은 그래프를 user_id 없이 부르면 `MissingUser`; `K_SERVICE`가 있으면 개발 로그인으로 시작 거절; supabase 모드에서 주소·소유자 목록이 없으면 시작 거절 | `tests/test_auth.py`, `tests/graph/test_server.py`, `tests/graph/test_agent.py::test_the_server_graph_refuses_to_run_without_a_user_id` | 서버 표시가 붙은 그래프가 user_id 없이 그대로 돈다 [실측 11-07: `DID NOT RAISE PermissionError`] |
| C5 | 재개 다시 가림 | 승인 고치기 인자(`DEMO0001 고추`)와 거절 글(`DEMO0001은 빼 주세요`)로 재개해도 가짜 모델이 받은 모든 입력에 `DEMO0001` 0개, 다시 가리지 않으면 1개 이상; 도구는 토큰으로 돈다(감시 줄에는 실제 번호); 대화에 없던 번호의 고치기는 정해 둔 거절로 바뀐다 | `tests/graph/test_resume.py`, `tests/graph/test_server.py::test_an_approval_card_shows_real_numbers_but_the_model_gets_tokens_back` | 다시 가리는 함수가 없다 |
| C6 | 이벤트 순서 | 첫 이벤트 `RUN_STARTED`, 끝 이벤트는 `RUN_FINISHED`나 `RUN_ERROR` 하나; 답이면 `TEXT_MESSAGE_START/CONTENT/END` 차례대로 한 짝; 끼어들기 차례는 `RUN_FINISHED.outcome.type == "interrupt"`이고 TEXT 이벤트가 없음; 진행 중 할 일이 든 `STATE_SNAPSHOT`이 `TEXT_MESSAGE_START`보다 먼저; 스냅숏 키는 정확히 `{plan, reading, cargos, evidence}`(`mask_map`·`messages`·`numbers`·`text` 없음) | `tests/graph/test_server.py` | 엔드포인트 없음 |
| C7 | 화면 입력 무시 | `state`·`forwardedProps`에 `llm_calls: 999`, `mask_map: {"[BL1]": "EVIL00001"}`, `actions`를 넣어 보내도 그래프의 `mask_map`은 질문에서 읽은 것뿐이고 `llm_calls < 999`, `actions == []` | `tests/graph/test_server.py::test_state_and_forwarded_props_from_the_browser_are_ignored` | 엔드포인트 없음 |
| C8 | 이미지 | `id -u` = 10001; 이미지 안에서 `load_rules`·`render` 성공; `/app`에 `.env`·`.local`·`scripts`·`tests`·`e2e` 없음(운영 단계); compose `prepare` 끝난 뒤 api HEALTHCHECK healthy 60초 안; `.dockerignore`는 `*`로 시작하는 허용 목록; Dockerfile·compose의 모든 바깥 이미지가 `@sha256:` 고정; 공개 포트는 모두 `127.0.0.1:`; `--platform linux/amd64` 빌드 성공; 이미지 크기 1.2GB 이하 | `tests/test_docker.py` + T8의 Docker 명령 | 이미지 없음 |
| C9 | Playwright | 이미지 `v1.64.1-noble`(digest 고정)과 `@playwright/test`·`playwright-core` 1.64.1 일치(시험과 이미지 빌드 안 검사); 주요 흐름 4개(질문→답·근거·화물, 선택지, 승인 고치기, 승인 거절) 통과, `workers: 1`, `retries: 0`; 각 카드·답 화면에서 axe serious·critical 0; 실시간 계획(가짜 검색 2초 동안 진행 중 할 일이 보이고 답 줄은 0개); 브라우저의 Anthropic·Voyage 요청 0, e2e 망은 internal; 스크린샷 3장 저장(DEMO 번호만) | `web/e2e/flows.spec.ts`, `tests/test_docker.py` | 없음 |
| C10 | 배포 준비 | 워크플로는 `workflow_dispatch`만이고 actionlint 오류 0; `PORT`로 듣는다; 키·로그인 설정이 없으면 시작 거절; `docs/deploy.md`의 "로컬 확인" 줄은 모두 실제로 돌린 명령과 그 결과 | `tests/graph/test_server.py::test_the_server_refuses_to_start_without_model_and_data_keys`, T10 명령 | 없음 |
| C11 | R-067 | 커밋마다 코드 파일 15개 이하(잠금 파일·`docs/`·`graphify-out/`·PNG 제외), 서버 연결 일은 부르는 곳별 커밋(2a 풀, 2b 연결, 2c 자르기, 5a 엔드포인트, 5b 다시 가림, 6a 감시 끄기, 6b 계정 삭제) | `git show --stat` | |
| C12 | 호스트 청결 | 이 계획 동안 호스트에서 `npm`·`npx`·`npm i -g`·`playwright install`을 돌리지 않는다; `~/Library/Caches/ms-playwright`의 목록이 시작 때와 같다(11-07 기준 `.links`, `b`, `chromium_headless_shell-1228`, `chromium-1228`, `ffmpeg-1011`; 이 계획 전부터 있던 것); `NEXT_TELEMETRY_DISABLED=1` | 셸 기록, `ls ~/Library/Caches/ms-playwright` | 사전 부검은 "폴더가 생기지 않음"이었다. 이미 있던 폴더라 "목록이 그대로"로 바꿨다 |

**R-035 스파이크 사전 등록 6항목 (D2)과 결과 [실측 11-07, 계획을 쓸 때 scratch 사본에서]:** 상태 두 칸을 `UntrackedValue`로 바꾼 사본에서 (1) 시험 DB 스캔에서 `DEMO0001~0004` 0줄(허용 집합 공집합) 통과, (2) 식별 서브그래프가 `text`를 읽어 `masked_text`에 `[BL1]` 통과, (3) `invoke` 결과에 `answer`(DEMO0001 포함) 통과, (4) `get_state()`에 `text`·`answer` 없음 통과, (5) `ask_user` 직접 입력(DEMO0003)과 승인 고치기(DEMO0004)로 재개 통과, (6) 번호 둘의 Send 두 갈래 뒤에도 저장 안 됨 통과. 전체 시험에서 깨진 것은 `get_state()`로 답을 읽던 3개뿐이었다(평가 실행기 `drive`의 시험 2개, `test_main.py` 1개). 판정: D2 길로 간다.

**먼저 실패해야 하는 문 시험 넷 (지금 HEAD에서 본 실패) [실측 11-07]:**

| 문 | 시험 | HEAD에서 |
|---|---|---|
| R-035 | C1 | `get_state()`에 평문 `text` 칸이 있어 실패 |
| R-048 | C4의 `MissingUser` 시험 | 같은 내용의 시험이 `DID NOT RAISE PermissionError`로 실패 |
| R-066 | C2 | 같은 길에서 idle in transaction 1개 |
| 트레이스 R-010·R-022·R-039 (트레이서 끔) | C3 | 가리기 전 콜백 값에 번호 넷 모두 있음 (가림 함수가 없어 시험은 import에서 실패) |

## 비용

이 계획에는 유료 모델 호출이 없다($0). 시험과 Playwright 흐름은 가짜 모델로 돌고, 실제 키로 화면을 돌려 보는 일과 배포는 충전·계정 뒤의 직접 할 일이다. Docker 이미지·npm 패키지 받기만 망을 쓴다.

## 시간 상한, 확인점, 자를 순서

남은 날은 11-07~11-13이고 11-14~15는 문서(done 5.x), 11-16이 코드 동결이다. 사전 부검의 어림은 약 56시간이었다. 이 문서의 코드는 미리 검증해 어림을 줄였지만 여유가 크지 않다 [추정].

| 태스크 | 닫는 것 | 사전 부검 어림 | 이 문서 어림 | 날짜 | 끝났다는 증거 |
|---|---|---|---|---|---|
| T0 결정·스파이크 기록 | D1~D5 | 1.5시간 | 0.5시간 (스파이크는 계획 때 끝냄) | 11-07 | 판정 줄 |
| T1 R-035 | done 4.1 R-034·R-035 | 3시간 | 2시간 | 11-07 | C1 |
| T2 R-066 (2a 풀, 2b 연결, 2c 300자) | R-066, 3b carry | 4시간 | 3시간 | 11-07~08 | C2, 300자 시험 |
| T3 트레이스 가림 | R-010·R-022·R-039 | 3시간 | 2시간 | 11-08 | C3 |
| T4 인증 (4a 로그인, 4b R-048) | R-048 | 5시간 | 4시간 | 11-08~09 | C4 |
| **CP1 (11-09 끝)** | T0~T4 끝났나. 아니면 자를 순서 2·3을 바로 자른다 | | | | |
| T5a 서버 엔드포인트·허용 목록 보기·잠금 | 4.1 서버 | 5시간 | 4시간 | 11-09~10 | C6, C7, C4 서버 부분 |
| T5b 재개 다시 가림 | done 1.4 남은 것 | 4시간 | 2.5시간 | 11-10 | C5 |
| T6 감시 끄기·계정 삭제 | R-033 | 2.5시간 | 2.5시간 | 11-10 | 시험 |
| T7a 화면 뼈대·채팅·스트림 | 4.1 | 4시간 | 3시간 | 11-10~11 | tsc, next build |
| T7b 계획·읽었어요·근거 | 4.1 | 4시간 | 2.5시간 | 11-11 | tsc |
| **CP2 (11-11 끝)** | T5~T7b 끝났나. 아니면 자를 순서 4·5·6을 자른다 | | | | |
| T7c 선택지·승인 카드 | 4.1 | 4시간 | 3시간 | 11-11~12 | tsc |
| T7d 화물 카드 | 4.1 (D3) | 2시간 | 1.5시간 | 11-12 | tsc |
| T7e Supabase 로그인 화면 | 4.1 로그인 | (자를 순서 3) | 1시간 | 11-12 | tsc, next build |
| T8 Docker 이미지·compose app | 4.3 | 5시간 | 4시간 | 11-12 | C8 |
| T9 Playwright in Docker | 4.2 | 5시간 | 4시간 | 11-12~13 | C9 |
| **CP3 (11-12 끝)** | T8~T9 끝났나. 아니면 자를 순서 7을 자르고 스크린샷은 답 화면과 승인 카드만 | | | | |
| T10 배포 준비 | 4.4 | 4시간 | 3시간 | 11-13 | C10 |
| T11 문서 | 설계 날짜 줄, done 증거 줄 | (5.x 일정) | 2시간 | 11-14 | |
| 합 | | 약 56시간 | 약 44.5시간 | | |

자르는 순서 (먼저 자르는 것부터, 사전 부검 4절):
1. 바깥 메시지 발송 도구: 만들지 않고 이유 기록 (지금 적용, 결정과 근거)
2. CI 배포 워크플로 → 손 배포 절차서만 (설계 14절 "자동 배포(손 배포)")
3. Supabase 로그인 화면(T7e) → 개발 로그인만. 서버의 Supabase JWT 확인과 시험(T4a)은 남긴다
4. 화물 카드 ETA·등급 → "2차" 표시 (D3, 처음부터 적용)
5. AG-UI 이벤트 풍부함 → `RUN_*`·`STATE_SNAPSHOT`·`TEXT_MESSAGE_*`만 (이 문서의 엔드포인트가 이미 이 모양이다. `STEP_*`·`STATE_DELTA`는 처음부터 없다)
6. 승인 카드 고치기 → 설명 깊이 한 도구만, 나머지는 승인·거절
7. web 컨테이너 → Playwright 이미지 안에서 `next build && next start`
8. MCP HTTP 공개 → 배포에서 내부 통로만 (처음부터 적용, `docs/deploy.md`)

자르지 않는 것: 문 넷(R-035, R-048, R-066, 트레이스 가림), 재개 값 다시 가림, 인증 거절과 thread 소유 검사, non-root 이미지와 `.dockerignore`, Playwright 주요 흐름과 스크린샷, 주요 화면의 axe 검사.

## 파일 구조

| 파일 | 책임 | 태스크 |
|---|---|---|
| `src/marvia/graph/state.py`, `src/marvia/eval/run.py`, `src/marvia/graph/live.py`(주석) | `text`·`answer` 저장 안 함, `drive`가 답을 invoke 결과에서 | T1 |
| `src/marvia/db.py`, `rules/server.yaml` (새) | `read_pool`(autocommit 풀), 화면 서버 설정값 | T2a, T4a, T5a |
| `src/marvia/rag/live.py`, `src/marvia/graph/live.py`, `scripts/{try_agent,compare_loops,run_eval,retrieval_check,serve_mcp,extract_items,try_rag}.py` | 검색·조문 조회가 풀에서 빌림 | T2b |
| `src/marvia/graph/rag.py` | 검색 질의 300자 자르기 | T2c |
| `src/marvia/trace.py` (새) | 콜백 값 가림 `scrub` | T3 |
| `src/marvia/auth.py` (새), `src/marvia/config.py`, `.env.example`, `.env` | 토큰 확인, 시작 검사, 로그인 설정 | T4a |
| `src/marvia/graph/tools.py` | `user_of`의 서버 길 거절(`MissingUser`), `unwatch_cargo` | T4b, T6a |
| `src/marvia/view.py` (새), `src/marvia/server.py` (새) | 허용 목록 화면 보기·카드, AG-UI 엔드포인트, 잠금, 계정 삭제 | T5a, T5b, T6b |
| `src/marvia/graph/resume.py` | `remask_reply` | T5b |
| `src/marvia/watch.py`, `rules/agent.yaml` | `remove_watch`, `WatchDeps.remove`, `unwatch_cargo` 늘 묻기 | T6a |
| `web/` (새): `package.json`, `package-lock.json`, `.npmrc`, `.gitignore`, `tsconfig.json`, `next.config.ts`, `app/{layout,page}.tsx`, `app/globals.css`, `lib/{agui,auth}.ts`, `components/*.tsx` | 화면 | T7a~T7e |
| `src/marvia/prepare_db.py` (새), `Dockerfile` (새), `.dockerignore` (새), `web/Dockerfile`, `web/.dockerignore`, `docker-compose.yml` | 표 준비 명령, API·화면 이미지, compose app | T8 |
| `e2e/fake_api.py` (새), `web/e2e.Dockerfile`, `web/playwright.config.ts`, `web/e2e/flows.spec.ts`, `web/e2e/screenshots/*.png` | 가짜 API, Playwright 실행 이미지·흐름·스크린샷, compose e2e | T9 |
| `.github/workflows/deploy.yml` (새), `docs/deploy.md` (새) | 손으로 시작하는 배포, 절차서와 로컬 확인 기록 | T10 |
| `tests/graph/test_postgres_memory.py`, `test_main.py`, `test_rag.py`, `test_trace.py`(새), `test_resume.py`, `test_server.py`(새), `test_agent.py`, `tests/rag/test_read_pool.py`(새), `tests/test_auth.py`(새), `tests/test_watch.py`, `tests/test_docker.py`(새) | 시험 | 모두 |

---
### Task 0: 결정과 스파이크 기록 (사전 부검 T0)

**배울 것:** LangGraph의 `UntrackedValue`는 "마지막 값을 들고 있지만 체크포인트에는 넣지 않는" 채널이다(`langgraph/channels/untracked_value.py`의 `checkpoint()`가 늘 MISSING). 루프는 쓰기 기록(`checkpoint_writes`)에서도 그 칸을 빼고, Send 묶음 안의 같은 이름 값도 지운다(`pregel/_loop.py` 496~510행, `_algo.py sanitize_untracked_values_in_send`) [문서 11-07 설치된 소스]. StateGraph는 `Annotated[str, UntrackedValue(str)]`처럼 주석 안의 채널 객체를 그대로 칸으로 쓴다. 그래서 "원문은 이 차례 안에서만 살고 저장되지 않는다"를 칸 선언 한 줄로 말할 수 있다.

스파이크(계획을 쓸 때 scratch 사본, 커밋 안 함)는 사전 등록 6항목을 모두 넘었다(위 "사전 등록"). 이 태스크는 판정 줄만 남긴다.

- [ ] **Step 1: 장부에 판정 줄을 남긴다(커밋 없음)**

```text
Ruling (D2): R-035 closes with UntrackedValue on IdentifyState.text and MarviaState.answer | plan-time spike 11-07: 6/6 pre-registered criteria passed, full suite broke only the 3 tests that read answer from get_state | outside callers must read answer from the invoke result
Ruling: server framework Starlette (already locked via mcp) instead of FastAPI 0.162.0 (adds opentelemetry-api) | 3 routes | design 3 gets a dated note
Ruling: thread ownership by server-made key "{user}/{threadId}" instead of a 404 table; C4 condition reworded | no table, other users' keys cannot be formed | none
Ruling: no outbound-message tool (cut order 1 applied now) | no channel, design 6.3 second phase | done 1.4 closes with this reason
```

---
### Task 1: R-035, 원문과 답을 저장하지 않는 칸으로 (done 4.1 R-034·R-035)

**배울 것:** `PostgresSaver.put`은 str·int 같은 단순 값 칸을 직렬화기(암호화)를 거치지 않고 `checkpoints.checkpoint` JSONB에 그대로 둔다. 그래서 계획 3d에서 암호화를 켜도 `text`(원문)와 `answer`(번호를 되돌린 답)는 평문으로 남았다. 칸을 `UntrackedValue`로 두면 이 차례의 노드들은 값을 읽고 쓰지만 체크포인트와 쓰기 기록에는 오지 않는다. 대신 `get_state()`에도 없으므로 답은 `invoke`(또는 stream의 갱신)에서 읽는다. 시험은 끼어들기와 재개(고친 인자에 실제 번호)를 지나게 해서 쓰기 기록과 재개 값까지 본다.

**Files:**
- Modify: `src/marvia/graph/state.py`, `src/marvia/eval/run.py`, `src/marvia/graph/live.py`(주석)
- Test: `tests/graph/test_postgres_memory.py`, `tests/graph/test_main.py`

**Interfaces:**
- Produces: `IdentifyState.text`, `MarviaState.answer`는 저장되지 않는다. `graph.get_state(config).values`에 두 칸이 없다. 답은 `graph.invoke(...)["answer"]`로 읽는다.
- Produces: `marvia.eval.run.drive(...)`가 돌려주는 값에는 마지막 invoke의 `answer`가 합쳐져 있다(부르는 쪽은 그대로).

- [ ] **Step 1: 실패하는 시험**: `tests/graph/test_postgres_memory.py`의 `test_checkpoints_keep_real_numbers_only_in_the_plain_text_and_answer_channels`를 아래 시험으로 바꾼다(허용 집합 `{text, answer}` → 공집합, 끼어들기·재개를 더함). `test_main.py`는 답을 invoke 결과에서 읽게 고친다.

```diff
--- a/tests/graph/test_postgres_memory.py
+++ b/tests/graph/test_postgres_memory.py
@@ -58,35 +58,40 @@
     assert "품목 카드 건고추" in [m.content for m in messages if m.type == "tool"][-1]
 
 
-def test_checkpoints_keep_real_numbers_only_in_the_plain_text_and_answer_channels(agent_deps, test_url):
+def test_no_checkpoint_row_holds_a_real_number(agent_deps, test_url):
+    # [왜] R-035: str 칸(text 원문, answer 답)은 PostgresSaver가 직렬화기 없이 JSONB로 둔다.
+    #      저장하지 않는 칸으로 바꿨으니 질문·끼어들기·재개(고친 인자에 실제 번호)를 지난 뒤에도
+    #      0줄이어야 한다
     key = Fernet.generate_key().decode()
     config = {"configurable": {"thread_id": "pg-encrypted", "user_id": "u1"}}
+    calls = model(
+        ("calc_deadlines", {}), ("check_reimport", {"facts": CHILI}), ("save_item_card", {"name": "고추"})
+    )
+    edit = {"type": "edit", "edited_action": {"name": "save_item_card", "args": {"name": "DEMO0002 고추"}}}
     with live_memory(test_url, key) as (saver, store):
-        deps = agent_deps(model=model(("calc_deadlines", {})))
-        graph = build_main_graph(deps, saver, loop="agent", store=store)
-        graph.invoke({"text": "DEMO0001 언제까지 수입신고 해야 해요?"}, config)
+        graph = build_main_graph(agent_deps(model=calls), saver, loop="agent", store=store)
+        assert "__interrupt__" in graph.invoke({"text": "DEMO0001 언제까지 수입신고 해야 해요?"}, config)
+        out = graph.invoke(Command(resume={"decisions": [edit]}), config)
+        assert "DEMO0001" in out["answer"]  # 화면에 보낼 답은 invoke 결과에만 있다
     # 새 연결, 같은 키: 암호화한 기록을 풀어 읽는다
     with live_memory(test_url, key) as (saver, store):
         graph = build_main_graph(agent_deps(model=model()), saver, loop="agent", store=store)
-        assert graph.get_state(config).values["mask_map"] == {"[BL1]": "DEMO0001"}
+        values = graph.get_state(config).values
+        assert values["mask_map"] == {"[BL1]": "DEMO0001"}
+        assert "text" not in values and "answer" not in values  # 저장하지 않는 칸
     with psycopg.connect(test_url) as conn:
-        # 직렬화기를 거치는 칸(가림 표, 화물, 메시지, Send 묶음, 재개 값)은 모두 암호문이다
-        blobs = "SELECT channel FROM checkpoint_blobs WHERE position('DEMO0001'::bytea IN blob) > 0"
-        writes = "SELECT channel FROM checkpoint_writes WHERE position('DEMO0001'::bytea IN blob) > 0"
-        assert conn.execute(blobs).fetchall() == []
-        assert conn.execute(writes).fetchall() == []
-        others = (
-            "SELECT checkpoint_id FROM checkpoints WHERE metadata::text LIKE '%DEMO0001%' "
-            "OR (checkpoint - 'channel_values')::text LIKE '%DEMO0001%'"
-        )
-        assert conn.execute(others).fetchall() == []
-        # [주의] str 칸은 PostgresSaver가 직렬화기 없이 JSONB로 둔다.
-        #        남은 평문은 text·answer뿐이다 (done.md 4.1)
-        plain = (
-            "SELECT DISTINCT c.key FROM checkpoints, jsonb_each(checkpoint -> 'channel_values') AS c "
-            "WHERE c.value::text LIKE '%DEMO0001%'"
-        )
-        assert {row[0] for row in conn.execute(plain).fetchall()} <= {"text", "answer"}
+        for number in ("DEMO0001", "DEMO0002"):
+            blobs = "SELECT channel FROM checkpoint_blobs WHERE position(%s::bytea IN blob) > 0"
+            writes = "SELECT channel FROM checkpoint_writes WHERE position(%s::bytea IN blob) > 0"
+            assert conn.execute(blobs, (number.encode(),)).fetchall() == [], number
+            assert conn.execute(writes, (number.encode(),)).fetchall() == [], number
+            # [왜] 인라인 값(channel_values)과 metadata까지 checkpoints 줄 전체를 본다.
+            #      허용하는 평문 칸은 없다
+            rows = (
+                "SELECT checkpoint_id FROM checkpoints "
+                "WHERE checkpoint::text LIKE %s OR metadata::text LIKE %s"
+            )
+            assert conn.execute(rows, (f"%{number}%", f"%{number}%")).fetchall() == [], number
 
 
 # 엄격 직렬화 모드에서 그래프를 컴파일하고, 그 그래프가 쓰는 직렬화기에 평문·암호문 값을 읽혀 본다
```

```diff
--- a/tests/graph/test_main.py
+++ b/tests/graph/test_main.py
@@ -373,10 +373,11 @@
 def test_same_number_keeps_its_token_on_the_next_turn(agent_deps):
     graph = build_main_graph(agent_deps(), InMemorySaver())
     graph.invoke({"text": "DEMO0001 언제까지 신고해요?"}, cfg("t42"))
-    graph.invoke({"text": "DEMO0002도 있고 DEMO0001도 다시 봐 줘"}, cfg("t42"))
+    out = graph.invoke({"text": "DEMO0002도 있고 DEMO0001도 다시 봐 줘"}, cfg("t42"))
     values = graph.get_state(cfg("t42")).values
     assert values["masked_text"] == "[BL2]도 있고 [BL1]도 다시 봐 줘"  # 앞 차례의 [BL1]을 그대로 쓴다
-    assert "DEMO0001" in values["answer"] and "DEMO0002" in values["answer"]
+    # [왜] 답은 저장하지 않는 칸이라 get_state가 아니라 invoke 결과에서 읽는다 (R-035)
+    assert "DEMO0001" in out["answer"] and "DEMO0002" in out["answer"]
 
 
 def test_numbers_are_looked_up_in_parallel_within_the_rule_limit(agent_deps, slow_lookup):
```

```bash
uv run pytest -q tests/graph/test_postgres_memory.py::test_no_checkpoint_row_holds_a_real_number
```

Expected: FAIL `AssertionError: assert ('text' not in {'text': 'DEMO0001 언제까지 수입신고 해야 해요?', ...})` [실측 11-07]. (`test_main.py`의 고친 시험은 지금도 통과한다.)

- [ ] **Step 2: 코드**: 두 칸을 저장하지 않는 칸으로, 평가 실행기는 답을 invoke 결과에서 읽게, 저장기 주석을 지금 상태로.

```diff
--- a/src/marvia/graph/state.py
+++ b/src/marvia/graph/state.py
@@ -13,6 +13,7 @@
 
 from langchain.agents import AgentState
 from langchain_core.messages import AnyMessage
+from langgraph.channels import UntrackedValue
 from langgraph.graph.message import add_messages
 from langgraph.managed import RemainingSteps
 
@@ -22,7 +23,10 @@
 # [왜] TypedDict는 "이 dict에는 이런 칸이 있다"를 적어 두는 문법이다. 실행 중 검사는 하지 않고 pyright가 본다
 # [왜] total=False: 모든 칸이 처음부터 있을 필요는 없다. 노드가 하나씩 채워 간다
 class IdentifyState(TypedDict, total=False):
-    text: str  # 사용자가 준 단서 글 원문. [주의] LLM에 넘기지 않는다
+    # 사용자가 준 단서 글 원문. [주의] LLM에 넘기지 않는다
+    # [왜] UntrackedValue: 이 차례 안에서만 살고 체크포인트에 저장하지 않는다. 원문에는 실제 번호가 있고,
+    #      PostgresSaver는 str 칸을 직렬화기(암호화) 없이 JSONB로 둔다 (R-035)
+    text: Annotated[str, UntrackedValue(str)]
     masked_text: str  # 번호를 가린 글. LLM에 넘겨도 되는 글
     mask_map: dict[str, str]  # [BL1] → 실제 번호
     numbers: list[str]  # 조회할 번호 (확정한 것만)
@@ -45,7 +49,8 @@
     failed_tools: list[dict]  # 실패한 도구 호출 {"tool", "message"}
     # [왜] LangGraph가 단계마다 채우는 값(recursion_limit까지 남은 단계 수). 읽기만 하고 start도 비우지 않는다
     remaining_steps: RemainingSteps
-    answer: str  # 화면에 보낼 답 (번호를 되돌린 글)
+    # 화면에 보낼 답 (번호를 되돌린 글). [왜] text와 같은 까닭으로 저장하지 않는다. invoke 결과에서만 읽는다
+    answer: Annotated[str, UntrackedValue(str)]
     # 아래는 에이전트 루프 칸 (계획 3c). 계획자 길에서는 쓰지 않는다
     # [왜] add_messages: 메시지 목록을 덮어쓰지 않고 id로 합친다.
     #      루프가 돌려준 전체 목록을 다시 받아도 겹치지 않는다
```

```diff
--- a/src/marvia/eval/run.py
+++ b/src/marvia/eval/run.py
@@ -135,7 +135,10 @@
         else:
             reply = {"timeout": True}
         out = graph.invoke(Command(resume=reply), config)
-    return graph.get_state({"configurable": {"thread_id": thread}}).values, pauses
+    values = graph.get_state({"configurable": {"thread_id": thread}}).values
+    # [왜] 답(answer)은 체크포인트에 저장하지 않는 칸이라 get_state에 없다 (R-035).
+    #      마지막 invoke 결과에서 읽는다
+    return values | {"answer": out.get("answer", "")}, pauses
 
 
 def behaviour(values: dict, pauses: list[dict], *, not_found: bool = True) -> str:
```

```diff
--- a/src/marvia/graph/live.py
+++ b/src/marvia/graph/live.py
@@ -129,8 +129,9 @@
     # [왜] 직렬화기를 거치는 칸(가림 표, 화물, 메시지, Send 묶음, 재개 값, 도구 안 서브그래프 상태)이
     #      모두 암호문이 된다. 장기 기억(품목 카드, 설명 깊이)은 검사에서 번호를 받지 않아 암호화하지 않는다
     # [주의] PostgresSaver.put은 str·int 같은 단순 값 칸을 직렬화기 없이 checkpoints 표 JSONB에 그대로 둔다.
-    #        그래서 text(사용자 원문)와 answer(번호를 되돌린 답)는 평문으로 남는다.
-    #        서버 쪽에서 막는 일은 done.md 4.1
+    #        실제 번호가 든 str 칸(text 원문, answer 답)은 저장하지 않는 칸(UntrackedValue)이라
+    #        표에 오지 않는다
+    #        (graph/state.py, R-035)
     serde = checkpoint_serde(secret)
     with (
         # [왜] from_conn_string은 serde를 받지 않는다. 그 함수와 같은 설정으로 연결을 열고
```

- [ ] **Step 3: 확인**: 명령 A.

Expected: `626 passed`, 나머지 오류 0. (시험 이름이 하나 바뀌고 수는 같다.)

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/graph/state.py src/marvia/eval/run.py src/marvia/graph/live.py tests/graph/test_postgres_memory.py tests/graph/test_main.py
git commit -m "fix(graph): 원문과 답을 체크포인트에 저장하지 않는 칸으로 둠 (R-035)"
```

---
### Task 2: R-066, 읽기 연결 풀과 300자 질의 (R-066, 계획 3b carry)

**배울 것:** psycopg는 autocommit이 꺼진 연결에서 SELECT 하나도 트랜잭션을 연다. commit·rollback 없이 두면 그 연결은 `pg_stat_activity`에서 "idle in transaction"으로 남아 스냅숏과 잠금을 잡는다(VACUUM과 CREATE INDEX CONCURRENTLY가 기다린다). `psycopg_pool.ConnectionPool(kwargs={"autocommit": True})`는 연결마다 autocommit이고, `with pool.connection() as conn:`은 빌린 연결을 블록 끝에 돌려주며 상태가 IDLE이 아니면 되돌리거나 바꾼다(`psycopg_pool/pool.py` `connection()`·`_reset_connection`) [문서 11-07 설치된 소스]. `open=False`로 만들고 `with read_pool(url) as pool:`로 열고 닫는다(암묵적 열기는 DeprecationWarning). 시험은 이 시험만의 `application_name`을 붙여 다른 작업의 연결과 섞이지 않게 센다.

#### 커밋 2a: feat(db): 읽기 연결을 autocommit 풀에서 빌림

**Files:**
- Modify: `src/marvia/db.py`
- Create: `rules/server.yaml`, `tests/rag/test_read_pool.py`

**Interfaces:**
- Produces: `marvia.db.read_pool(url: str) -> psycopg_pool.ConnectionPool` (열지 않은 풀. `with`로 연다)

- [ ] **Step 1: HEAD에서 문제를 먼저 본다(커밋 없음)**: 아래 시험의 `read_pool` 자리에 지금처럼 `psycopg.connect(url)` 연결 하나를 쓰면 검색 한 번 뒤 idle in transaction이 1개다 [실측 11-07, scratch 사본 `test_head_idle.py`].

- [ ] **Step 2: 실패하는 시험**: `tests/rag/test_read_pool.py` (새 파일)

<!-- fmt: off -->
```python
"""읽기 연결 풀 시험 (R-066, 계획 4b Task 2). 실제 Postgres와 실제 검색 길에 가짜 임베딩·리랭커를 넣는다.

로컬 DB가 꺼져 있으면 건너뛴다(MARVIA_REQUIRE_DB=1이면 실패).
"""

from datetime import date
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from marvia.config import Settings
from marvia.db import read_pool
from marvia.rag.index import index_units
from marvia.rag.search import hybrid_search

AS_OF = date(2026, 10, 30)


def idle_in_transaction(url: str, name: str) -> int:
    """이름(application_name)이 name인 연결 가운데 idle in transaction인 수."""
    # [왜] 같은 DB에 다른 시험·작업의 연결이 있을 수 있다. 이 시험의 풀 연결만 이름으로 센다
    with psycopg.connect(url, autocommit=True) as conn:
        sql = (
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE application_name = %s AND state = 'idle in transaction'"
        )
        return conn.execute(sql, (name,)).fetchone()[0]


@pytest.fixture
def pooled(db, make_unit, fake_embed):
    """시험용 스키마에 단위 둘을 색인하고, 이 시험만의 이름을 붙인 접속 문자열과 이름을 준다."""
    units = [make_unit("제1조", "수입신고는 입항 후에 한다"), make_unit("제2조", "정밀검사를 면제할 수 있다")]
    index_units(db, units, fake_embed)
    schema = db.execute("SELECT current_schema()").fetchone()[0]
    db.commit()

    name = f"marvia-read-{uuid4().hex[:8]}"
    # [왜] pgvector 타입은 public에 있다. 시험용 스키마 다음에 public을 둔다 (tests/conftest.py의 db와 같다)
    options = f"-c search_path={schema},public"
    return make_conninfo(Settings().database_url, options=options, application_name=name), name


def test_a_search_leaves_no_connection_idle_in_transaction(pooled, fake_embed):
    url, name = pooled
    with read_pool(url) as pool:
        with pool.connection() as conn:
            hits = hybrid_search(conn, "정밀검사 면제", fake_embed, AS_OF)
        assert hits[0].unit_id == "LTEST@20261002#제2조"
        assert idle_in_transaction(url, name) == 0  # [왜] 지금(HEAD)의 공유 연결은 1이었다 (11-07 실측)
```
<!-- fmt: on -->

```bash
uv run pytest -q tests/rag/test_read_pool.py
```

Expected: FAIL `ImportError: cannot import name 'read_pool' from 'marvia.db'`

- [ ] **Step 3: 코드**: `rules/server.yaml` (새 파일)

```yaml
# 화면 서버와 그 DB 연결의 설정값 (설계 10절·13절, 계획 4b). src/marvia/db.py·auth.py·server.py·view.py가 읽는다.

pool:
  # 검색·조문 조회가 빌려 쓰는 읽기 연결 풀 (R-066). 한 차례의 병렬 검색과 동시 요청을 함께 받는다
  min_size: 1
  max_size: 8 # [왜] 한 단계의 병렬 search_law(agent.yaml loop.max_concurrency)보다 크게 둔다
  timeout_s: 10 # 빌릴 연결이 없을 때 기다리는 초. 넘으면 psycopg_pool.PoolTimeout(검색 실패로 남는다)
```

`src/marvia/db.py`:

```diff
--- a/src/marvia/db.py
+++ b/src/marvia/db.py
@@ -2,6 +2,7 @@
 
 하지 않는 일: 적용 기록 표. 1차는 migrations/*.sql을 이름 순서로 모두 돌리고,
 파일마다 IF NOT EXISTS로 써서 여러 번 돌려도 같게 한다.
+읽기 연결 풀(read_pool)은 마이그레이션을 돌리지 않는다. 표가 있는 DB에 붙는다 (계획 4b, R-066).
 """
 
 from __future__ import annotations
@@ -9,6 +10,9 @@
 from pathlib import Path
 
 import psycopg
+from psycopg_pool import ConnectionPool
+
+from marvia.tools.rules import load_rules
 
 MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
 
@@ -27,3 +31,25 @@
     conn = psycopg.connect(url)
     apply_migrations(conn)
     return conn
+
+
+def read_pool(url: str) -> ConnectionPool:
+    """검색·조문 조회가 부를 때마다 빌려 쓰는 읽기 연결 풀. with 블록으로 열고 닫는다.
+
+    [왜] 연결 하나를 RAG 검색·조문 조회·MCP 서버·병렬 search_law가 함께 쓰면, SELECT 뒤 트랜잭션이
+         "idle in transaction"으로 남아 VACUUM과 CREATE INDEX CONCURRENTLY를 막고(11-06 실측: 시험이 멈춤),
+         한 요청의 오류가 함께 쓰는 연결을 실패 상태로 만들어 다른 요청까지 죽인다 (R-066).
+    [왜] autocommit: 문장마다 바로 끝나 읽은 뒤 열린 트랜잭션이 없다. 검색은 읽기만 해서 묶을 트랜잭션이 없다.
+    [주의] 쓰기(색인·감시 표)는 이 풀을 쓰지 않는다. connect()나 따로 연 연결을 쓴다.
+    """
+    cfg = load_rules("server")["pool"]
+    # [왜] open=False: 만들기만 하고 with 블록에 들어갈 때 연다.
+    #      라이브러리가 암묵적 열기를 곧 없앤다고 경고한다(psycopg_pool pool.py)
+    return ConnectionPool(
+        url,
+        kwargs={"autocommit": True},
+        min_size=cfg["min_size"],
+        max_size=cfg["max_size"],
+        timeout=cfg["timeout_s"],
+        open=False,
+    )
```

- [ ] **Step 4: 확인**: 명령 A. Expected: `627 passed`, 오류 0.

- [ ] **Step 5: 커밋**

```bash
git add src/marvia/db.py rules/server.yaml tests/rag/test_read_pool.py
git commit -m "feat(db): 읽기 연결을 autocommit 풀에서 빌림 (R-066)"
```

#### 커밋 2b: feat(rag): 검색·조문 조회와 부르는 스크립트가 풀을 씀

**Files:**
- Modify: `src/marvia/rag/live.py`, `src/marvia/graph/live.py`, `scripts/try_agent.py`, `scripts/compare_loops.py`, `scripts/run_eval.py`, `scripts/retrieval_check.py`, `scripts/serve_mcp.py`, `scripts/extract_items.py`, `scripts/try_rag.py`
- Test: `tests/rag/test_read_pool.py`

**Interfaces:**
- Consumes: `read_pool` (2a)
- Produces: `marvia.rag.live.live_deps(settings, pool: ConnectionPool) -> RagDeps`, `marvia.graph.live.agent_deps(settings, pool: ConnectionPool, watch_conn) -> AgentDeps` (감시 연결은 그대로 따로)

- [ ] **Step 1: 실패하는 시험**: `tests/rag/test_read_pool.py`에 동시 MCP 시험을 더한다.

```diff
--- a/tests/rag/test_read_pool.py
+++ b/tests/rag/test_read_pool.py
@@ -3,6 +3,7 @@
 로컬 DB가 꺼져 있으면 건너뛴다(MARVIA_REQUIRE_DB=1이면 실패).
 """
 
+from concurrent.futures import ThreadPoolExecutor
 from datetime import date
 from uuid import uuid4
 
@@ -12,10 +13,14 @@
 
 from marvia.config import Settings
 from marvia.db import read_pool
+from marvia.rag import voyage
 from marvia.rag.index import index_units
+from marvia.rag.live import live_deps
+from marvia.rag.models import SearchFailed
 from marvia.rag.search import hybrid_search
 
 AS_OF = date(2026, 10, 30)
+BROKEN = "고장 난 질의"  # 이 질의만 임베딩 차원이 틀려 DB 오류를 낸다
 
 
 def idle_in_transaction(url: str, name: str) -> int:
@@ -43,6 +48,9 @@
     return make_conninfo(Settings().database_url, options=options, application_name=name), name
 
 
+SETTINGS = Settings(_env_file=None, anthropic_api_key="sk-test-not-real", voyage_api_key="test", graph="off")
+
+
 def test_a_search_leaves_no_connection_idle_in_transaction(pooled, fake_embed):
     url, name = pooled
     with read_pool(url) as pool:
@@ -50,3 +58,34 @@
             hits = hybrid_search(conn, "정밀검사 면제", fake_embed, AS_OF)
         assert hits[0].unit_id == "LTEST@20261002#제2조"
         assert idle_in_transaction(url, name) == 0  # [왜] 지금(HEAD)의 공유 연결은 1이었다 (11-07 실측)
+
+
+def test_concurrent_mcp_searches_do_not_break_each_other(pooled, fake_embed, monkeypatch):
+    url, name = pooled
+
+    def embed(texts, settings, input_type):
+        # [왜] 차원이 3인 벡터는 vector(1024) 칸과 맞지 않아 DB 오류가 난다.
+        #      동시 요청 하나만 일부러 실패시킨다
+        return [[0.0] * 3 for _ in texts] if BROKEN in texts[0] else fake_embed(texts)
+
+    monkeypatch.setattr(voyage, "embed", embed)
+    monkeypatch.setattr(
+        voyage, "rerank", lambda query, texts, settings: [1.0 / (i + 1) for i in range(len(texts))]
+    )
+    queries = ["정밀검사 면제"] * 7 + [BROKEN]
+    with read_pool(url) as pool:
+        rag = live_deps(SETTINGS, pool)  # 기본 rag_via=mcp: 같은 MCP 서버를 메모리 통로로 부른다
+        assert rag.ranked is not None
+
+        def one(query: str):
+            try:
+                return rag.ranked(query, AS_OF)
+            except SearchFailed as error:
+                return error
+
+        with ThreadPoolExecutor(max_workers=8) as workers:
+            results = list(workers.map(one, queries))
+        assert idle_in_transaction(url, name) == 0
+    # [왜] 한 요청의 DB 오류가 같은 연결을 쓰는 다른 요청을 실패 상태로 만들지 않는다. 고장 난 질의만 실패한다
+    assert [isinstance(r, SearchFailed) for r in results] == [False] * 7 + [True]
+    assert all(r[0].unit_id == "LTEST@20261002#제2조" for r in results[:7])
```

```bash
uv run pytest -q tests/rag/test_read_pool.py
```

Expected: FAIL `assert [True, True, ...] == [False, False, ...]` (지금의 `live_deps`는 풀을 연결처럼 써서 여덟 검색이 모두 `SearchFailed`가 된다) [실측 11-07]

- [ ] **Step 2: 코드**: `src/marvia/rag/live.py`

```diff
--- a/src/marvia/rag/live.py
+++ b/src/marvia/rag/live.py
@@ -7,7 +7,7 @@
 
 from datetime import date
 
-import psycopg
+from psycopg_pool import ConnectionPool
 
 from marvia.config import Settings
 from marvia.graph.rag import RagDeps, top_ranked
@@ -20,8 +20,8 @@
 from marvia.rag.search import hybrid_search
 
 
-def live_deps(settings: Settings, conn: psycopg.Connection) -> RagDeps:
-    """설정의 모델과 로컬 DB로 RagDeps를 만든다."""
+def live_deps(settings: Settings, pool: ConnectionPool) -> RagDeps:
+    """설정의 모델과 로컬 DB로 RagDeps를 만든다. 검색은 부를 때마다 pool에서 연결을 빌린다 (R-066)."""
     llm = chat_model(settings)
     # [왜] 그래프를 끄면 계획 3b 전과 같은 검색이다
     expand = graph_expand(settings) if settings.graph == "on" else None
@@ -30,7 +30,9 @@
         return voyage.embed(texts, settings, "query")
 
     def search(query: str, as_of: date) -> list[Evidence]:
-        return hybrid_search(conn, query, embed, as_of, expand)
+        # [왜] 병렬 검색·동시 요청이 각자 연결을 쓴다. 블록을 나가면 연결이 풀로 돌아간다
+        with pool.connection() as conn:
+            return hybrid_search(conn, query, embed, as_of, expand)
 
     def rerank(query: str, texts: list[str]) -> list[float]:
         return voyage.rerank(query, texts, settings)
```

`src/marvia/graph/live.py` (T1 주석 다음 상태에서):

```diff
--- a/src/marvia/graph/live.py
+++ b/src/marvia/graph/live.py
@@ -12,6 +12,7 @@
 import os
 from collections.abc import Collection, Iterator
 from contextlib import contextmanager
+from datetime import date
 from typing import Any
 
 import httpx
@@ -22,12 +23,14 @@
 from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
 from langgraph.store.postgres import PostgresStore
 from psycopg.rows import DictRow, dict_row
+from psycopg_pool import ConnectionPool
 
 from marvia.config import Settings
 from marvia.graph.main import AgentDeps
 from marvia.graph.schemas import Draft, Plan
 from marvia.llm import chat_model, structured
 from marvia.rag.live import live_deps
+from marvia.rag.models import Evidence
 from marvia.rag.provision import find_provision
 from marvia.tools.reimport import ItemFacts
 from marvia.tools.rules import load_rules
@@ -39,10 +42,11 @@
 NONCE_BYTES = 12  # AES-GCM이 권하는 nonce 길이
 
 
-def agent_deps(settings: Settings, conn: psycopg.Connection, watch_conn: psycopg.Connection) -> AgentDeps:
+def agent_deps(settings: Settings, pool: ConnectionPool, watch_conn: psycopg.Connection) -> AgentDeps:
     """설정의 모델과 로컬 DB로 AgentDeps를 만든다. 만들기만 하고 부르지는 않는다.
 
-    conn: RAG 검색·조문 조회가 함께 쓰는 연결. watch_conn: 감시 목록만 쓰는 autocommit 연결.
+    pool: RAG 검색·조문 조회가 부를 때마다 빌리는 읽기 연결 풀(db.read_pool). watch_conn: 감시 목록만 쓰는
+    autocommit 연결.
     """
     llm = chat_model(settings)
     # [왜] 키가 없으면 실제 번호를 저장하지 않는다(fail-closed).
@@ -55,16 +59,22 @@
     except ValueError:
         watch = None
     return AgentDeps(
-        rag=live_deps(settings, conn),  # 계획 2의 RAG 바깥 기능을 그대로 쓴다
+        rag=live_deps(settings, pool),  # 계획 2의 RAG 바깥 기능을 그대로 쓴다
         plan=structured(llm, Plan),
         item=structured(llm, ItemFacts),
         write=structured(llm, Draft),
-        provision=lambda label, as_of: find_provision(conn, label, as_of),
+        provision=lambda label, as_of: _provision(pool, label, as_of),
         model=llm,  # [왜] 에이전트 길은 같은 모델에 도구를 묶어 부른다(create_agent가 bind_tools를 한다)
         # [왜] follow_redirects=False: 넘겨 주는 주소를 따라가면 허용 목록 밖으로 갈 수 있다 (official_lookup)
         web=httpx.Client(timeout=load_rules("agent")["official"]["timeout_s"], follow_redirects=False),
         watch=watch,  # 감시 표는 같은 로컬 DB에 있다(migrations/002_watch.sql)
     )
+
+
+def _provision(pool: ConnectionPool, label: str, as_of: date) -> list[Evidence]:
+    """조문 직접 조회. 부를 때마다 풀에서 연결을 빌린다 (R-066)."""
+    with pool.connection() as conn:
+        return find_provision(conn, label, as_of)
 
 
 class AesGcm:
```

스크립트 일곱 곳은 같은 꼴이다: 표 만들기가 필요한 곳은 `connect(url)`을 그대로 두고 읽기는 `read_pool(url)`로, 자기 SQL을 읽은 곳은 바로 `commit()`으로 트랜잭션을 닫는다. `tests/graph/test_live.py`는 연결 자리에 `None`과 기록용 가짜를 넣어 만들기만 하므로 바꾸지 않는다. `tests/eval/test_unipass_forced.py`가 막는 `marvia.db.connect`는 `run_eval.py`·`compare_loops.py`가 여전히 먼저 부른다.

```diff
--- a/scripts/try_agent.py
+++ b/scripts/try_agent.py
@@ -20,7 +20,7 @@
 from langgraph.types import Command
 
 from marvia.config import Settings
-from marvia.db import connect
+from marvia.db import connect, read_pool
 from marvia.graph.live import agent_deps, live_memory
 from marvia.graph.main import build_main_graph
 from marvia.graph.resume import approval_reply
@@ -51,14 +51,15 @@
 config = {"configurable": {"thread_id": args.thread, "user_id": args.user}}
 # [왜] get_usage_metadata_callback: 이 블록 안의 LLM 호출(RAG 서브그래프 안 포함)의 토큰 수를 모델별로 더한다
 with (
-    connect(settings.database_url) as conn,
+    connect(settings.database_url),  # [왜] 표가 없으면 만든다(마이그레이션). 읽기는 아래 풀로 한다
+    read_pool(settings.database_url) as pool,
     # [왜] 감시 목록은 따로 autocommit 연결을 쓴다. 다른 도구가 conn을 되돌려도 감시 줄이 남는다 (R-041)
     psycopg.connect(settings.database_url, autocommit=True) as watch_conn,
     live_memory(settings.database_url, settings.data_key.get_secret_value()) as (saver, store),
     get_usage_metadata_callback() as usage,
 ):
     graph = build_main_graph(
-        agent_deps(settings, conn, watch_conn),
+        agent_deps(settings, pool, watch_conn),
         saver,
         loop=settings.loop,
         store=store,
```

```diff
--- a/scripts/compare_loops.py
+++ b/scripts/compare_loops.py
@@ -20,7 +20,7 @@
 from langgraph.types import Command
 
 from marvia.config import Settings
-from marvia.db import connect
+from marvia.db import connect, read_pool
 from marvia.graph.live import agent_deps
 from marvia.graph.main import build_main_graph
 from marvia.graph.resume import approval_reply
@@ -84,13 +84,14 @@
 prices = load_rules("pricing")
 rows = []
 with (
-    connect(settings.database_url) as conn,
+    connect(settings.database_url),  # [왜] 표가 없으면 만든다(마이그레이션). 읽기는 아래 풀로 한다
+    read_pool(settings.database_url) as pool,
     # [왜] 감시 목록은 따로 autocommit 연결을 쓴다. 다른 도구가 conn을 되돌려도 감시 줄이 남는다 (R-041)
     psycopg.connect(settings.database_url, autocommit=True) as watch_conn,
 ):
     for loop in ("planner", "agent"):
         graph = build_main_graph(
-            agent_deps(settings, conn, watch_conn), InMemorySaver(), loop=loop, store=InMemoryStore()
+            agent_deps(settings, pool, watch_conn), InMemorySaver(), loop=loop, store=InMemoryStore()
         )
         for i, text in enumerate(QUESTIONS):
             started = time.monotonic()
```

```diff
--- a/scripts/run_eval.py
+++ b/scripts/run_eval.py
@@ -349,7 +349,7 @@
 import psycopg  # noqa: E402
 
 from marvia.config import Settings  # noqa: E402
-from marvia.db import connect  # noqa: E402
+from marvia.db import connect, read_pool  # noqa: E402
 from marvia.eval.dataset import CORPUS_UNITS  # noqa: E402
 from marvia.graph.live import agent_deps  # noqa: E402
 from marvia.rag.edges import build_edges  # noqa: E402
@@ -379,11 +379,13 @@
     settings = Settings(chat_model=model)
     with (
         connect(settings.database_url) as conn,
+        read_pool(settings.database_url) as pool,  # [왜] 검색·조문 조회는 풀에서 빌린다 (R-066)
         # [왜] agent_deps는 감시 목록용 연결을 따로 받는다 (R-041). 평가 실행은 감시를 끄므로 쓰지 않는다
         psycopg.connect(settings.database_url, autocommit=True) as watch_conn,
     ):
-        deps = agent_deps(settings, conn, watch_conn)
+        deps = agent_deps(settings, pool, watch_conn)
         annex_units = conn.execute(ANNEX_SQL).fetchone()[0]
+        conn.commit()  # [왜] 읽은 뒤 트랜잭션을 닫는다. 긴 실행 내내 열려 있지 않게 (R-066)
         docs = sorted({p.name.split(".")[0] for p in CORPUS_UNITS.glob("*.jsonl")})
         graph = {}
         # [왜] 그래프가 지금 코드로 만든 간선 수와 같은지 대조한다. 켠 설정에서만 센다
```

```diff
--- a/scripts/retrieval_check.py
+++ b/scripts/retrieval_check.py
@@ -37,7 +37,7 @@
 
 # [왜] 키·DB가 필요한 모듈은 인자 검사 뒤에 읽는다
 from marvia.config import Settings  # noqa: E402
-from marvia.db import connect  # noqa: E402
+from marvia.db import connect, read_pool  # noqa: E402
 from marvia.graph.rag import top_ranked  # noqa: E402
 from marvia.rag.live import live_deps  # noqa: E402
 
@@ -45,12 +45,13 @@
 items = {i.id: i for i in data.items if i.gold}
 k = load_rules("eval")["retrieval_k"]
 settings = Settings()
-with connect(settings.database_url) as conn:
-    rag = live_deps(settings, conn)
+with connect(settings.database_url) as conn, read_pool(settings.database_url) as pool:
+    rag = live_deps(settings, pool)
     find = rag.ranked or partial(top_ranked, rag.search, rag.rerank)
     annex = conn.execute(
         "SELECT count(*) FROM corpus_units WHERE split_part(unit_id, '#', 2) LIKE '별표%'"
     ).fetchone()
+    conn.commit()  # [왜] 읽은 뒤 트랜잭션을 닫는다 (R-066)
     rows = []
     for item in items.values():
         found = find(mask_text(item.question)[0], data.as_of)
```

```diff
--- a/scripts/serve_mcp.py
+++ b/scripts/serve_mcp.py
@@ -11,7 +11,7 @@
 import uvicorn
 
 from marvia.config import Settings
-from marvia.db import connect
+from marvia.db import read_pool
 from marvia.graph.rag import top_ranked
 from marvia.rag.live import live_deps
 from marvia.rag.mcp import build_server, http_app
@@ -22,8 +22,9 @@
 args = parser.parse_args()
 
 settings = Settings()
-with connect(settings.database_url) as conn:
-    rag = live_deps(settings, conn)
+# [왜] 오래 도는 서버는 요청마다 풀에서 연결을 빌린다. 연결 하나를 겹치는 요청이 함께 쓰지 않는다 (R-066)
+with read_pool(settings.database_url) as pool:
+    rag = live_deps(settings, pool)
     server = build_server(partial(top_ranked, rag.search, rag.rerank))
     uvicorn.run(
         http_app(server, settings.mcp_token.get_secret_value(), args.host), host=args.host, port=args.port
```

```diff
--- a/scripts/extract_items.py
+++ b/scripts/extract_items.py
@@ -17,7 +17,7 @@
 from pydantic import BaseModel
 
 from marvia.config import Settings
-from marvia.db import connect
+from marvia.db import read_pool
 from marvia.eval.run import cost_usd, inside_repo
 from marvia.graph.rag import evidence_block, top_ranked
 from marvia.llm import chat_model, structured
@@ -46,8 +46,8 @@
 settings = Settings()
 prices = load_rules("pricing")
 items = []
-with connect(settings.database_url) as conn, get_usage_metadata_callback() as usage:
-    rag = live_deps(settings, conn)
+with read_pool(settings.database_url) as pool, get_usage_metadata_callback() as usage:
+    rag = live_deps(settings, pool)
     find = partial(top_ranked, rag.search, rag.rerank)
     extract = structured(chat_model(settings), Extracted)
     for name, aliases in ITEMS.items():
```

```diff
--- a/scripts/try_rag.py
+++ b/scripts/try_rag.py
@@ -7,13 +7,13 @@
 from datetime import date
 
 from marvia.config import Settings
-from marvia.db import connect
+from marvia.db import read_pool
 from marvia.graph.rag import build_rag_graph
 from marvia.rag.live import live_deps
 
 settings = Settings()
-with connect(settings.database_url) as conn:
-    out = build_rag_graph(live_deps(settings, conn)).invoke({"question": sys.argv[1], "as_of": date.today()})
+with read_pool(settings.database_url) as pool:
+    out = build_rag_graph(live_deps(settings, pool)).invoke({"question": sys.argv[1], "as_of": date.today()})
 
 print(
     "질문 유형:",
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `628 passed`, 오류 0.

- [ ] **Step 4: 커밋** (10파일, 결정과 근거의 R-067 줄)

```bash
git add src/marvia/rag/live.py src/marvia/graph/live.py scripts/try_agent.py scripts/compare_loops.py scripts/run_eval.py scripts/retrieval_check.py scripts/serve_mcp.py scripts/extract_items.py scripts/try_rag.py tests/rag/test_read_pool.py
git commit -m "feat(rag): 검색·조문 조회와 부르는 스크립트가 읽기 연결 풀을 씀 (R-066)"
```

#### 커밋 2c: fix(rag): 검색 질의를 MCP 상한까지 자름

**Files:**
- Modify: `src/marvia/graph/rag.py`
- Test: `tests/graph/test_rag.py`

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_rag.py
+++ b/tests/graph/test_rag.py
@@ -103,3 +103,21 @@
     out = build_rag_graph(deps).invoke(START_STATE)
     assert [e["unit_id"] for e in out["evidence"]] == ["LTEST@20261002#제9조"]
     assert "search" not in seen
+
+
+def test_a_long_query_still_goes_through_the_mcp_server():
+    # [왜] 질의 분석 LLM이 쓴 질의가 MCP 서버의 글자 수 상한(rules/rag.yaml mcp.max_query)을 넘으면
+    #      서버가 거절해 검색 전체가 실패했다. 서버로 보내기 전에 상한까지 자른다 (계획 3b에서 넘어온 일)
+    from marvia.rag.mcp import MAX_QUERY, build_server, mcp_ranked
+
+    seen: list[str] = []
+
+    def ranked(query: str, when: date) -> list[Evidence]:
+        seen.append(query)
+        return [_evidence("제2조", "정밀검사를 면제할 수 있다")]
+
+    long = QueryAnalysis(question_type="문구 해석", as_of=None, search_query="정밀검사 면제 " * 60)
+    deps = replace(_deps([ENOUGH]), analyze=lambda prompt: long, ranked=mcp_ranked(build_server(ranked)))
+    out = build_rag_graph(deps).invoke(START_STATE)
+    assert [e["unit_id"] for e in out["evidence"]] == ["LTEST@20261002#제2조"]
+    assert len(seen[0]) == MAX_QUERY
```

```bash
uv run pytest -q tests/graph/test_rag.py::test_a_long_query_still_goes_through_the_mcp_server
```

Expected: FAIL `marvia.rag.models.SearchFailed: mcp_tool_error` [실측 11-07]

- [ ] **Step 2: 코드**

```diff
--- a/src/marvia/graph/rag.py
+++ b/src/marvia/graph/rag.py
@@ -77,7 +77,9 @@
     def retrieve(state: RagState) -> dict:
         """하이브리드 검색으로 후보를 찾고, 리랭커로 다시 줄 세워 상위 n개를 근거로 남긴다."""
         # [왜] 노드가 채우는 칸은 .get으로 읽는다. 처음 넣는 칸(question, as_of)만 []로 바로 읽는다
-        query = state.get("search_query", "")
+        # [왜] 규정 검색 MCP 서버는 상한(mcp.max_query)을 넘는 질의를 거절한다. 질의는 LLM이 쓴 글이라 길이를
+        #      믿지 않는다. 두 길(direct, mcp)이 같은 질의를 쓰게 여기서 자른다
+        query = state.get("search_query", "")[: cfg["mcp"]["max_query"]]
         if deps.ranked is not None:
             found = deps.ranked(query, state["as_of"])
         else:
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `629 passed`, 오류 0.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/graph/rag.py tests/graph/test_rag.py
git commit -m "fix(rag): 검색 질의를 MCP 질의 상한까지 잘라 두 길이 같은 질의를 씀"
```

---
### Task 3: 트레이스 가림 문, 트레이서 끈 채로 (R-010·R-022·R-039, done 3.9 문)

**배울 것:** LangChain 콜백(`BaseCallbackHandler`)은 그래프의 모든 노드 입력·출력(`on_chain_start/end`), 도구 입력·출력(`on_tool_start/end`), 모델 입력(`on_chat_model_start`)을 받는다. 트레이서(Langfuse)는 이 값을 그대로 밖으로 보낸다. 실제 번호는 조회 서브그래프 입력, Send 묶음, `lookup_cargo` 결과, `news` 출력, 끼어들기(`on_chain_error`의 GraphInterrupt), 답에 있다. 가림 함수는 값의 모양을 모르고도 걸어 다녀야 한다: dict·list·pydantic(메시지 포함)·dataclass·Send를 따라가고, 모르는 객체는 글로 바꿔 가린다. 시험은 "가리기 전 값에는 번호가 있다"를 함께 보여 가림을 빼면 실패함을 증명한다.

**Files:**
- Create: `src/marvia/trace.py`, `tests/graph/test_trace.py`

**Interfaces:**
- Produces: `marvia.trace.scrub(value: Any) -> Any` (JSON으로 바꿀 수 있는 새 값), `scrub_text(text: str) -> str`, `MASK = "[가림]"`. Langfuse를 붙일 때 클라이언트의 `mask=scrub`로 쓴다(이 계획에서는 붙이지 않는다).

- [ ] **Step 1: 실패하는 시험**: `tests/graph/test_trace.py` (새 파일)

<!-- fmt: off -->
```python
"""트레이스 가림 문 시험 (R-010·R-022·R-039, done 3.9). 트레이서 없이 기록 콜백으로 본다. 키 없이 돈다."""

import json

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command, Send

from marvia.graph.main import build_main_graph
from marvia.graph.schemas import Draft
from marvia.trace import MASK, scrub
from marvia.watch import WatchDeps

NUMBERS = ("DEMO0001", "DEMO0002", "DEMO0003", "DEMO0004")
TWO = [{"label": "부산", "description": "부산항 기준"}, {"label": "인천", "description": "인천항 기준"}]


class ToolModel(GenericFakeChatModel):
    """정해 둔 AIMessage를 차례로 내는 가짜 모델 (tests/graph/test_agent.py와 같다)."""

    def bind_tools(self, tools, **kwargs):
        return self


def say(name: str, args: dict, n: int) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"t{n}-{name}"}])


class Record(BaseCallbackHandler):
    """콜백이 받는 값을 모두 모은다. 트레이서(Langfuse)가 받는 값과 같은 자리다."""

    def __init__(self):
        self.payloads: list = []

    def on_chain_start(self, serialized, inputs, **kwargs):
        self.payloads.append(inputs)

    def on_chain_end(self, outputs, **kwargs):
        self.payloads.append(outputs)

    def on_chain_error(self, error, **kwargs):
        self.payloads.append(error)  # [왜] 끼어들기(GraphInterrupt)는 오류 길로 질문 값을 싣고 온다

    def on_tool_start(self, serialized, input_str, *, inputs=None, **kwargs):
        self.payloads.append([input_str, inputs])

    def on_tool_end(self, output, **kwargs):
        self.payloads.append(output)

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.payloads.append(messages)

    def on_llm_end(self, response, **kwargs):
        self.payloads.append(response)


def test_every_callback_payload_is_free_of_numbers_after_scrub(agent_deps):
    # 한 대화가 지나는 길: 번호 둘(Send 두 갈래) → news(감시 변화 DEMO0004) → lookup_cargo
    # → ask_user(직접 입력 DEMO0003) → research(조사 서브에이전트 안의 search_law) → 작성자
    # → 답(DEMO0001을 되돌린 글)
    script = [
        say("lookup_cargo", {"tokens": ["[BL1]"]}, 1),
        say("ask_user", {"question": "어느 화물부터 볼까요?", "options": TWO}, 2),
        say("research", {"question": "수입신고 기한의 근거"}, 3),
        say("search_law", {"query": "수입신고 기한"}, 4),  # 조사 서브에이전트 안
        AIMessage("관세법 제241조가 30일을 정해요."),  # 조사 요약
        AIMessage(""),  # 부모 루프 끝
    ]
    news = [{"id": 1, "number": "DEMO0004", "old_stage": "", "new_stage": "반입신고"}]
    watch = WatchDeps(add=lambda *row: None, news=lambda user: news, ack=lambda user, ids: None)
    citing = Draft(
        answer="[BL1]은 반입일부터 30일 안에 신고해요.", citations=[], next_options=[], forwarder_message=""
    )
    deps = agent_deps(model=ToolModel(messages=iter(script)), watch=watch, write=lambda prompt: citing)
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
    record = Record()
    config = {"configurable": {"thread_id": "trace"}, "callbacks": [record]}
    out = graph.invoke({"text": "DEMO0001 DEMO0002 언제까지 신고해요?"}, config)
    assert "__interrupt__" in out
    out = graph.invoke(Command(resume={"custom": "DEMO0003부터 봐 주세요"}), config)
    assert "DEMO0001" in out["answer"]
    raw = json.dumps(record.payloads, ensure_ascii=False, default=str)
    # [왜] 가림을 빼면 실패하는 시험인지 먼저 본다: 길마다 넣은 번호가 가리기 전 값에는 모두 있다
    assert all(number in raw for number in NUMBERS)
    scrubbed = json.dumps(scrub(record.payloads), ensure_ascii=False)
    assert [number for number in NUMBERS if number in scrubbed] == []
    assert MASK in scrubbed


def test_scrub_walks_send_packets_models_and_unknown_objects():
    packet = Send("one", {"idx": 0, "number": "DEMO0001", "mask_map": {"[BL1]": "DEMO0001"}})
    message = AIMessage("", tool_calls=[{"name": "watch_cargo", "args": {"token": "DEMO0002"}, "id": "c1"}])
    cleaned = json.dumps(scrub([packet, message, ValueError("DEMO0003 조회 실패")]), ensure_ascii=False)
    assert "DEMO" not in cleaned and cleaned.count(MASK) == 4
    # 날짜·짧은 글·unit_id는 그대로 둔다 (L001556은 7자, 20261002는 날짜라 번호 후보가 아니다)
    assert scrub({"unit_id": "L001556@20261002#제241조.3항", "n": 3}) == {
        "unit_id": "L001556@20261002#제241조.3항",
        "n": 3,
    }
```
<!-- fmt: on -->

```bash
uv run pytest -q tests/graph/test_trace.py
```

Expected: FAIL `ModuleNotFoundError: No module named 'marvia.trace'`. (`scrub` 없이 같은 대화를 돌리면 가리기 전 값에 `DEMO0001~0004`가 모두 있다 [실측 11-07].)

- [ ] **Step 2: 코드**: `src/marvia/trace.py` (새 파일)

<!-- fmt: off -->
```python
"""트레이스(콜백·Langfuse)로 나가는 값에서 화물 번호를 가린다 (설계 12절, done 3.9 문: R-010·R-022·R-039).

하지 않는 일: 트레이서 연결. Langfuse 키가 없어 연결은 미뤘다. scrub은 Langfuse 클라이언트의 mask= 훅 모양
(값 하나를 받아 가린 값을 돌려준다)이라 연결할 때 그대로 끼운다.
[왜] 상태 없이 글 모양으로 찾는다. 콜백에는 그 대화의 가림 표가 오지 않고, 번호는 노드 입력·출력,
     도구 결과, Send 묶음, 도구 안에서 부른 서브그래프, 답 어디에든 들 수 있다.
[주의] 번호처럼 생긴 다른 글(8자 이상 영문·숫자 덩어리)도 함께 가린다. 트레이스에서는 덜 가리는 것보다 낫다.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from langgraph.types import Send
from pydantic import BaseModel

from marvia.identify.parse import find_spans

MASK = "[가림]"


def scrub_text(text: str) -> str:
    """글 속 번호 후보 덩어리(identify.parse.find_spans와 같은 규칙)를 모두 MASK로 바꾼다."""
    pieces: list[str] = []
    last = 0
    for span in find_spans(text):
        pieces += [text[last : span.start], MASK]
        last = span.end
    return "".join(pieces) + text[last:]


def scrub(value: Any) -> Any:
    """값 안의 모든 글에서 번호를 가린 새 값. dict·list·tuple·set·pydantic·dataclass·Send를 걸어 다닌다."""
    if isinstance(value, str):
        return scrub_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {scrub(key): scrub(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [scrub(item) for item in value]
    if isinstance(value, Send):
        # [왜] Send 묶음(조회 갈래 하나)의 arg에 실제 번호와 가림 표가 통째로 든다 (R-039)
        return {"send": value.node, "arg": scrub(value.arg)}
    if isinstance(value, BaseModel):
        # [왜] 메시지·화물 결과(CargoIdentity)·Evidence는 pydantic이다. 칸을 하나씩 걸어 다닌다
        return scrub(dict(value))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        # [주의] dataclasses.asdict는 값을 깊이 복사해 잠금 같은 객체에서 죽는다. 칸을 직접 읽는다
        return {field.name: scrub(getattr(value, field.name)) for field in dataclasses.fields(value)}
    # [주의] 모르는 객체(날짜, 예외, 도구 실행 정보 등)는 글로 바꿔 가린다. 원래 객체를 그대로 내보내지 않는다
    return scrub_text(str(value))
```
<!-- fmt: on -->

- [ ] **Step 3: 확인**: 명령 A. Expected: `631 passed`, 오류 0.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/trace.py tests/graph/test_trace.py
git commit -m "feat(trace): 콜백 값의 화물 번호를 가리는 scrub과 기록 콜백 시험 (R-010, R-022, R-039)"
```

---
### Task 4: 로그인 확인과 R-048 (done 4.1 R-048, 설계 10절 로그인·12절)

**배울 것:** Supabase Auth는 로그인한 사용자에게 ES256으로 서명한 JWT를 준다. 서버는 공개키 목록(JWKS, `<프로젝트>/auth/v1/.well-known/jwks.json`)으로 서명을 확인하고 `aud`(authenticated), `iss`(`<프로젝트>/auth/v1`), `exp`를 본다. 우리 쪽에 JWT 비밀값이 없다. PyJWT의 `jwt.decode(token, key, algorithms=[...], audience=..., issuer=..., options={"require": [...]})`와 `jwt.PyJWKClient(url).get_signing_key_from_jwt(token).key`를 쓴다 [문서 11-07 설치된 PyJWT 2.15.1 `api_jwt.py`·`jwks_client.py`]. 알고리즘 목록을 ES256 하나로 닫아야 헤더의 alg를 바꾼 위조 토큰이 통하지 않는다. 시험은 이 시험 안에서 만든 키쌍으로 서명하고 공개키 함수를 바꿔 끼워 네트워크 없이 돈다(v1 `backend/app/auth.py`와 같은 방식).

R-048은 그래프 쪽 문이다. 서버 앱이 그래프에 `with_config(configurable={"surface": "server"})`를 붙이고, `user_of`는 그 표시가 있는데 user_id가 없으면 멈춘다. `with_config`의 값은 호출할 때 넘긴 config와 합쳐지므로(`Pregel.with_config` → `merge_configs`) 호출 쪽이 빠뜨려도 남는다 [문서 11-07 설치된 langgraph `pregel/main.py`].

#### 커밋 4a: feat(auth): 토큰 확인, 소유자 목록, 시작 검사

**Files:**
- Create: `src/marvia/auth.py`, `tests/test_auth.py`
- Modify: `src/marvia/config.py`, `rules/server.yaml`, `.env.example`, `.env`, `pyproject.toml`, `uv.lock`

**Interfaces:**
- Produces: `marvia.auth.Verify = Callable[[str], str]`, `AuthError(status: int, message: str)`, `check_startup(settings) -> None`, `supabase_verifier(settings, signing_key=None) -> Verify`, `dev_verifier(settings) -> Verify`, `verifier(settings) -> Verify`, `user_from_header(header: str | None, verify) -> str`, `DEV_USER = "dev-owner"`
- Produces: `Settings.auth: Literal["supabase", "dev"] = "supabase"`, `supabase_url: str`, `owner_ids: str`(쉼표), `dev_token: SecretStr`, `web_origin: str = "http://localhost:3000"`

- [ ] **Step 1: 의존성**: `uv add "pyjwt[crypto]>=2.15.1"` (2.15.1은 mcp를 따라 이미 잠금 파일에 있고 cryptography 50.0.2도 있다. 잠금 파일에는 직접 의존성 줄만 더해진다 [실측 11-07])

- [ ] **Step 2: 실패하는 시험**: `tests/test_auth.py` (새 파일)

<!-- fmt: off -->
```python
"""화면 서버 로그인 확인 시험 (계획 4b Task 4, C4). 시험 안에서 만든 ES256 키로 돌고 네트워크를 안 쓴다."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from marvia.auth import DEV_USER, AuthError, check_startup, dev_verifier, supabase_verifier, user_from_header
from marvia.config import Settings

BASE = "https://demo.supabase.test"
KEY = ec.generate_private_key(ec.SECP256R1())  # [왜] 시험 안에서 만든 키. 저장소에 키를 두지 않는다
OTHER = ec.generate_private_key(ec.SECP256R1())
SETTINGS = Settings(_env_file=None, supabase_url=BASE, owner_ids="owner-1, owner-2")


def token(key=KEY, **changes) -> str:
    claims = {
        "sub": "owner-1",
        "iss": f"{BASE}/auth/v1",
        "aud": "authenticated",
        "exp": int(time.time()) + 300,
    }
    claims = {k: v for k, v in (claims | changes).items() if v is not None}
    return jwt.encode(claims, key, algorithm="ES256")


VERIFY = supabase_verifier(SETTINGS, signing_key=lambda raw: KEY.public_key())


def test_a_signed_token_of_an_owner_gives_its_user_id():
    assert user_from_header(f"Bearer {token()}", VERIFY) == "owner-1"


@pytest.mark.parametrize(
    "bad",
    [
        token(OTHER),  # 서명이 다른 키
        token(exp=int(time.time()) - 10),  # 만료
        token(iss="https://other.supabase.test/auth/v1"),  # 다른 프로젝트가 발급
        token(aud="anon"),  # 로그인한 사용자 토큰이 아니다
        token(exp=None),  # 만료 시각이 없다
        "not-a-jwt",
    ],
    ids=["signature", "expired", "issuer", "audience", "no-exp", "garbage"],
)
def test_bad_tokens_are_401_without_the_reason_text(bad):
    with pytest.raises(AuthError) as refused:
        user_from_header(f"Bearer {bad}", VERIFY)
    assert refused.value.status == 401 and str(refused.value) == "로그인을 확인하지 못했어요"


def test_a_signed_token_outside_the_owner_list_is_403():
    with pytest.raises(AuthError) as refused:
        user_from_header(f"Bearer {token(sub='stranger')}", VERIFY)
    assert refused.value.status == 403


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer ", "Bearer"])
def test_a_missing_or_other_scheme_header_is_401(header):
    with pytest.raises(AuthError) as refused:
        user_from_header(header, VERIFY)
    assert refused.value.status == 401


def test_dev_login_takes_only_its_fixed_token():
    verify = dev_verifier(Settings(_env_file=None, auth="dev", dev_token="local-dev-token"))
    assert user_from_header("Bearer local-dev-token", verify) == DEV_USER
    with pytest.raises(AuthError):
        user_from_header("Bearer local-dev-token-x", verify)


@pytest.mark.parametrize(
    ("changes", "cloud_run", "message"),
    [
        ({"auth": "dev", "dev_token": "t"}, True, "Cloud Run"),
        ({"auth": "dev"}, False, "MARVIA_DEV_TOKEN"),
        ({"owner_ids": "owner-1"}, False, "MARVIA_SUPABASE_URL"),
        ({"supabase_url": BASE}, False, "MARVIA_OWNER_IDS"),
    ],
    ids=["dev-on-cloud-run", "dev-without-token", "no-supabase-url", "no-owners"],
)
def test_the_server_refuses_to_start_with_an_unsafe_login_setting(monkeypatch, changes, cloud_run, message):
    # [왜] 개발 로그인이 운영에 켜진 채 배포되거나, 로그인 확인 없이 뜨는 일을 시작에서 막는다 (fail-closed)
    for name in ("MARVIA_AUTH", "MARVIA_SUPABASE_URL", "MARVIA_OWNER_IDS", "MARVIA_DEV_TOKEN"):
        monkeypatch.delenv(name, raising=False)  # [왜] 셸에 걸린 값이 시험의 빈 설정을 채우지 않게 한다
    if cloud_run:
        monkeypatch.setenv("K_SERVICE", "marvia-api")  # Cloud Run이 넣는 환경 변수
    else:
        monkeypatch.delenv("K_SERVICE", raising=False)
    with pytest.raises(RuntimeError, match=message):
        check_startup(Settings(_env_file=None, **changes))
```
<!-- fmt: on -->

```bash
uv run pytest -q tests/test_auth.py
```

Expected: FAIL `ModuleNotFoundError: No module named 'marvia.auth'`

- [ ] **Step 3: 코드**: `rules/server.yaml` 끝에 더한다:

```yaml

auth:
  audience: authenticated # Supabase가 로그인한 사용자 토큰에 넣는 aud
  algorithms: [ES256] # [주의] 목록을 열면 alg를 HS256·none으로 바꾼 위조 토큰이 통할 수 있다
```

`src/marvia/config.py`:

```diff
--- a/src/marvia/config.py
+++ b/src/marvia/config.py
@@ -62,3 +62,13 @@
     # 규정 검색 MCP (계획 3b Task 8). [왜] mcp면 에이전트 RAG가 같은 MCP 서버를 메모리 통로로 부른다(설계 9절)
     rag_via: Literal["direct", "mcp"] = "mcp"  # MARVIA_RAG_VIA
     mcp_token: SecretStr = SecretStr("")  # MARVIA_MCP_TOKEN. 비면 scripts/serve_mcp.py가 뜨지 않는다
+
+    # 화면 서버 (계획 4b, 설계 10절·12절).
+    # [왜] 사용자는 서명을 확인한 토큰에서만 꺼낸다. 화면이 보낸 값은 믿지 않는다
+    # MARVIA_AUTH. dev는 이 컴퓨터에서만 쓴다(Cloud Run이면 시작을 거절한다)
+    auth: Literal["supabase", "dev"] = "supabase"
+    supabase_url: str = ""  # MARVIA_SUPABASE_URL (https://<프로젝트>.supabase.co). 비밀이 아니다
+    # MARVIA_OWNER_IDS. 쓸 수 있는 사용자 id(토큰 sub)를 쉼표로. 비면 supabase 모드 서버가 뜨지 않는다
+    owner_ids: str = ""
+    dev_token: SecretStr = SecretStr("")  # MARVIA_DEV_TOKEN. auth=dev일 때만 받는 고정 토큰
+    web_origin: str = "http://localhost:3000"  # MARVIA_WEB_ORIGIN. 화면 주소. CORS는 이 origin만 연다
```

`.env.example` 끝에 더하고, 같은 블록을 값 없이 `.env` 끝에도 더한다(`.env`는 열지 않고 `cat >> .env <<'EOF'`로 붙인다):

```diff
--- a/.env.example
+++ b/.env.example
@@ -30,3 +30,14 @@
 
 # 그래프 시험이 붙는 시험용 Neo4j (docker compose의 neo4j-test). 비우면 bolt://localhost:7689. 개발 주소와 같으면 시험이 실패한다
 MARVIA_NEO4J_TEST_URL=
+
+# 화면 서버(계획 4b) 로그인: supabase(기본, Supabase Auth 토큰 ES256 확인) 또는 dev(이 컴퓨터에서만, 고정 토큰)
+MARVIA_AUTH=
+# Supabase 프로젝트 주소(https://<프로젝트>.supabase.co). 비밀이 아니다. supabase 모드에서 비면 서버가 뜨지 않는다
+MARVIA_SUPABASE_URL=
+# 쓸 수 있는 사용자 id(토큰의 sub)를 쉼표로. 목록 밖 사용자는 403
+MARVIA_OWNER_IDS=
+# auth=dev일 때 받는 고정 토큰. 운영(Cloud Run)에서는 dev 모드로 뜨지 않는다
+MARVIA_DEV_TOKEN=
+# 화면 주소. CORS는 이 origin만 연다. 비우면 http://localhost:3000
+MARVIA_WEB_ORIGIN=
```

`src/marvia/auth.py` (새 파일):

<!-- fmt: off -->
```python
"""화면 서버의 로그인 확인 (설계 10절 로그인, 12절 신뢰 경계, 계획 4b Task 4).

사용자 id는 서명을 확인한 토큰에서만 꺼낸다. 화면이 보낸 user_id·state는 받지 않는다.
- supabase(기본): Supabase Auth가 발급한 JWT를 공개키(JWKS, ES256)로 확인한다. aud·iss·exp·sub가 없으면
  거절하고, sub가 소유자 목록(MARVIA_OWNER_IDS)에 없으면 403이다. 우리 쪽에 JWT 비밀값을 두지 않는다.
- dev: 이 컴퓨터에서 화면을 돌려 볼 때만 쓰는 고정 토큰(MARVIA_DEV_TOKEN). 사용자는 DEV_USER 하나다.
하지 않는 일: 로그인 화면·가입(Supabase가 한다), 토큰 발급. 가입 막기는 Supabase 설정에서 한다(배포 절차서).
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Callable
from typing import Any

import jwt

from marvia.config import Settings
from marvia.tools.rules import load_rules

DEV_USER = "dev-owner"
Verify = Callable[[str], str]  # 토큰 → 사용자 id. 통과 못 하면 AuthError


class AuthError(Exception):
    """401·403으로 돌려줄 로그인 실패. 글에는 토큰·사유 원문을 넣지 않는다."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def owners(settings: Settings) -> set[str]:
    """MARVIA_OWNER_IDS(쉼표 구분)를 집합으로."""
    return {owner.strip() for owner in settings.owner_ids.split(",") if owner.strip()}


def check_startup(settings: Settings) -> None:
    """서버를 띄우기 전에 로그인 설정을 본다. 맞지 않으면 시작하지 않는다(fail-closed)."""
    if settings.auth == "dev":
        # [왜] K_SERVICE는 Cloud Run이 넣는 환경 변수다. 개발 로그인이 운영에 켜진 채 배포되는 일을 막는다
        if os.environ.get("K_SERVICE"):
            raise RuntimeError("Cloud Run에서는 개발 로그인(MARVIA_AUTH=dev)으로 시작하지 않습니다")
        if not settings.dev_token.get_secret_value():
            raise RuntimeError("MARVIA_AUTH=dev인데 MARVIA_DEV_TOKEN이 비어 있습니다")
        return
    if not settings.supabase_url:
        raise RuntimeError("MARVIA_SUPABASE_URL이 없어 로그인을 확인할 수 없습니다")
    if not owners(settings):
        raise RuntimeError("MARVIA_OWNER_IDS가 비어 있습니다. 쓸 수 있는 사용자를 정해야 서버가 뜹니다")


def supabase_verifier(settings: Settings, signing_key: Callable[[str], Any] | None = None) -> Verify:
    """Supabase JWT 확인 함수. signing_key(토큰 → 공개키)를 주면 JWKS 대신 쓴다(시험은 네트워크 없이 돈다)."""
    base = settings.supabase_url.rstrip("/")
    allowed = owners(settings)
    cfg = load_rules("server")["auth"]
    if signing_key is None:
        # [왜] 공개키 목록은 한 번 받아 두고, 토큰의 kid가 목록에 없을 때만 다시 받는다(PyJWKClient 캐시)
        client = jwt.PyJWKClient(f"{base}/auth/v1/.well-known/jwks.json")

        def from_jwks(token: str) -> Any:
            return client.get_signing_key_from_jwt(token).key

        key_of = from_jwks
    else:
        key_of = signing_key

    def verify(token: str) -> str:
        try:
            claims = jwt.decode(
                token,
                key_of(token),
                algorithms=cfg["algorithms"],
                audience=cfg["audience"],
                issuer=f"{base}/auth/v1",  # [왜] 다른 Supabase 프로젝트에서 받은 토큰을 막는다
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
        except jwt.PyJWTError:
            # [주의] 사유 원문(만료 시각, 기대한 발급처 등)은 응답에 넣지 않는다
            raise AuthError(401, "로그인을 확인하지 못했어요") from None
        if claims["sub"] not in allowed:
            raise AuthError(403, "이 서비스를 쓸 수 있는 계정이 아니에요")
        return claims["sub"]

    return verify


def dev_verifier(settings: Settings) -> Verify:
    """개발 로그인 확인 함수: 고정 토큰과 상수 시간으로 비교한다."""
    expected = settings.dev_token.get_secret_value().encode()

    def verify(token: str) -> str:
        if not expected or not hmac.compare_digest(token.encode(), expected):
            raise AuthError(401, "로그인을 확인하지 못했어요")
        return DEV_USER

    return verify


def verifier(settings: Settings) -> Verify:
    """설정에 맞는 확인 함수. 시작 검사를 먼저 한다."""
    check_startup(settings)
    return dev_verifier(settings) if settings.auth == "dev" else supabase_verifier(settings)


def user_from_header(header: str | None, verify: Verify) -> str:
    """Authorization 머리글("Bearer <토큰>")에서 사용자 id를 꺼낸다. 없거나 모양이 틀리면 401."""
    scheme, _, token = (header or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError(401, "로그인이 필요해요")
    return verify(token.strip())
```
<!-- fmt: on -->

- [ ] **Step 4: 확인**: 명령 A. Expected: `649 passed`, 오류 0.

- [ ] **Step 5: 커밋**

```bash
git add src/marvia/auth.py src/marvia/config.py rules/server.yaml .env.example tests/test_auth.py pyproject.toml uv.lock
git commit -m "feat(auth): Supabase 토큰 확인과 소유자 목록, 개발 로그인, 시작 검사"
```

(`.env`는 올리지 않는다.)

#### 커밋 4b: fix(graph): 서버 길에서 user_id가 없으면 멈춤 (R-048)

**Files:**
- Modify: `src/marvia/graph/tools.py`
- Test: `tests/graph/test_agent.py`

**Interfaces:**
- Produces: `marvia.graph.tools.SERVER_SURFACE = "server"`, `MissingUser(PermissionError)`. `user_of(config)`는 user_id가 있으면 그것, 없고 `configurable.surface == "server"`면 `MissingUser`, 그 밖은 `"local"`.

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_agent.py
+++ b/tests/graph/test_agent.py
@@ -15,7 +15,7 @@
 from marvia.graph.agent import ONE_IN_PROGRESS
 from marvia.graph.main import build_main_graph
 from marvia.graph.schemas import Draft
-from marvia.graph.tools import search_calls, worst_search_calls
+from marvia.graph.tools import MissingUser, search_calls, worst_search_calls
 from marvia.llm import LLMFailed
 from marvia.prompts import render
 from marvia.rag.models import SearchFailed
@@ -1456,3 +1456,11 @@
     graph = agent_graph(agent_deps, say(), write=lambda p: missing)
     out = graph.invoke({"text": "관세법 제999조는 뭐라고 해요?"}, cfg("nf2"))
     assert out["answer"].startswith(NOT_FOUND_LEAD) and missing.answer in out["answer"]
+
+
+def test_the_server_graph_refuses_to_run_without_a_user_id(agent_deps):
+    # [왜] R-048: 로그인 없는 길이 "local" 칸을 함께 쓰지 않는다. 서버가 붙이는 표시가 있으면 멈춘다
+    graph = agent_graph(agent_deps, say(), store=InMemoryStore())
+    server_graph = graph.with_config(configurable={"surface": "server"})
+    with pytest.raises(MissingUser):
+        server_graph.invoke({"text": "수입신고 기한?"}, {"configurable": {"thread_id": "no-user"}})
```

```bash
uv run pytest -q tests/graph/test_agent.py::test_the_server_graph_refuses_to_run_without_a_user_id
```

Expected: FAIL `ImportError: cannot import name 'MissingUser'`. (같은 내용을 `PermissionError`로 쓰면 지금 HEAD에서 `DID NOT RAISE` [실측 11-07].)

- [ ] **Step 2: 코드**

```diff
--- a/src/marvia/graph/tools.py
+++ b/src/marvia/graph/tools.py
@@ -48,9 +48,26 @@
     return str(error) if isinstance(error, (LLMFailed, SearchFailed)) else type(error).__name__
 
 
+# 화면 서버가 컴파일한 그래프에 붙이는 표시 (server.build_app). 이 표시가 있으면 user_id 없이 돌지 않는다
+SERVER_SURFACE = "server"
+
+
+class MissingUser(PermissionError):
+    """화면 서버 길에서 user_id 없이 사용자 데이터에 닿으려 했다 (R-048)."""
+
+
 def user_of(config: RunnableConfig) -> str:
-    """장기 기억을 나누는 사용자 id. 실행 설정의 configurable.user_id, 없으면 "local"(로그인 전)."""
-    return config.get("configurable", {}).get("user_id", "local")
+    """장기 기억·감시를 나누는 사용자 id. 실행 설정의 configurable.user_id.
+
+    없으면 CLI·시험 길에서만 "local"이다. 화면 서버 길(configurable.surface == "server")에서는 MissingUser를
+    낸다. [왜] 로그인한 사람이 없는데 "local" 칸을 함께 쓰면 남의 기억과 감시를 읽고 쓴다 (R-048, fail-closed)
+    """
+    configurable = config.get("configurable", {})
+    if configurable.get("user_id"):
+        return configurable["user_id"]
+    if configurable.get("surface") == SERVER_SURFACE:
+        raise MissingUser("화면 서버 길에는 user_id가 있어야 합니다")
+    return "local"
 
 
 def _reply(runtime: ToolRuntime, text: str, **update) -> Command:
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `650 passed`, 오류 0.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/graph/tools.py tests/graph/test_agent.py
git commit -m "fix(graph): 화면 서버 길에서 user_id 없이 사용자 데이터에 닿으면 멈춤 (R-048)"
```

장부에 확인점 줄을 남긴다: `CP1 (11-09): T0~T4 done? <yes/no, cut applied>`.

---
### Task 5a: AG-UI 엔드포인트, 허용 목록 보기, thread 잠금 (done 4.1 서버, 결정 D1)

**배울 것:** AG-UI는 "에이전트 한 번 실행"을 이벤트 흐름으로 본다. 클라이언트는 `RunAgentInput`(`threadId`, `runId`, `messages`, `state`, `tools`, `context`, `forwardedProps`, 끼어들기 답이면 `resume[]`)을 POST하고, 서버는 SSE(`data: {json}` 줄과 빈 줄)로 `RUN_STARTED` → … → `RUN_FINISHED`(`outcome`이 `success` 또는 `interrupt`와 `interrupts[]`) 또는 `RUN_ERROR`를 보낸다. `ag-ui-protocol` 1.0.0의 모델은 snake_case 이름을 camelCase로 내보내고 값이 없는 선택 칸은 빼며, `EventEncoder().encode(event)`가 `data: …\n\n` 한 줄을 만든다 [실측 11-07 scratch: `{"type":"RUN_FINISHED","threadId":"t","runId":"r","outcome":{"type":"interrupt","interrupts":[{"id":"i1","reason":"choice",...}]}}`]. 그래프는 동기라 작업 스레드 하나에서 `graph.stream(payload, config, stream_mode="updates", subgraphs=True)`로 끝까지 돌리고 이벤트는 큐로 넘긴다. Starlette는 동기 iterator를 `next()`마다 다른 스레드에서 부를 수 있어 이렇게 한다. 큐를 기다리는 쪽은 `anyio.to_thread.run_sync(q.get, abandon_on_cancel=True)`라 브라우저가 끊으면 바로 빠져나오고, 멈춤 깃발을 세워 그래프는 다음 갱신에서 멈춘다 [문서 11-07 설치된 anyio 4.15.1·starlette 1.10.0]. 답(`answer`)은 저장하지 않는 칸이라 메인 그래프 노드의 갱신에서 읽는다. 끼어들기는 끝난 뒤 `get_state(config).interrupts[0]`(id와 값)에서 카드로 만든다.

**Files:**
- Create: `src/marvia/view.py`, `src/marvia/server.py`, `tests/graph/test_server.py`
- Modify: `rules/server.yaml`, `pyproject.toml`, `uv.lock`

**Interfaces:**
- Consumes: `auth.user_from_header`, `auth.verifier`, `Verify` (4a), `tools.SERVER_SURFACE` (4b), `db.read_pool` (2a), `graph.live.agent_deps(settings, pool, watch_conn)`, `live_memory` (2b, 3d)
- Produces: `marvia.view.screen_view(values: dict) -> {"plan", "reading", "cargos", "evidence"}`, `interrupt_card(value: dict, mask_map) -> {"kind": "choice", "question", "options", "recommended", "timeout_s"} | {"kind": "approval", "actions": [{"name", "args", "description", "allowed"}]}`
- Produces: `marvia.server.build_app(graph, verify, *, web_origin: str) -> Starlette` (`POST /agui`, `GET /health`), `turn_input(graph, body, config)`, `turn_events(graph, payload, config, thread, run, stop) -> Iterator[BaseEvent]`, `main()` (`python -m marvia.server`, `PORT` 기본 8080)
- Produces (화면과의 약속): SSE `STATE_SNAPSHOT.snapshot` = `screen_view`, `RUN_FINISHED.outcome.interrupts[0]` = `{id, reason: "choice"|"approval", metadata: 카드}`, 재개는 `resume[0] = {interruptId, status: "resolved", payload}`. 선택지 payload는 `{"selected": i} | {"custom": 글} | {"timeout": true}`, 승인 payload는 `{"decisions": [...]}`.

- [ ] **Step 1: 의존성**: `uv add "ag-ui-protocol>=1.0.0" "starlette>=1.10.0" "uvicorn>=0.54.0"` (잠금 파일에 `ag-ui-protocol` 1.0.0 한 묶음이 더해진다. starlette·uvicorn은 이미 있다 [실측 11-07])

- [ ] **Step 2: 실패하는 시험**: `tests/graph/test_server.py` (새 파일)

<!-- fmt: off -->
```python
"""화면 서버(AG-UI SSE) 시험 (계획 4b Task 5·6, C4·C5·C6·C7). 가짜 모델로 키·네트워크 없이 돈다."""

import json
import threading

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from starlette.testclient import TestClient

from marvia.auth import AuthError
from marvia.graph.main import build_main_graph
from marvia.server import build_app

TOKENS = {"tok-a": "user-a", "tok-b": "user-b"}
TWO = [{"label": "부산", "description": "부산항 기준"}, {"label": "인천", "description": "인천항 기준"}]
SNAPSHOT_KEYS = {"plan", "reading", "cargos", "evidence"}


def verify(token: str) -> str:
    if token not in TOKENS:
        raise AuthError(401, "로그인을 확인하지 못했어요")
    return TOKENS[token]


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class Inputs(BaseCallbackHandler):
    def __init__(self):
        self.seen: list[str] = []

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.seen += [f"{m.content} {getattr(m, 'tool_calls', '')}" for batch in messages for m in batch]


def say(name: str, args: dict, n: int = 0) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"s{n}-{name}"}])


def served(agent_deps, *messages, **changes):
    """가짜 모델로 만든 그래프와 그 그래프를 띄운 시험 클라이언트."""
    deps = agent_deps(model=ToolModel(messages=iter(messages)), **changes)
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
    app = build_app(graph, verify, web_origin="http://web.test")
    return graph, TestClient(app)


def body(thread: str, text: str = "", resume: list | None = None, **extra) -> dict:
    out = {"threadId": thread, "runId": f"run-{thread}", "messages": [], **extra}
    if text:
        out["messages"] = [{"id": "m1", "role": "user", "content": text}]
    if resume:
        out["resume"] = resume
    return out


def run(client: TestClient, payload: dict, token: str = "tok-a") -> list[dict]:
    response = client.post("/agui", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in response.text.split("\n") if line.startswith("data: ")]


def kinds(events: list[dict]) -> list[str]:
    return [event["type"] for event in events]


def test_a_turn_streams_in_protocol_order_and_sends_only_the_allowed_view(agent_deps):
    todos = {"todos": [{"content": "기한 계산", "status": "in_progress"}]}
    graph, client = served(
        agent_deps, say("write_todos", todos, 1), say("calc_deadlines", {}, 2), AIMessage("")
    )
    events = run(client, body("t1", "DEMO0001 언제까지 수입신고 해요?"))
    order = kinds(events)
    assert order[0] == "RUN_STARTED" and order[-1] == "RUN_FINISHED"
    assert sum(kind in ("RUN_FINISHED", "RUN_ERROR") for kind in order) == 1
    text = [kind for kind in order if kind.startswith("TEXT_MESSAGE")]
    assert text == ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"]
    snapshots = [e["snapshot"] for e in events if e["type"] == "STATE_SNAPSHOT"]
    assert all(set(s) == SNAPSHOT_KEYS for s in snapshots)  # 가림 표·메시지·원문·번호 목록은 가지 않는다
    in_progress = next(
        i for i, e in enumerate(events) if e["type"] == "STATE_SNAPSHOT" and e["snapshot"]["plan"]
    )
    assert in_progress < order.index("TEXT_MESSAGE_START")  # 할 일은 답보다 먼저 보인다
    assert snapshots[-1]["reading"] == [{"token": "[BL1]", "number": "DEMO0001", "kind": "B/L"}]
    assert snapshots[-1]["cargos"][0]["number"] == "DEMO0001"  # 화면에는 주인에게 실제 번호를 보인다
    answer = next(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert "시험 답이에요." in answer and events[-1]["outcome"] == {"type": "success"}
    assert "text" not in graph.get_state({"configurable": {"thread_id": "user-a/t1"}}).values


def test_a_question_ends_the_run_with_a_choice_card_and_the_answer_resumes_it(agent_deps):
    ask = say("ask_user", {"question": "어느 항이에요?", "options": TWO}, 1)
    graph, client = served(agent_deps, ask, AIMessage(""))
    events = run(client, body("t2", "장치기간이 궁금해요"))
    outcome = events[-1]["outcome"]
    assert outcome["type"] == "interrupt" and "TEXT_MESSAGE_START" not in kinds(events)
    card = outcome["interrupts"][0]
    assert card["reason"] == "choice" and card["metadata"]["options"][1]["label"] == "인천"
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"selected": 1}}]
    events = run(client, body("t2", resume=resume))
    assert events[-1]["outcome"] == {"type": "success"}
    values = graph.get_state({"configurable": {"thread_id": "user-a/t2"}}).values
    assert "인천" in "".join(values["clarifications"])


def test_state_and_forwarded_props_from_the_browser_are_ignored(agent_deps):
    graph, client = served(agent_deps, AIMessage(""))
    sneaky = {"llm_calls": 999, "mask_map": {"[BL1]": "EVIL00001"}, "actions": ["다 지웠어요"]}
    run(client, body("t4", "DEMO0001 언제까지?", state=sneaky, forwardedProps=sneaky))
    values = graph.get_state({"configurable": {"thread_id": "user-a/t4"}}).values
    assert values["mask_map"] == {"[BL1]": "DEMO0001"}
    assert values["llm_calls"] < 999 and values["actions"] == []


def test_no_login_is_401_and_the_graph_is_not_called(agent_deps):
    graph, client = served(agent_deps)  # [왜] 모델 메시지가 없다. 그래프가 돌면 StopIteration으로 실패한다
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = client.post("/agui", json=body("t5", "DEMO0001 언제?"), headers=headers)
        assert response.status_code == 401
    assert graph.get_state({"configurable": {"thread_id": "user-a/t5"}}).values == {}


def test_another_users_thread_id_reaches_only_that_users_own_thread(agent_deps):
    graph, client = served(agent_deps, AIMessage(""), AIMessage(""))
    run(client, body("shared", "DEMO0001 언제까지?"), token="tok-a")
    events = run(client, body("shared", "그 화물 어디 있어요?"), token="tok-b")
    assert "DEMO0001" not in json.dumps(events, ensure_ascii=False)
    values = graph.get_state({"configurable": {"thread_id": "user-b/shared"}}).values
    assert values.get("mask_map", {}) == {}  # B는 A의 가림 표를 읽지 못한다


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        (body("bad/id", "질문"), 422),
        (body("t6", ""), 422),
        (body("t6", "가" * 2001), 422),
        (body("t6", resume=[{"interruptId": "x", "status": "resolved", "payload": {}}]), 409),
        ({"threadId": "t6"}, 422),
    ],
    ids=["thread-id", "empty", "too-long", "nothing-to-resume", "shape"],
)
def test_bad_requests_are_refused_before_the_graph_runs(agent_deps, payload, status):
    _, client = served(agent_deps)
    response = client.post("/agui", json=payload, headers={"Authorization": "Bearer tok-a"})
    assert response.status_code == status


def test_a_second_run_on_a_busy_thread_is_409(agent_deps, fake_rag):
    entered, gate = threading.Event(), threading.Event()
    rag = fake_rag()

    def slow_search(query, as_of):
        entered.set()
        gate.wait(10)  # [왜] 첫 차례를 검색 안에 붙잡아 두고 둘째 요청을 보낸다
        return rag.search(query, as_of)

    slow = type(rag)(**{**rag.__dict__, "search": slow_search})
    _, client = served(agent_deps, say("search_law", {"query": "수입신고 기한"}, 1), AIMessage(""), rag=slow)
    first: list = []
    worker = threading.Thread(target=lambda: first.append(run(client, body("t8", "수입신고 기한?"))))
    worker.start()
    assert entered.wait(10)
    second = client.post("/agui", json=body("t8", "또 물어요"), headers={"Authorization": "Bearer tok-a"})
    gate.set()
    worker.join(10)
    assert second.status_code == 409
    assert first[0][-1]["type"] == "RUN_FINISHED"


def test_cors_opens_only_the_screen_origin(agent_deps):
    _, client = served(agent_deps)
    asked = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization"}
    ok = client.options("/agui", headers={"Origin": "http://web.test", **asked})
    other = client.options("/agui", headers={"Origin": "http://evil.test", **asked})
    assert ok.headers.get("access-control-allow-origin") == "http://web.test"
    assert "access-control-allow-origin" not in other.headers


def test_the_server_refuses_to_start_without_model_and_data_keys(monkeypatch, tmp_path):
    # [왜] 키 없이 뜨면 차례마다 실패한다. 시작에서 거절해 배포 확인(dry-run)에서 바로 보이게 한다 (C10)
    from marvia import server

    monkeypatch.chdir(tmp_path)  # [왜] 저장소의 .env를 읽지 않게 빈 폴더에서 돈다
    for name in ("MARVIA_ANTHROPIC_API_KEY", "MARVIA_VOYAGE_API_KEY", "MARVIA_DATA_KEY", "K_SERVICE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MARVIA_AUTH", "dev")
    monkeypatch.setenv("MARVIA_DEV_TOKEN", "local-dev-token")
    with pytest.raises(RuntimeError, match="MARVIA_ANTHROPIC_API_KEY"):
        server.main()


def test_the_view_links_only_to_the_official_site_over_https(evidence):
    # [왜] 근거 패널의 링크는 국가법령정보센터(rules agent.yaml official.allowed_hosts)만 연다.
    #      javascript: 링크를 막는다
    from marvia.view import screen_view

    urls = [
        "https://www.law.go.kr/법령/관세법",
        "javascript:alert(1)",
        "http://www.law.go.kr/x",
        "https://evil.test/x",
    ]
    values = {"evidence": [dict(evidence[0], unit_id=f"u{i}", source_url=url) for i, url in enumerate(urls)]}
    assert [e["source_url"] for e in screen_view(values)["evidence"]] == [urls[0], None, None, None]
```
<!-- fmt: on -->

```bash
uv run pytest -q tests/graph/test_server.py
```

Expected: FAIL `ModuleNotFoundError: No module named 'marvia.server'`

- [ ] **Step 3: 코드**: `rules/server.yaml` 끝에 더한다:

```yaml

request:
  max_text: 2000 # 사용자 글 한 번의 글자 수 상한. 넘으면 422
  max_body_bytes: 65536 # 요청 본문 바이트 상한. 넘으면 413

question:
  timeout_s: 120 # 선택지 카드에 답이 없으면 화면이 {"timeout": true}로 재개하는 초 (설계 6.3)

```

`src/marvia/view.py` (새 파일):

<!-- fmt: off -->
```python
"""화면에 보낼 값만 고르는 허용 목록 (설계 10절 화면 구성, 12절 신뢰 경계, 계획 4b Task 5).

공책(state)의 어느 칸이 브라우저로 가는지는 이 파일만 정한다. 토큰을 실제 번호로 되돌리는 일도 화면 길에서는
여기서만 한다. 가림 표(mask_map), 메시지, 원문(text), 조회할 번호(numbers)는 보내지 않는다.
하지 않는 일: 답 글 만들기(graph/answer.py), ETA·등급(선박 위치 조회와 함께 2차, 설계 10절 화물 카드).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from marvia.identify.mask import unmask
from marvia.tools.rules import load_rules

# 토큰 이름표 → 화면에 보일 이름 ("이렇게 읽었어요")
KIND_NAMES = {"BL": "B/L", "CARGO": "화물관리번호", "NUM": "읽지 못한 덩어리"}


def _unmask_all(value: Any, mask_map: dict[str, str]) -> Any:
    """값 안의 모든 글에서 토큰을 실제 번호로 되돌린다 (승인 카드의 인자)."""
    if isinstance(value, str):
        return unmask(value, mask_map)
    if isinstance(value, dict):
        return {key: _unmask_all(item, mask_map) for key, item in value.items()}
    if isinstance(value, list):
        return [_unmask_all(item, mask_map) for item in value]
    return value


def _link(url: str) -> str | None:
    """출처 링크는 허용한 공식 사이트(https)만 보낸다. 아니면 None(화면은 글자만 보인다)."""
    parsed = urlparse(url)
    allowed = load_rules("agent")["official"]["allowed_hosts"]
    return url if parsed.scheme == "https" and parsed.hostname in allowed else None


def _plan(values: dict) -> list[dict]:
    """할 일 목록. 에이전트 길은 todos, 계획자 길은 plan을 같은 모양({content, status})으로 바꾼다."""
    if values.get("todos"):
        return [{"content": t["content"], "status": t["status"]} for t in values["todos"]]
    status = {"in_progress": "in_progress", "done": "completed", "pending": "pending"}
    return [
        {"content": f"{s['action']}: {s['query']}".rstrip(": "), "status": status.get(s["status"], "pending")}
        for s in values.get("plan", [])
    ]


def screen_view(values: dict) -> dict:
    """STATE_SNAPSHOT에 실을 값: 할 일, "이렇게 읽었어요", 화물 카드, 근거 패널."""
    mask_map = values.get("mask_map", {})
    reading = [
        {"token": token, "number": number, "kind": KIND_NAMES[token.strip("[]").rstrip("0123456789")]}
        for token, number in mask_map.items()
    ]
    cargos = []
    for cargo in values.get("cargos", []):
        facts, error = cargo.get("facts") or {}, cargo.get("error") or {}
        cargos.append(
            {
                "number": unmask(cargo["token"], mask_map),
                "stage": facts.get("stage"),
                "stage_at": facts.get("stage_at"),
                "port": facts.get("port"),
                "vessel": facts.get("vessel_name"),
                "source": facts.get("source"),
                "fetched_at": facts.get("fetched_at"),
                "error": error.get("message"),
            }
        )
    evidence = [
        {
            "unit_id": e["unit_id"],
            "heading": e["heading"],
            "effective": e["effective"],
            "text": e["text"],
            "source_url": _link(e["source_url"]),
        }
        for e in values.get("evidence", [])
    ]
    return {"plan": _plan(values), "reading": reading, "cargos": cargos, "evidence": evidence}


def interrupt_card(value: dict, mask_map: dict[str, str]) -> dict:
    """멈춘 이유(interrupt 값)를 화면 카드로 바꾼다: 선택지 카드 또는 승인 카드 (설계 6.3)."""
    if "action_requests" in value:
        # [왜] review_configs는 도구 이름마다 하나다(요청 순서가 아니다). 모르는 도구는 승인·거절만 연다
        allowed = {c["action_name"]: c["allowed_decisions"] for c in value.get("review_configs", [])}
        return {
            "kind": "approval",
            "actions": [
                {
                    "name": request["name"],
                    "args": _unmask_all(request["args"], mask_map),
                    "description": unmask(request.get("description", ""), mask_map),
                    "allowed": allowed.get(request["name"], ["approve", "reject"]),
                }
                for request in value["action_requests"]
            ],
        }
    return {
        "kind": "choice",
        "question": unmask(value["question"], mask_map),
        "options": [
            {"label": unmask(o["label"], mask_map), "description": unmask(o["description"], mask_map)}
            for o in value["options"]
        ],
        "recommended": value["recommended"],
        "timeout_s": load_rules("server")["question"]["timeout_s"],
    }
```
<!-- fmt: on -->

`src/marvia/server.py` (새 파일):

<!-- fmt: off -->
```python
"""화면 서버: 에이전트 한 차례를 AG-UI 이벤트(SSE)로 흘려보낸다 (설계 3절·10절·12절, 계획 4b Task 5).

ag-ui-langgraph 어댑터를 쓰지 않고 ag-ui-protocol의 이벤트 타입·인코더로 엔드포인트를 직접 쓴다.
[왜] 어댑터는 화면이 보낸 메시지·state를 그래프 입력에 합치고, 공책 전체(가림 표 포함)를
     STATE_SNAPSHOT으로 보내고, 비동기 저장기를 요구한다(계획 4b 사전 부검 1번). 여기서는 받는 값을
     마지막 사용자 글과 재개 값으로 줄이고, 보내는 값은 view.py의 허용 목록만 쓴다.
흐름: POST /agui → 로그인 확인(auth) → thread 잠금 → 작업 스레드 하나에서 graph.stream → 큐 → SSE
     RUN_STARTED → STATE_SNAPSHOT(할 일·읽은 번호·화물·근거가 바뀔 때마다) → (답이면 TEXT_MESSAGE_*)
     → RUN_FINISHED(outcome success 또는 interrupt + 카드) | RUN_ERROR
하지 않는 일: 화면 그리기(web/), 가림 판단(identify), 모델 호출, 표 만들기(python -m marvia.migrate).
"""

from __future__ import annotations

import os
import queue
import re
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import anyio
import psycopg
import uvicorn
from ag_ui.core import (
    BaseEvent,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunFinishedSuccessOutcome,
    RunStartedEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from ag_ui.core import Interrupt as CardInterrupt
from ag_ui.encoder import EventEncoder
from langgraph.types import Command
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from marvia.auth import AuthError, Verify, user_from_header, verifier
from marvia.config import Settings
from marvia.db import read_pool
from marvia.graph.live import agent_deps, live_memory
from marvia.graph.main import build_main_graph
from marvia.graph.resume import approval_reply
from marvia.graph.state import merge_cargos, merge_evidence
from marvia.graph.tools import SERVER_SURFACE
from marvia.tools.rules import load_rules
from marvia.view import interrupt_card, screen_view

# [왜] 화면이 정하는 thread id는 이름 공간 안의 이름일 뿐이다.
#      서버가 "사용자/이름"으로 묶어 남의 대화에 닿지 못한다
THREAD_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
# [왜] 프록시·압축이 이벤트를 모았다가 한꺼번에 보내면 "진행 중인 할 일"이 답과 함께 뜬다
SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
LIVE_KEYS = ("todos", "plan", "cargos", "evidence", "mask_map")  # 화면 보기를 바꾸는 공책 칸
CHOICE_KEYS = ("selected", "custom", "timeout")  # 선택지 재개 값에서 받는 칸 (설계 6.3)


class Refused(Exception):
    """그래프를 부르기 전에 요청을 거절한다. status에 상태 코드를 둔다."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _merge(live: dict, update: dict, inside: bool) -> bool:
    """흘러온 갱신 하나를 화면용 공책 사본에 반영한다. 화면 보기가 바뀌면 True."""
    changed = False
    for key in LIVE_KEYS:
        if key not in update:
            continue
        value = update[key]
        # [왜] 루프(서브그래프) 안의 도구 갱신은 새로 찾은 것만 담는다. 공책의 합치는 함수와 같게 합친다.
        #      바깥(메인 그래프) 노드의 갱신은 칸 전체 값이다
        if inside and key == "evidence":
            limit = load_rules("agent")["answer"]["max_evidence"]
            value = merge_evidence(live.get("evidence", []), value, limit)
        elif inside and key == "cargos":
            value = merge_cargos(live.get("cargos", []), value)
        live[key] = value
        changed = True
    return changed


def _parts(update: Any) -> list[dict]:
    """노드 갱신 하나를 dict 목록으로. 도구 노드는 갱신을 여러 개(목록) 낼 수 있다."""
    items = update if isinstance(update, list) else [update]
    return [item for item in items if isinstance(item, dict)]


def turn_events(
    graph, payload: Any, config: dict, thread: str, run: str, stop: threading.Event
) -> Iterator[BaseEvent]:
    """한 차례를 돌리며 AG-UI 이벤트를 낸다. 작업 스레드 하나에서 끝까지 돈다(동기 그래프와 저장기)."""
    yield RunStartedEvent(thread_id=thread, run_id=run)
    answer = ""
    try:
        live = dict(graph.get_state(config).values)  # [왜] 재개 차례도 지난 화물·읽은 번호를 이어 보인다
        for namespace, chunk in graph.stream(payload, config, stream_mode="updates", subgraphs=True):
            if stop.is_set():
                return  # [왜] 브라우저가 끊었다. 다음 단계로 가지 않고 멈춰 LLM 비용을 더 쓰지 않는다
            for node, update in chunk.items():
                for part in _parts(update):
                    if not namespace and "answer" in part:
                        answer = part["answer"]  # [왜] 답은 저장하지 않는 칸이라 갱신에서만 읽는다 (R-035)
                    if node != "__interrupt__" and _merge(live, part, inside=bool(namespace)):
                        yield StateSnapshotEvent(snapshot=screen_view(live))
        state = graph.get_state(config)
    except Exception as error:
        # [왜] 어떤 실패든 화면에 끝을 알린다. 오류 글은 보내지 않는다(번호·주소가 섞일 수 있다)
        yield RunErrorEvent(
            message="이번 차례를 끝내지 못했어요. 다시 물어봐 주세요.", code=type(error).__name__
        )
        return
    if state.interrupts:
        pending = state.interrupts[
            0
        ]  # [왜] 질문과 승인은 한 번에 하나씩 멈춘다 (batched, ask_user 혼자 부르기)
        card = interrupt_card(pending.value, state.values.get("mask_map", {}))
        stopped = CardInterrupt(id=pending.id, reason=card["kind"], metadata=card)
        outcome = RunFinishedInterruptOutcome(interrupts=[stopped])
        yield RunFinishedEvent(thread_id=thread, run_id=run, outcome=outcome)
        return
    message = f"{run}-answer"
    yield TextMessageStartEvent(message_id=message, role="assistant")
    yield TextMessageContentEvent(message_id=message, delta=answer)
    yield TextMessageEndEvent(message_id=message)
    yield RunFinishedEvent(thread_id=thread, run_id=run, outcome=RunFinishedSuccessOutcome())


def turn_input(graph, body: RunAgentInput, config: dict) -> Any:
    """그래프에 넣을 값: 새 질문이면 {"text": 마지막 사용자 글}, 재개면 Command(resume=정리한 값).

    [주의] 화면이 보낸 state·forwardedProps·지난 메시지는 읽지 않는다.
           호출 수 상한이나 가림 표를 화면이 바꿀 수 없다.
    """
    max_text = load_rules("server")["request"]["max_text"]
    if body.resume:
        state = graph.get_state(config)
        if not state.interrupts or body.resume[0].interrupt_id != state.interrupts[0].id:
            raise Refused(409, "답할 질문이 없거나 이미 지난 카드예요")
        value, raw = state.interrupts[0].value, body.resume[0].payload
        raw = raw if isinstance(raw, dict) else {}
        if "action_requests" in value:
            names = [request["name"] for request in value["action_requests"]]
            # [왜] 모양이 틀린 결정은 거절로 바꾼다(approval_reply). 고친 인자 다시 가리기는 Task 5b
            return Command(resume=approval_reply(raw, len(names), names))
        choice = {key: raw[key] for key in CHOICE_KEYS if key in raw}
        if len(str(choice.get("custom", ""))) > max_text:
            raise Refused(422, "글이 너무 길어요")
        return Command(resume=choice)
    texts = [m.content for m in body.messages if m.role == "user" and isinstance(m.content, str)]
    text = texts[-1].strip() if texts else ""
    if not text or len(text) > max_text:
        raise Refused(422, f"질문은 1~{max_text}자로 보내 주세요")
    return {"text": text}


async def _sse(
    events: Iterator[BaseEvent], stop: threading.Event, done: Callable[[], None]
) -> AsyncIterator[str]:
    """이벤트를 작업 스레드에서 만들어 큐로 받아 SSE 글로 내보낸다."""
    # [왜] Starlette는 동기 iterator의 next()를 매번 다른 스레드에서 부를 수 있다.
    #      그래프는 한 스레드에서 끝까지 돌린다
    encoder = EventEncoder()
    lines: queue.Queue[str | None] = queue.Queue()

    def work() -> None:
        try:
            for event in events:
                lines.put(encoder.encode(event))
        finally:
            done()  # [왜] thread 잠금은 그래프가 실제로 멈춘 뒤에 푼다(연결이 끊긴 때가 아니다)
            lines.put(None)

    threading.Thread(target=work, daemon=True).start()
    try:
        while (line := await anyio.to_thread.run_sync(lines.get, abandon_on_cancel=True)) is not None:
            yield line
    finally:
        stop.set()


def build_app(graph, verify: Verify, *, web_origin: str) -> Starlette:
    """화면 서버 앱. graph는 컴파일한 메인 그래프, verify는 auth의 토큰 확인 함수."""
    # [왜] 이 앱이 부르는 그래프는 user_id 없이 사용자 데이터에 닿으면 멈춘다 (tools.user_of, R-048)
    graph = graph.with_config(configurable={"surface": SERVER_SURFACE})
    running: set[str] = set()
    guard = threading.Lock()
    cfg = load_rules("server")["request"]

    async def run(request: Request) -> Response:
        try:
            user = user_from_header(request.headers.get("authorization"), verify)
            body = RunAgentInput.model_validate_json(await request.body())
        except AuthError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)
        except ValidationError:
            return JSONResponse({"error": "요청 모양이 틀렸어요"}, status_code=422)
        if not THREAD_ID.fullmatch(body.thread_id):
            return JSONResponse({"error": "대화 id 모양이 틀렸어요"}, status_code=422)
        key = f"{user}/{body.thread_id}"
        with guard:
            if key in running:
                return JSONResponse({"error": "이 대화는 아직 답하는 중이에요"}, status_code=409)
            running.add(key)
        config = {"configurable": {"thread_id": key, "user_id": user}}
        try:
            payload = await anyio.to_thread.run_sync(turn_input, graph, body, config)
        except Refused as error:
            running.discard(key)
            return JSONResponse({"error": str(error)}, status_code=error.status)
        except BaseException:
            running.discard(key)
            raise
        stop = threading.Event()
        events = turn_events(graph, payload, config, body.thread_id, body.run_id, stop)
        stream = _sse(events, stop, lambda: running.discard(key))
        return StreamingResponse(stream, media_type=EventEncoder().get_content_type(), headers=SSE_HEADERS)

    async def health(request: Request) -> Response:
        return JSONResponse({"ok": True})

    middleware = [
        # [왜] 화면 주소 하나만 연다. 쿠키를 쓰지 않아 credentials는 열지 않는다
        Middleware(
            CORSMiddleware,
            allow_origins=[web_origin],
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["authorization", "content-type"],
        ),
        Middleware(RequestBodyLimitMiddleware, max_body_size=cfg["max_body_bytes"]),
    ]
    routes = [
        Route("/agui", run, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ]
    return Starlette(routes=routes, middleware=middleware)


def main() -> None:
    """운영 진입점: python -m marvia.server. 로그인 설정이 틀리면 뜨지 않는다. 포트는 PORT(Cloud Run)."""
    settings = Settings()
    verify = verifier(settings)  # [왜] 로그인 설정 검사를 DB에 붙기 전에 한다(fail-closed)
    for key in ("anthropic_api_key", "voyage_api_key", "data_key"):
        # [왜] 키 없이 뜨면 차례마다 실패한다. 배포 확인(dry-run)에서 바로 보이게 시작을 거절한다
        if not getattr(settings, key).get_secret_value():
            raise RuntimeError(f"MARVIA_{key.upper()}가 비어 있어 서버를 띄우지 않습니다")
    url = settings.database_url
    with (
        live_memory(url, settings.data_key.get_secret_value()) as (saver, store),
        read_pool(url) as pool,
        # [왜] 감시 목록은 따로 autocommit 연결을 쓴다 (R-041)
        psycopg.connect(url, autocommit=True) as watch_conn,
    ):
        deps = agent_deps(settings, pool, watch_conn)
        graph = build_main_graph(
            deps, saver, loop=settings.loop, store=store, permission_mode=settings.permission_mode
        )
        app = build_app(graph, verify, web_origin=settings.web_origin)
        # [주의] 컨테이너 안에서는 모든 주소에서 듣는다. 이 컴퓨터에서는 compose가 127.0.0.1로만 연다
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
```
<!-- fmt: on -->

- [ ] **Step 4: 확인**: 명령 A. Expected: `664 passed`, 오류 0.

- [ ] **Step 5: 커밋**

```bash
git add src/marvia/view.py src/marvia/server.py rules/server.yaml tests/graph/test_server.py pyproject.toml uv.lock
git commit -m "feat(server): AG-UI 엔드포인트와 허용 목록 화면 보기, thread 잠금"
```

---
### Task 5b: 재개 값 다시 가리기 (done 1.4의 남은 것)

**배울 것:** `HumanInTheLoopMiddleware`는 고치기(edit) 결정의 인자로 모델이 낸 도구 호출 메시지를 바꾸고, 거절(reject) 글을 그 도구의 결과 메시지로 넣는다. 둘 다 다음 모델 호출에 그대로 간다. 화면은 토큰을 실제 번호로 되돌려 보이므로 사람이 고친 값에는 실제 번호가 들어 있다. 그래서 서버가 재개하기 전에 그 대화의 가림 표(`mask_map`)로 `mask_text`를 다시 돌린다. 표에 없던 번호는 새 토큰을 만들 수 없으니(서버는 공책에 쓰지 않는다) 실행하지 않는 쪽으로 바꾼다.

**Files:**
- Modify: `src/marvia/graph/resume.py`, `src/marvia/server.py`
- Test: `tests/graph/test_resume.py`, `tests/graph/test_server.py`

**Interfaces:**
- Produces: `marvia.graph.resume.remask_reply(reply: dict, mask_map: dict[str, str]) -> dict`, `NEW_NUMBER`(정해 둔 거절 결정), `REJECTED = "사용자가 거절했어요"`
- `server.turn_input`의 승인 길: `Command(resume=remask_reply(approval_reply(raw, n, names), mask_map))`

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_resume.py
+++ b/tests/graph/test_resume.py
@@ -1,6 +1,15 @@
 """승인 재개 값 정리(graph/resume.py) 시험."""
 
-from marvia.graph.resume import approval_reply
+import pytest
+from langchain_core.callbacks import BaseCallbackHandler
+from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
+from langchain_core.messages import AIMessage
+from langgraph.checkpoint.memory import InMemorySaver
+from langgraph.store.memory import InMemoryStore
+from langgraph.types import Command
+
+from marvia.graph.main import build_main_graph
+from marvia.graph.resume import NEW_NUMBER, REJECTED, approval_reply, remask_reply
 
 REJECT = {"type": "reject", "message": "승인 값을 읽지 못해 실행하지 않았어요"}
 
@@ -40,3 +49,83 @@
 def test_names_with_a_different_count_reject_all_without_raising():
     raw = {"decisions": [{"type": "approve"}]}
     assert approval_reply(raw, 1, ["a", "b"]) == {"decisions": [REJECT]}
+
+
+# --- 재개 값 다시 가리기 (done 1.4, 계획 4b Task 6) ---
+
+MAP = {"[BL1]": "DEMO0001"}
+
+
+def _edit(args: dict) -> dict:
+    return {"type": "edit", "edited_action": {"name": "save_item_card", "args": args}}
+
+
+def test_edited_args_and_reject_text_get_this_threads_tokens_back():
+    reply = {
+        "decisions": [
+            _edit({"name": "DEMO0001 고추", "n": 3}),
+            {"type": "reject", "message": "DEMO0001 빼 줘"},
+        ]
+    }
+    assert remask_reply(reply, MAP) == {
+        "decisions": [_edit({"name": "[BL1] 고추", "n": 3}), {"type": "reject", "message": "[BL1] 빼 줘"}]
+    }
+
+
+def test_a_number_new_to_the_thread_turns_the_decision_into_a_fixed_rejection():
+    # [왜] 고치기로 새 번호를 들여오면 서버가 새 토큰을 공책에 넣을 길이 없다. 실행하지 않는 쪽으로 간다
+    reply = {"decisions": [_edit({"name": "DEMO0009"}), {"type": "reject", "message": "DEMO0009는 아니에요"}]}
+    assert remask_reply(reply, MAP) == {"decisions": [NEW_NUMBER, {"type": "reject", "message": REJECTED}]}
+
+
+class ToolModel(GenericFakeChatModel):
+    def bind_tools(self, tools, **kwargs):
+        return self
+
+
+class Inputs(BaseCallbackHandler):
+    """채팅 모델에 들어간 메시지 글과 도구 호출 인자를 모은다."""
+
+    def __init__(self):
+        self.seen: list[str] = []
+
+    def on_chat_model_start(self, serialized, messages, **kwargs):
+        self.seen += [f"{m.content} {getattr(m, 'tool_calls', '')}" for batch in messages for m in batch]
+
+
+CHILI = {
+    "category": "농산물·임산물",
+    "same": ["생산국", "품명", "수출업소", "포장장소"],
+    "different": [],
+    "prior_precise": "받음",
+    "prior_result": "적합",
+    "prior_cert_on": "2026-03-10",
+    "flags": [],
+}
+
+
+@pytest.mark.parametrize(
+    "decision", [_edit({"name": "DEMO0001 고추"}), {"type": "reject", "message": "DEMO0001은 빼 주세요"}]
+)
+@pytest.mark.parametrize("remask", [True, False])
+def test_the_model_never_sees_a_number_typed_on_the_approval_card(agent_deps, decision, remask):
+    steps = [
+        AIMessage("", tool_calls=[{"name": "check_reimport", "args": {"facts": CHILI}, "id": "c1"}]),
+        AIMessage("", tool_calls=[{"name": "save_item_card", "args": {"name": "건고추"}, "id": "c2"}]),
+        AIMessage(""),
+    ]
+    graph = build_main_graph(
+        agent_deps(model=ToolModel(messages=iter(steps))),
+        InMemorySaver(),
+        loop="agent",
+        store=InMemoryStore(),
+    )
+    inputs = Inputs()
+    config = {"configurable": {"thread_id": f"remask-{remask}"}, "callbacks": [inputs]}
+    out = graph.invoke({"text": "DEMO0001 건고추 카드로 기억해 줘"}, config)
+    reply = approval_reply({"decisions": [decision]}, 1, ["save_item_card"])
+    mask_map = graph.get_state(config).values["mask_map"]
+    graph.invoke(Command(resume=remask_reply(reply, mask_map) if remask else reply), config)
+    assert "__interrupt__" in out
+    # [왜] 다시 가리지 않으면 실패하는 시험인지 함께 본다 (가린 쪽만 0이다)
+    assert any("DEMO0001" in text for text in inputs.seen) is (not remask)
```

```diff
--- a/tests/graph/test_server.py
+++ b/tests/graph/test_server.py
@@ -14,6 +14,7 @@
 from marvia.auth import AuthError
 from marvia.graph.main import build_main_graph
 from marvia.server import build_app
+from marvia.watch import WatchDeps
 
 TOKENS = {"tok-a": "user-a", "tok-b": "user-b"}
 TWO = [{"label": "부산", "description": "부산항 기준"}, {"label": "인천", "description": "인천항 기준"}]
@@ -210,3 +211,21 @@
     ]
     values = {"evidence": [dict(evidence[0], unit_id=f"u{i}", source_url=url) for i, url in enumerate(urls)]}
     assert [e["source_url"] for e in screen_view(values)["evidence"]] == [urls[0], None, None, None]
+
+
+def test_an_approval_card_shows_real_numbers_but_the_model_gets_tokens_back(agent_deps):
+    inputs, added = Inputs(), []
+    watch = WatchDeps(add=lambda *row: added.append(row), news=lambda user: [], ack=lambda user, ids: None)
+    steps = (say("watch_cargo", {"token": "[BL1]"}, 1), AIMessage(""))
+    deps = agent_deps(model=ToolModel(messages=iter(steps)), watch=watch)
+    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
+    # [왜] 그래프에 기록 콜백을 붙여 모델이 받은 글을 모두 본다
+    app = build_app(graph.with_config(callbacks=[inputs]), verify, web_origin="http://web.test")
+    client = TestClient(app)
+    card = run(client, body("t3", "DEMO0001 계속 지켜봐 줘"))[-1]["outcome"]["interrupts"][0]
+    assert card["reason"] == "approval" and card["metadata"]["actions"][0]["args"] == {"token": "DEMO0001"}
+    edit = {"type": "edit", "edited_action": {"name": "watch_cargo", "args": {"token": "DEMO0001"}}}
+    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"decisions": [edit]}}]
+    assert run(client, body("t3", resume=resume))[-1]["outcome"] == {"type": "success"}
+    assert added == [("user-a", "DEMO0001", "반입신고")]  # 다시 가린 [BL1]로 도구가 돌았다
+    assert not any("DEMO0001" in text for text in inputs.seen)  # 모델은 화면에서 온 실제 번호를 받지 않았다
```

```bash
uv run pytest -q tests/graph/test_resume.py tests/graph/test_server.py
```

Expected: FAIL `ImportError: cannot import name 'NEW_NUMBER' from 'marvia.graph.resume'`

- [ ] **Step 2: 코드**

```diff
--- a/src/marvia/graph/resume.py
+++ b/src/marvia/graph/resume.py
@@ -2,11 +2,14 @@
 
 하지 않는 일: 승인 여부 판단, 승인 카드 만들기(graph/agent.py), 질문(ask_user) 응답 정리.
 [주의] 읽지 못한 값은 승인으로 보지 않고 거절로 돌린다(실행하지 않는 쪽이 안전하다).
+remask_reply는 화면 서버가 재개하기 전에 승인 결정의 글을 다시 가린다 (done 1.4, 계획 4b Task 6).
 """
 
 from __future__ import annotations
 
 from typing import Any
+
+from marvia.identify.mask import mask_text
 
 UNREADABLE = {"type": "reject", "message": "승인 값을 읽지 못해 실행하지 않았어요"}
 
@@ -46,3 +49,43 @@
             for i, decision in enumerate(decisions)
         ]
     }
+
+
+NEW_NUMBER = {"type": "reject", "message": "고친 값에 이 대화에 없던 화물 번호가 있어 실행하지 않았어요"}
+REJECTED = "사용자가 거절했어요"
+
+
+def _remask(value: Any, mask_map: dict[str, str]) -> tuple[Any, bool]:
+    """값 안의 모든 글을 이 대화의 가림 표로 다시 가린다. 표에 없던 번호가 나왔는지도 돌려준다."""
+    if isinstance(value, str):
+        masked, grown = mask_text(value, mask_map)
+        return masked, len(grown) > len(mask_map)
+    if isinstance(value, dict):
+        pairs = {key: _remask(item, mask_map) for key, item in value.items()}
+        return {key: masked for key, (masked, _) in pairs.items()}, any(fresh for _, fresh in pairs.values())
+    if isinstance(value, list):
+        items = [_remask(item, mask_map) for item in value]
+        return [masked for masked, _ in items], any(fresh for _, fresh in items)
+    return value, False
+
+
+def remask_reply(reply: dict, mask_map: dict[str, str]) -> dict:
+    """approval_reply를 거친 승인 응답에서 고친 인자와 거절 글의 실제 번호를 이 대화의 토큰으로 바꾼다.
+
+    [왜] 화면은 토큰을 실제 번호로 되돌려 보인다. 사람이 고친 인자와 거절 글은 실제 번호를 담아 돌아오고,
+         승인 미들웨어는 고친 인자로 도구 호출 메시지를 바꾸고 거절 글을 도구 결과로 모델에 준다 (설계 12절).
+    [주의] 이 대화의 가림 표에 없던 번호는 새 토큰을 만들지 않는다. 고치기는 거절로,
+           거절 글은 정해 둔 글로 바꾼다.
+    """
+    decisions = []
+    for decision in reply["decisions"]:
+        if decision["type"] == "edit":
+            args, fresh = _remask(decision["edited_action"]["args"], mask_map)
+            edited = {**decision, "edited_action": {**decision["edited_action"], "args": args}}
+            decisions.append(dict(NEW_NUMBER) if fresh else edited)
+        elif decision["type"] == "reject":
+            message, fresh = _remask(decision["message"], mask_map)
+            decisions.append({**decision, "message": REJECTED if fresh else message})
+        else:
+            decisions.append(decision)
+    return {"decisions": decisions}
```

```diff
--- a/src/marvia/server.py
+++ b/src/marvia/server.py
@@ -52,7 +52,7 @@
 from marvia.db import read_pool
 from marvia.graph.live import agent_deps, live_memory
 from marvia.graph.main import build_main_graph
-from marvia.graph.resume import approval_reply
+from marvia.graph.resume import approval_reply, remask_reply
 from marvia.graph.state import merge_cargos, merge_evidence
 from marvia.graph.tools import SERVER_SURFACE
 from marvia.tools.rules import load_rules
@@ -155,8 +155,9 @@
         raw = raw if isinstance(raw, dict) else {}
         if "action_requests" in value:
             names = [request["name"] for request in value["action_requests"]]
-            # [왜] 모양이 틀린 결정은 거절로 바꾼다(approval_reply). 고친 인자 다시 가리기는 Task 5b
-            return Command(resume=approval_reply(raw, len(names), names))
+            # [왜] 모양을 본 뒤(approval_reply) 고친 인자·거절 글의 실제 번호를 이 대화의 토큰으로 다시 가린다
+            reply = approval_reply(raw, len(names), names)
+            return Command(resume=remask_reply(reply, state.values.get("mask_map", {})))
         choice = {key: raw[key] for key in CHOICE_KEYS if key in raw}
         if len(str(choice.get("custom", ""))) > max_text:
             raise Refused(422, "글이 너무 길어요")
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `671 passed`, 오류 0.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/graph/resume.py src/marvia/server.py tests/graph/test_resume.py tests/graph/test_server.py
git commit -m "fix(server): 승인 카드에서 돌아온 고친 인자·거절 글을 대화의 토큰으로 다시 가림 (done 1.4)"
```

---
### Task 6: 감시 끄기와 계정 삭제 (R-033, done 4.1)

**배울 것:** 감시 표의 번호는 암호문이라 같은 번호를 키가 있는 해시(`number_hash`)로 찾는다. `watch_events`는 `ON DELETE CASCADE`라 감시 줄을 지우면 그 변화 기록도 지워진다. 감시를 끄는 일도 남는 일이라 `approval.always_ask`에 넣는다. 계정 삭제는 감시(`forget_user`), 장기 기억(Store의 `("users", uid, "items"|"prefs")`), 대화 기록(서버가 `uid/`로 시작하는 thread 키로 저장한 `checkpoints`·`checkpoint_blobs`·`checkpoint_writes`)을 함께 지운다. 표 이름은 코드 안 상수지만 SQL 조립은 `psycopg.sql.Identifier`로 한다.

#### 커밋 6a: feat(graph): 감시를 끄는 unwatch_cargo 도구 (승인 뒤)

**Files:**
- Modify: `src/marvia/watch.py`, `src/marvia/graph/tools.py`, `rules/agent.yaml`
- Test: `tests/test_watch.py`, `tests/graph/test_agent.py`

**Interfaces:**
- Produces: `marvia.watch.remove_watch(conn, keys, user, number) -> int`, `WatchDeps.remove: Callable[[str, str], int] | None = None`(있으면 `unwatch_cargo` 도구가 생긴다), `live_watch`가 `remove`를 채운다

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/test_watch.py
+++ b/tests/test_watch.py
@@ -16,6 +16,7 @@
     forget_user,
     number_hash,
     recheck,
+    remove_watch,
     take_news,
     watch_keys,
 )
@@ -144,6 +145,18 @@
     assert forget_user(db, "nobody") == 0
 
 
+def test_remove_watch_deletes_one_cargo_and_its_events_for_that_user_only(db, keys):
+    # [왜] R-033: 감시를 끄면 그 화물의 줄과 변화 기록이 남지 않는다. 같은 번호의 남의 감시는 그대로다
+    add_watch(db, keys, "u1", "DEMO0001", "반입신고")
+    add_watch(db, keys, "u1", "DEMO0002", "반입신고")
+    add_watch(db, keys, "u2", "DEMO0001", "반입신고")
+    recheck(db, keys, cleared)
+    assert remove_watch(db, keys, "u1", "DEMO0001") == 1
+    assert [n["number"] for n in take_news(db, keys, "u1")] == ["DEMO0002"]  # 지운 화물의 변화도 사라졌다
+    assert [n["number"] for n in take_news(db, keys, "u2")] == ["DEMO0001"]
+    assert remove_watch(db, keys, "u1", "DEMO0001") == 0  # 이미 지웠다
+
+
 def test_watch_keys_repr_hides_hash_key():
     secret = Fernet.generate_key().decode()
     assert repr(derive_key(secret, HASH_INFO)) not in repr(
```

```diff
--- a/tests/graph/test_agent.py
+++ b/tests/graph/test_agent.py
@@ -1464,3 +1464,26 @@
     server_graph = graph.with_config(configurable={"surface": "server"})
     with pytest.raises(MissingUser):
         server_graph.invoke({"text": "수입신고 기한?"}, {"configurable": {"thread_id": "no-user"}})
+
+
+def test_unwatching_a_cargo_waits_for_approval_and_removes_it_server_side(agent_deps):
+    # [왜] R-033: 감시를 끄는 일도 남는 일이라 승인 뒤에만 한다. 실제 번호는 서버의 감시 표에서 찾는 데만 쓴다
+    from marvia.watch import WatchDeps
+
+    removed: list[tuple[str, str]] = []
+    watch = WatchDeps(
+        add=lambda *row: None,
+        news=lambda user: [],
+        ack=lambda user, ids: None,
+        remove=lambda user, number: removed.append((user, number)) or 1,
+    )
+    ask = say(("unwatch_cargo", {"token": "[BL1]"}))
+    graph = agent_graph(agent_deps, ask, say(), permission_mode="auto", watch=watch)
+    out = graph.invoke({"text": "DEMO0001 그만 지켜봐 줘"}, cfg("uw1"))
+    # auto여도 묻는다. 카드에도 토큰만 있다
+    assert out["__interrupt__"][0].value["action_requests"][0]["args"] == {"token": "[BL1]"}
+    assert removed == []  # 승인 전에는 지우지 않는다
+    out = graph.invoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg("uw1"))
+    assert removed == [("local", "DEMO0001")]
+    assert "DEMO0001 감시 목록에서 뺌" in out["answer"]  # 화면 답에는 되돌린 번호, 공책에는 토큰
+    assert "DEMO0001" not in all_text(graph.get_state(cfg("uw1")).values)
```

```bash
uv run pytest -q tests/test_watch.py tests/graph/test_agent.py -k "remove_watch or unwatching"
```

Expected: FAIL `ImportError: cannot import name 'remove_watch' from 'marvia.watch'`

- [ ] **Step 2: 코드**

```diff
--- a/src/marvia/watch.py
+++ b/src/marvia/watch.py
@@ -66,6 +66,8 @@
     # 사용자 → 아직 보이지 않은 변화 [{"id", "number", "old_stage", "new_stage"}]. 꺼내기만 한다
     news: Callable[[str], list[dict]]
     ack: Callable[[str, list[int]], None]  # (사용자, 변화 id들) → 답에 보인 변화를 본 것으로 표시
+    # (사용자, 실제 번호) → 그 화물을 감시 목록에서 지우고 지운 수. 없으면 unwatch_cargo 도구도 없다 (R-033)
+    remove: Callable[[str, str], int] | None = None
 
 
 def add_watch(conn: psycopg.Connection, keys: WatchKeys, user: str, number: str, stage: str) -> None:
@@ -155,10 +157,26 @@
         raise
 
 
+def remove_watch(conn: psycopg.Connection, keys: WatchKeys, user: str, number: str) -> int:
+    """사용자의 감시 목록에서 화물 하나를 지운다. 그 변화 기록도 함께 지워진다. 지운 줄 수를 돌려준다."""
+    try:
+        # [왜] 번호는 암호문이라 같은 번호를 해시로 찾는다(add_watch의 UNIQUE와 같은 열).
+        #      watch_events는 ON DELETE CASCADE라 그 화물의 변화 기록도 함께 지워진다
+        deleted = conn.execute(
+            "DELETE FROM watches WHERE user_id = %s AND number_hash = %s", (user, number_hash(keys, number))
+        ).rowcount
+        conn.commit()
+    except psycopg.Error:
+        # [왜] 실패한 트랜잭션이 남으면 같은 연결의 다음 질의가 모두 죽는다. 되돌린 뒤 다시 던진다
+        conn.rollback()
+        raise
+    return deleted
+
+
 def forget_user(conn: psycopg.Connection, user: str) -> int:
     """사용자의 감시 목록과 변화 기록을 모두 지우고 지운 감시 수를 돌려준다.
 
-    계정 삭제용이다 (설계 8절). 화물 하나만 감시를 끄는 기능은 화면과 함께 온다 (done.md 4.1).
+    계정 삭제용이다 (설계 8절). 화물 하나만 끄는 일은 remove_watch(unwatch_cargo 도구)가 한다.
     """
     try:
         # [왜] watch_events는 ON DELETE CASCADE라 감시 줄을 지우면 변화 기록도 함께 지워진다
@@ -177,4 +195,5 @@
         add=lambda user, number, stage: add_watch(conn, keys, user, number, stage),
         news=lambda user: take_news(conn, keys, user),
         ack=lambda user, ids: ack_news(conn, user, ids),
+        remove=lambda user, number: remove_watch(conn, keys, user, number),
     )
```

```diff
--- a/src/marvia/graph/tools.py
+++ b/src/marvia/graph/tools.py
@@ -375,7 +375,7 @@
     law_tools = [search_law] + ([get_provision] if provision else [])
     extra = [_research_tool(model, law_tools, today)] if model is not None else []
     extra += [_official_tool(web)] if web is not None else []
-    extra += [_watch_tool(watch)] if watch is not None else []
+    extra += _watch_tools(watch) if watch is not None else []
     tools = [
         search_law,
         calc_deadlines,
@@ -488,8 +488,8 @@
     return official_lookup
 
 
-def _watch_tool(watch: WatchDeps):
-    """화물을 감시 목록에 넣는 도구 watch_cargo를 만든다 (계획 3d). 승인 뒤에만 돈다(approval.always_ask)."""
+def _watch_tools(watch: WatchDeps) -> list:
+    """감시 목록 도구: watch_cargo(계획 3d), remove가 있으면 unwatch_cargo(R-033). 둘 다 승인 뒤에만 돈다."""
 
     @tool
     def watch_cargo(token: str, runtime: ToolRuntime) -> Command:
@@ -523,4 +523,30 @@
             actions=[f"{token} 감시 목록에 넣음"],
         )
 
-    return watch_cargo
+    if watch.remove is None:
+        return [watch_cargo]
+    remove = watch.remove
+
+    @tool
+    def unwatch_cargo(token: str, runtime: ToolRuntime) -> Command:
+        """Remove a cargo token such as [BL1] from the user's watch list, with its recorded changes. Use it
+        only when the user asks to stop watching a cargo. Needs the user's approval.
+        """
+        number = runtime.state.get("mask_map", {}).get(token)
+        if number is None:
+            return _reply(runtime, f"{token}: 모르는 토큰이에요")
+        try:
+            # [주의] 실제 번호는 서버의 감시 표에서 찾는 데만 쓴다. 모델에게 주는 글은 토큰뿐이다 (설계 12절)
+            removed = remove(user_of(runtime.config), number)
+        except psycopg.Error as error:
+            name = error_name(error)
+            return _reply(
+                runtime,
+                f"감시 목록 지우기 실패: {name}",
+                failed_tools=[{"tool": "unwatch_cargo", "message": name}],
+            )
+        if not removed:
+            return _reply(runtime, f"{token}은 감시 목록에 없어요.")
+        return _reply(runtime, f"{token}을 감시 목록에서 뺐어요.", actions=[f"{token} 감시 목록에서 뺌"])
+
+    return [watch_cargo, unwatch_cargo]
```

```diff
--- a/rules/agent.yaml
+++ b/rules/agent.yaml
@@ -53,7 +53,7 @@
 approval:
   ask: [] # 권한 모드가 ask일 때만 묻는 도구용. 지금은 없다
   # 장기 기억과 감시 목록에 쓰는 도구는 auto에서도 늘 묻는다 (설계 8절·12절: 남는 일은 승인 뒤에만)
-  always_ask: [save_item_card, save_preference, watch_cargo]
+  always_ask: [save_item_card, save_preference, watch_cargo, unwatch_cargo]
 
 # 장기 기억 저장 기준 (설계 8절). 품목 카드 이름은 짧은 품목 이름만 받는다
 memory:
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `673 passed`, 오류 0.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/watch.py src/marvia/graph/tools.py rules/agent.yaml tests/test_watch.py tests/graph/test_agent.py
git commit -m "feat(graph): 감시 목록에서 화물을 빼는 unwatch_cargo를 승인 뒤에만 돌림 (R-033)"
```

#### 커밋 6b: feat(server): 계정 삭제가 감시·기억·대화 기록을 지움

**Files:**
- Modify: `src/marvia/server.py`
- Test: `tests/graph/test_server.py`

**Interfaces:**
- Produces: `marvia.server.forget_account(conn, store, user) -> None`, `build_app(graph, verify, *, web_origin, forget: Callable[[str], None])`, `DELETE /account`(204, 로그인 없으면 401)

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_server.py
+++ b/tests/graph/test_server.py
@@ -3,18 +3,23 @@
 import json
 import threading
 
+import psycopg
 import pytest
+from cryptography.fernet import Fernet
 from langchain_core.callbacks import BaseCallbackHandler
 from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
 from langchain_core.messages import AIMessage
 from langgraph.checkpoint.memory import InMemorySaver
 from langgraph.store.memory import InMemoryStore
+from psycopg.conninfo import make_conninfo
 from starlette.testclient import TestClient
 
 from marvia.auth import AuthError
+from marvia.config import Settings
+from marvia.graph.live import live_memory
 from marvia.graph.main import build_main_graph
-from marvia.server import build_app
-from marvia.watch import WatchDeps
+from marvia.server import build_app, forget_account
+from marvia.watch import WatchDeps, add_watch, watch_keys
 
 TOKENS = {"tok-a": "user-a", "tok-b": "user-b"}
 TWO = [{"label": "부산", "description": "부산항 기준"}, {"label": "인천", "description": "인천항 기준"}]
@@ -48,7 +53,7 @@
     """가짜 모델로 만든 그래프와 그 그래프를 띄운 시험 클라이언트."""
     deps = agent_deps(model=ToolModel(messages=iter(messages)), **changes)
     graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
-    app = build_app(graph, verify, web_origin="http://web.test")
+    app = build_app(graph, verify, web_origin="http://web.test", forget=lambda user: None)
     return graph, TestClient(app)
 
 
@@ -220,7 +225,7 @@
     deps = agent_deps(model=ToolModel(messages=iter(steps)), watch=watch)
     graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
     # [왜] 그래프에 기록 콜백을 붙여 모델이 받은 글을 모두 본다
-    app = build_app(graph.with_config(callbacks=[inputs]), verify, web_origin="http://web.test")
+    app = build_app(graph.with_config(callbacks=[inputs]), verify, web_origin="http://web.test", forget=print)
     client = TestClient(app)
     card = run(client, body("t3", "DEMO0001 계속 지켜봐 줘"))[-1]["outcome"]["interrupts"][0]
     assert card["reason"] == "approval" and card["metadata"]["actions"][0]["args"] == {"token": "DEMO0001"}
@@ -229,3 +234,31 @@
     assert run(client, body("t3", resume=resume))[-1]["outcome"] == {"type": "success"}
     assert added == [("user-a", "DEMO0001", "반입신고")]  # 다시 가린 [BL1]로 도구가 돌았다
     assert not any("DEMO0001" in text for text in inputs.seen)  # 모델은 화면에서 온 실제 번호를 받지 않았다
+
+
+def test_account_deletion_forgets_watches_memory_and_only_that_users_threads(agent_deps, db):
+    # [왜] R-033: 계정을 지우면 감시 목록, 장기 기억, 그 사람의 대화 기록(체크포인트)이 남지 않는다.
+    #      남의 것은 그대로다
+    schema = db.execute("SELECT current_schema()").fetchone()[0]
+    db.commit()
+    url = make_conninfo(Settings().database_url, options=f"-c search_path={schema},public")
+    secret = Fernet.generate_key().decode()  # [왜] 시험 안에서 만든 키. 저장소의 키를 쓰지 않는다
+    add_watch(db, watch_keys(secret), "user-a", "DEMO0001", "반입신고")
+    add_watch(db, watch_keys(secret), "user-b", "DEMO0002", "반입신고")
+    with live_memory(url, secret) as (saver, store), psycopg.connect(url, autocommit=True) as conn:
+        deps = agent_deps(model=ToolModel(messages=iter([AIMessage(""), AIMessage("")])))
+        graph = build_main_graph(deps, saver, loop="agent", store=store)
+        forget = lambda user: forget_account(conn, store, user)  # noqa: E731
+        client = TestClient(build_app(graph, verify, web_origin="http://web.test", forget=forget))
+        run(client, body("t1", "DEMO0001 언제까지?"), token="tok-a")
+        run(client, body("t1", "DEMO0002 언제까지?"), token="tok-b")
+        store.put(("users", "user-a", "items"), "고추", {"name": "고추"})
+        store.put(("users", "user-a", "prefs"), "depth", {"depth": "짧게"})
+        store.put(("users", "user-b", "items"), "쌀", {"name": "쌀"})
+        assert client.delete("/account").status_code == 401
+        assert client.delete("/account", headers={"Authorization": "Bearer tok-a"}).status_code == 204
+        threads = {row[0] for row in conn.execute("SELECT DISTINCT thread_id FROM checkpoints")}
+        assert threads == {"user-b/t1"}
+        assert store.search(("users", "user-a")) == []
+        assert [item.key for item in store.search(("users", "user-b", "items"))] == ["쌀"]
+    assert db.execute("SELECT user_id FROM watches").fetchall() == [("user-b",)]
```

```bash
uv run pytest -q tests/graph/test_server.py
```

Expected: FAIL `ImportError: cannot import name 'forget_account' from 'marvia.server'`

- [ ] **Step 2: 코드**

```diff
--- a/src/marvia/server.py
+++ b/src/marvia/server.py
@@ -37,7 +37,9 @@
 )
 from ag_ui.core import Interrupt as CardInterrupt
 from ag_ui.encoder import EventEncoder
+from langgraph.store.base import BaseStore
 from langgraph.types import Command
+from psycopg import sql
 from pydantic import ValidationError
 from starlette.applications import Starlette
 from starlette.middleware import Middleware
@@ -57,6 +59,7 @@
 from marvia.graph.tools import SERVER_SURFACE
 from marvia.tools.rules import load_rules
 from marvia.view import interrupt_card, screen_view
+from marvia.watch import forget_user
 
 # [왜] 화면이 정하는 thread id는 이름 공간 안의 이름일 뿐이다.
 #      서버가 "사용자/이름"으로 묶어 남의 대화에 닿지 못한다
@@ -194,8 +197,8 @@
         stop.set()
 
 
-def build_app(graph, verify: Verify, *, web_origin: str) -> Starlette:
-    """화면 서버 앱. graph는 컴파일한 메인 그래프, verify는 auth의 토큰 확인 함수."""
+def build_app(graph, verify: Verify, *, web_origin: str, forget: Callable[[str], None]) -> Starlette:
+    """화면 서버 앱. graph는 컴파일한 메인 그래프, verify는 auth의 토큰 확인 함수, forget은 계정 삭제."""
     # [왜] 이 앱이 부르는 그래프는 user_id 없이 사용자 데이터에 닿으면 멈춘다 (tools.user_of, R-048)
     graph = graph.with_config(configurable={"surface": SERVER_SURFACE})
     running: set[str] = set()
@@ -231,6 +234,14 @@
         stream = _sse(events, stop, lambda: running.discard(key))
         return StreamingResponse(stream, media_type=EventEncoder().get_content_type(), headers=SSE_HEADERS)
 
+    async def delete_account(request: Request) -> Response:
+        try:
+            user = user_from_header(request.headers.get("authorization"), verify)
+        except AuthError as error:
+            return JSONResponse({"error": str(error)}, status_code=error.status)
+        await anyio.to_thread.run_sync(forget, user)
+        return Response(status_code=204)
+
     async def health(request: Request) -> Response:
         return JSONResponse({"ok": True})
 
@@ -246,9 +257,24 @@
     ]
     routes = [
         Route("/agui", run, methods=["POST"]),
+        Route("/account", delete_account, methods=["DELETE"]),
         Route("/health", health, methods=["GET"]),
     ]
     return Starlette(routes=routes, middleware=middleware)
+
+
+def forget_account(conn: psycopg.Connection, store: BaseStore, user: str) -> None:
+    """계정 삭제 (설계 8절, R-033): 감시 목록과 변화, 장기 기억(품목 카드·설명 깊이), 대화 기록을 지운다."""
+    forget_user(conn, user)
+    for namespace in (("users", user, "items"), ("users", user, "prefs")):
+        while found := store.search(namespace, limit=100):
+            for item in found:
+                store.delete(item.namespace, item.key)
+    prefix = f"{user}/"  # [왜] 서버는 대화를 "사용자/이름"으로 저장한다(build_app). 같은 앞머리만 지운다
+    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
+        query = sql.SQL("DELETE FROM {} WHERE left(thread_id, %s) = %s").format(sql.Identifier(table))
+        conn.execute(query, (len(prefix), prefix))
+    conn.commit()
 
 
 def main() -> None:
@@ -263,14 +289,19 @@
     with (
         live_memory(url, settings.data_key.get_secret_value()) as (saver, store),
         read_pool(url) as pool,
-        # [왜] 감시 목록은 따로 autocommit 연결을 쓴다 (R-041)
+        # [왜] 감시 목록·계정 삭제는 따로 autocommit 연결을 쓴다 (R-041)
         psycopg.connect(url, autocommit=True) as watch_conn,
     ):
         deps = agent_deps(settings, pool, watch_conn)
         graph = build_main_graph(
             deps, saver, loop=settings.loop, store=store, permission_mode=settings.permission_mode
         )
-        app = build_app(graph, verify, web_origin=settings.web_origin)
+        app = build_app(
+            graph,
+            verify,
+            web_origin=settings.web_origin,
+            forget=lambda user: forget_account(watch_conn, store, user),
+        )
         # [주의] 컨테이너 안에서는 모든 주소에서 듣는다. 이 컴퓨터에서는 compose가 127.0.0.1로만 연다
         uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
 
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `674 passed`, 오류 0.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/server.py tests/graph/test_server.py
git commit -m "feat(server): 계정 삭제가 감시·장기 기억·그 사용자의 대화 기록을 지움 (R-033)"
```

바깥 메시지 발송 도구는 만들지 않는다(T0 판정 줄). done 1.4에 그 이유를 적는다(T11).

---
### Task 7a: 화면 뼈대, 채팅, AG-UI 스트림 (done 4.1, 결정 D4·D5)

**배울 것:** Next.js App Router에서 `app/layout.tsx`는 모든 쪽의 틀이고 `app/page.tsx`가 `/` 쪽이다. 맨 위에 `"use client"`를 둔 쪽은 브라우저에서 돌아 `useState`·`fetch`를 쓴다. SSE는 `EventSource`가 아니라 `fetch`의 본문 스트림으로 읽는다(EventSource는 POST와 `Authorization` 머리글을 못 보낸다). 조각이 이벤트 중간에서 끊길 수 있어 빈 줄(`\n\n`)까지 버퍼에 모은다. 한글 입력기는 글자를 조합하는 동안 Enter를 "조합 확정"에 쓰므로 `isComposing`일 때는 보내지 않는다. `crypto.randomUUID`는 https·localhost에서만 있어서 id는 직접 만든다(e2e 망은 `http://web-e2e`). npm 설치·빌드는 모두 `node:22` 컨테이너 안에서 한다.

**Files:**
- Create: `web/package.json`, `web/package-lock.json`, `web/.npmrc`, `web/.gitignore`, `web/tsconfig.json`, `web/next.config.ts`, `web/app/layout.tsx`, `web/app/globals.css`, `web/app/page.tsx`, `web/lib/agui.ts`, `web/lib/auth.ts`

**Interfaces:**
- Consumes: 서버 약속(T5a): `POST {API}/agui`, SSE 이벤트 모양
- Produces: `web/lib/agui.ts`의 `runTurn(apiUrl, token, {threadId, text? | resume?}, onEvent)`, 타입 `View`, `Card`, `ChoiceCard`, `ApprovalCard`, `AgUiEvent`, `EMPTY_VIEW`, `newId()`. `web/lib/auth.ts`의 `AUTH_MODE`, `currentToken()`, `signIn(devToken?)`, `signOut()`
- 환경 값: `NEXT_PUBLIC_API_URL`(기본 `http://localhost:8080`), `NEXT_PUBLIC_AUTH`(`dev`|`supabase`)

#### 커밋 7a-1: feat(web): Next.js 뼈대 (8파일)

- [ ] **Step 1: 파일**: `web/package.json`

```json
{
  "name": "marvia-web",
  "version": "2.0.0",
  "private": true,
  "scripts": {
    "dev": "next dev --port 3000",
    "build": "next build",
    "start": "next start --port 3000",
    "typecheck": "tsc --noEmit"
  },
  "engines": {
    "node": ">=22.12.0"
  },
  "dependencies": {
    "@fontsource-variable/noto-sans-kr": "5.3.1",
    "next": "16.4.3",
    "react": "19.3.1",
    "react-dom": "19.3.1"
  },
  "devDependencies": {
    "@types/node": "22.20.5",
    "@types/react": "19.3.0",
    "@types/react-dom": "19.3.0",
    "typescript": "5.9.3"
  }
}
```

`web/.npmrc`:

```ini
save-exact=true
fund=false
audit=false
```

`web/.gitignore`:

```text
node_modules/
.next/
next-env.d.ts
test-results/
playwright-report/
```

`web/tsconfig.json` (Next 16이 빌드 때 `.next/dev/types/**/*.ts`를 더하라고 하므로 미리 넣는다 [실측 11-07]):

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "react-jsx",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts", ".next/dev/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

`web/next.config.ts`:

```ts
// 화면 설정 (설계 10절, 계획 4b Task 7). standalone: Docker 실행 단계에 필요한 파일만 .next/standalone에 모은다
import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
};

export default config;
```

`web/app/layout.tsx`:

```tsx
// 화면 틀 (설계 10절). 한글 글꼴은 패키지에서 직접 싣는다(빌드·e2e가 바깥 글꼴 서버에 기대지 않는다).
import "@fontsource-variable/noto-sans-kr";
import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Marvia", description: "수입 화물과 법령 근거를 함께 보는 에이전트" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
```

`web/app/globals.css`:

```css
/* 화면 모양 (계획 4b Task 7). 글자 대비는 WCAG AA(4.5:1) 이상인 색만 쓴다 (axe 검사) */
:root {
  --ink: #1c1f24;
  --muted: #4a5260;
  --line: #d4d9e1;
  --paper: #ffffff;
  --soft: #f3f5f8;
  --accent: #0b5cad;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--soft);
  color: var(--ink);
  font-family: "Noto Sans KR Variable", system-ui, sans-serif;
  line-height: 1.6;
}

main {
  max-width: 760px;
  margin: 0 auto;
  padding: 16px;
  display: grid;
  gap: 12px;
}

h1 {
  font-size: 1.5rem;
  margin: 0;
}

h2 {
  font-size: 1.1rem;
  margin: 0 0 8px;
}

h3 {
  font-size: 1rem;
  margin: 0 0 4px;
}

.panel,
.card {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px 16px;
}

.card {
  border-color: var(--accent);
}

.row {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}

.text {
  white-space: pre-wrap;
  margin: 4px 0;
}

.meta,
.hint {
  color: var(--muted);
  font-size: 0.9rem;
}

.hint {
  display: block;
}

.chat {
  list-style: none;
  padding: 0;
  margin: 0;
}

.chat li[data-role="user"] .who {
  color: var(--accent);
}

.who {
  font-weight: 700;
}

.plan li[data-status="in_progress"] {
  font-weight: 700;
}

.badge {
  display: inline-block;
  min-width: 4em;
  color: var(--muted);
}

.options {
  display: grid;
  gap: 8px;
  margin-bottom: 8px;
}

button {
  font: inherit;
  padding: 8px 14px;
  border-radius: 6px;
  border: 1px solid var(--accent);
  background: var(--accent);
  color: #ffffff;
  cursor: pointer;
  text-align: left;
}

button.secondary,
.options button {
  background: var(--paper);
  color: var(--accent);
}

button:disabled {
  background: #6b7380;
  border-color: #6b7380;
  color: #ffffff;
  cursor: default;
}

input,
textarea,
select {
  font: inherit;
  padding: 8px;
  border: 1px solid #8a93a1;
  border-radius: 6px;
  width: 100%;
}

input[type="radio"] {
  width: auto;
}

label.block {
  display: block;
  margin-top: 8px;
}

fieldset {
  border: 1px solid var(--line);
  border-radius: 6px;
  margin: 0 0 8px;
}

.ask {
  display: grid;
  gap: 8px;
}

dl {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 2px 12px;
  margin: 4px 0;
}

dt {
  color: var(--muted);
}

dd {
  margin: 0;
}

a {
  color: var(--accent);
}
```

`web/app/page.tsx` (빈 쪽):

```tsx
// Marvia 화면 한 쪽 (설계 10절). 다음 커밋에서 채팅과 스트림을 붙인다
export default function Home() {
  return (
    <main>
      <h1>Marvia</h1>
    </main>
  );
}
```

- [ ] **Step 2: 잠금 파일**: 명령 C.

- [ ] **Step 3: 확인**: 명령 B.

Expected: 마지막 줄 `web-ok`. (`next-env.d.ts`·`.next/`는 `.gitignore`에 있다.)

- [ ] **Step 4: 커밋**

```bash
git add web/package.json web/package-lock.json web/.npmrc web/.gitignore web/tsconfig.json web/next.config.ts web/app/layout.tsx web/app/globals.css web/app/page.tsx
git commit -m "feat(web): Next.js 화면 뼈대 (npm, 정확한 버전, 한글 글꼴)"
```

#### 커밋 7a-2: feat(web): 채팅과 AG-UI 스트림 읽기, 개발 로그인

- [ ] **Step 1: 파일**: `web/lib/agui.ts` (새 파일)

```ts
// AG-UI 한 차례 부르기와 이벤트 모양 (설계 10절, 계획 4b Task 7).
// 서버(src/marvia/server.py)가 ag-ui-protocol로 보내는 SSE를 fetch 스트림으로 읽는다.
// [왜] @ag-ui/client는 rxjs·zod·proto를 끌어온다. 화면이 쓰는 이벤트는 일곱 가지라 직접 읽는다 (계획 4b 결정 D5).
// 하지 않는 일: 화면 그리기, 로그인(lib/auth.ts).

export type PlanItem = { content: string; status: "pending" | "in_progress" | "completed" };
export type Reading = { token: string; number: string; kind: string };
export type Cargo = {
  number: string;
  stage: string | null;
  stage_at: string | null;
  port: string | null;
  vessel: string | null;
  source: string | null;
  fetched_at: string | null;
  error: string | null;
};
export type EvidenceUnit = {
  unit_id: string;
  heading: string;
  effective: string;
  text: string;
  source_url: string | null;
};
export type View = { plan: PlanItem[]; reading: Reading[]; cargos: Cargo[]; evidence: EvidenceUnit[] };
export type ChoiceCard = {
  kind: "choice";
  question: string;
  options: { label: string; description: string }[];
  recommended: number;
  timeout_s: number;
};
export type ApprovalAction = {
  name: string;
  args: Record<string, unknown>;
  description: string;
  allowed: string[];
};
export type ApprovalCard = { kind: "approval"; actions: ApprovalAction[] };
export type Card = (ChoiceCard | ApprovalCard) & { id: string };

export type AgUiEvent =
  | { type: "RUN_STARTED"; threadId: string; runId: string }
  | { type: "STATE_SNAPSHOT"; snapshot: View }
  | { type: "TEXT_MESSAGE_START"; messageId: string }
  | { type: "TEXT_MESSAGE_CONTENT"; messageId: string; delta: string }
  | { type: "TEXT_MESSAGE_END"; messageId: string }
  | {
      type: "RUN_FINISHED";
      outcome?:
        | { type: "success" }
        | { type: "interrupt"; interrupts: { id: string; reason: string; metadata: ChoiceCard | ApprovalCard }[] };
    }
  | { type: "RUN_ERROR"; message: string; code?: string };

export const EMPTY_VIEW: View = { plan: [], reading: [], cargos: [], evidence: [] };

// [왜] crypto.randomUUID는 https·localhost에서만 있다. e2e 망(http://web-e2e)에서도 돌게 직접 만든다
export function newId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
}

type TurnInput = { threadId: string; text?: string; resume?: { interruptId: string; payload: unknown } };

// 한 차례를 보내고 이벤트마다 onEvent를 부른다. 서버가 거절하면(401·409·422) 상태 코드를 담아 던진다
export async function runTurn(
  apiUrl: string,
  token: string,
  input: TurnInput,
  onEvent: (event: AgUiEvent) => void,
): Promise<void> {
  // [주의] state·forwardedProps는 빈 값으로 보낸다. 서버도 읽지 않는다(계획 4b C7)
  const body = {
    threadId: input.threadId,
    runId: newId(),
    messages: input.text ? [{ id: newId(), role: "user", content: input.text }] : [],
    tools: [],
    context: [],
    state: {},
    forwardedProps: {},
    ...(input.resume
      ? { resume: [{ interruptId: input.resume.interruptId, status: "resolved", payload: input.resume.payload }] }
      : {}),
  };
  const response = await fetch(`${apiUrl}/agui`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream", authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    throw new Error(`서버가 요청을 받지 않았어요 (${response.status})`);
  }
  // SSE: "data: {json}" 줄들이 빈 줄로 나뉜다. 조각이 이벤트 중간에서 끊길 수 있어 버퍼에 모은다
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let end = buffer.indexOf("\n\n");
    while (end >= 0) {
      const chunk = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as AgUiEvent);
      }
      end = buffer.indexOf("\n\n");
    }
  }
}
```

`web/lib/auth.ts` (새 파일, 개발 로그인만. Supabase는 T7e):

```ts
// 화면 로그인 (설계 10절 로그인, 계획 4b Task 7). 토큰만 다루고 사용자 id는 서버가 토큰에서 꺼낸다.
// - dev: 이 컴퓨터·e2e에서 개발 토큰을 직접 넣는다. 탭을 닫으면 잊는다(sessionStorage).
// Supabase 로그인은 Task 7e에서 더한다.
// [주의] 토큰을 번들에 넣지 않는다. NEXT_PUBLIC_ 값은 주소와 공개 키뿐이다.

export const AUTH_MODE: "dev" | "supabase" = "dev";
const DEV_KEY = "marvia-dev-token";

export async function currentToken(): Promise<string | null> {
  return sessionStorage.getItem(DEV_KEY);
}

export async function signIn(devToken?: string): Promise<void> {
  if (devToken) sessionStorage.setItem(DEV_KEY, devToken);
}

export async function signOut(): Promise<void> {
  sessionStorage.removeItem(DEV_KEY);
}
```

`web/app/page.tsx` (빈 쪽을 바꾼다):

```tsx
"use client";
// Marvia 화면 한 쪽 (설계 10절): 채팅, 계획 진행, 이렇게 읽었어요, 선택지·승인 카드, 답과 근거, 화물 카드.
// 상태는 서버가 보낸 STATE_SNAPSHOT(허용 목록)과 답 글뿐이다. 서버에 state를 보내지 않는다.
import { useCallback, useEffect, useState } from "react";

import { type AgUiEvent, newId, runTurn } from "@/lib/agui";
import { AUTH_MODE, currentToken, signIn, signOut } from "@/lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
type Line = { role: "user" | "assistant"; text: string };

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [devToken, setDevToken] = useState("");
  const [threadId] = useState(newId);
  const [lines, setLines] = useState<Line[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    currentToken().then(setToken);
  }, []);

  const onEvent = useCallback((event: AgUiEvent) => {
    if (event.type === "TEXT_MESSAGE_CONTENT") setLines((old) => [...old, { role: "assistant", text: event.delta }]);
    if (event.type === "RUN_ERROR") setError(event.message);
  }, []);

  const turn = useCallback(
    async (input: { text?: string; resume?: { interruptId: string; payload: unknown } }) => {
      if (!token) return;
      setBusy(true);
      setError("");
      try {
        await runTurn(API_URL, token, { threadId, ...input }, onEvent);
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : "요청이 실패했어요");
      } finally {
        setBusy(false);
      }
    },
    [token, threadId, onEvent],
  );

  function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setLines((old) => [...old, { role: "user", text }]);
    setDraft("");
    turn({ text });
  }

  if (!token) {
    return (
      <main>
        <h1>Marvia</h1>
        {AUTH_MODE === "dev" ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              signIn(devToken).then(() => currentToken().then(setToken));
            }}
          >
            <label htmlFor="dev-token">개발 로그인 토큰</label>
            <div className="row">
              <input id="dev-token" type="password" value={devToken} onChange={(e) => setDevToken(e.target.value)} />
              <button type="submit">들어가기</button>
            </div>
          </form>
        ) : (
          <button type="button" onClick={() => signIn()}>
            구글로 로그인
          </button>
        )}
      </main>
    );
  }

  return (
    <main>
      <header className="row">
        <h1>Marvia</h1>
        <button type="button" className="secondary" onClick={() => signOut().then(() => setToken(null))}>
          로그아웃
        </button>
      </header>
      <section aria-labelledby="chat-title" className="panel">
        <h2 id="chat-title">대화</h2>
        <ol className="chat">
          {lines.map((line, i) => (
            <li key={i} data-role={line.role}>
              <span className="who">{line.role === "user" ? "나" : "Marvia"}</span>
              <p className="text">{line.text}</p>
            </li>
          ))}
        </ol>
        <p role="status" aria-live="polite" className="meta">
          {busy ? "답하는 중이에요" : ""}
        </p>
        {error ? <p role="alert">{error}</p> : null}
      </section>
      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <label htmlFor="question">질문이나 화물 단서 (B/L·화물관리번호)</label>
        <textarea
          id="question"
          rows={3}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            // [주의] 한글 조합 중 Enter는 글자를 확정하는 키다. 그때 보내면 마지막 글자가 남거나 두 번 간다
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button type="submit" disabled={busy || !draft.trim()}>
          보내기
        </button>
      </form>
    </main>
  );
}
```

- [ ] **Step 2: 확인**: 명령 B. Expected: `web-ok` [실측 11-07: 이 단계 `tsc --noEmit` 통과].

- [ ] **Step 3: 커밋**

```bash
git add web/lib/agui.ts web/lib/auth.ts web/app/page.tsx
git commit -m "feat(web): 채팅과 AG-UI 스트림 읽기, 개발 로그인"
```

---

### Task 7b: 계획 진행, "이렇게 읽었어요", 근거 패널 (done 4.1)

**배울 것:** 화면 상태는 서버가 보낸 `STATE_SNAPSHOT`을 그대로 바꿔 끼운다(합치지 않는다). 답과 조문은 글자로만 그린다(`dangerouslySetInnerHTML`을 쓰지 않는다: 법령 글과 답은 데이터다). 링크는 서버가 거른 뒤에도 화면에서 `https://www.law.go.kr/`로 시작할 때만 `href`로 만든다(`javascript:` 막기).

**Files:**
- Create: `web/components/Panels.tsx`
- Modify: `web/app/page.tsx`

- [ ] **Step 1: 파일**: `web/components/Panels.tsx`

```tsx
// 계획 진행, "이렇게 읽었어요", 근거 패널 (설계 10절). 값은 글자로만 그린다(dangerouslySetInnerHTML 쓰지 않음).
import type { EvidenceUnit, PlanItem, Reading } from "@/lib/agui";

const STATUS: Record<PlanItem["status"], string> = { pending: "대기", in_progress: "진행 중", completed: "끝" };

export function PlanList({ plan }: { plan: PlanItem[] }) {
  if (!plan.length) return null;
  return (
    <section aria-labelledby="plan-title" className="panel">
      <h2 id="plan-title">계획</h2>
      <ol className="plan">
        {plan.map((item, i) => (
          <li key={i} data-status={item.status}>
            <span className="badge">{STATUS[item.status]}</span> {item.content}
          </li>
        ))}
      </ol>
    </section>
  );
}

export function ReadingList({ reading }: { reading: Reading[] }) {
  if (!reading.length) return null;
  return (
    <section aria-labelledby="reading-title" className="panel">
      <h2 id="reading-title">이렇게 읽었어요</h2>
      <ul>
        {reading.map((r) => (
          <li key={r.token}>
            {r.kind} <strong>{r.number}</strong>
          </li>
        ))}
      </ul>
    </section>
  );
}

// [주의] 링크는 국가법령정보센터(https)만 만든다. 서버도 거르지만 화면에서 한 번 더 본다(javascript: 링크 막기)
function safeLink(url: string | null): string | null {
  return url && url.startsWith("https://www.law.go.kr/") ? url : null;
}

export function EvidencePanel({ evidence }: { evidence: EvidenceUnit[] }) {
  if (!evidence.length) return null;
  return (
    <section aria-labelledby="evidence-title" className="panel">
      <h2 id="evidence-title">근거</h2>
      {evidence.map((e) => {
        const link = safeLink(e.source_url);
        return (
          <article key={e.unit_id} className="evidence">
            <h3>{e.heading}</h3>
            <p className="meta">
              시행일 {e.effective} · {e.unit_id}
            </p>
            <p className="text">{e.text}</p>
            {link ? (
              <a href={link} target="_blank" rel="noopener noreferrer">
                원문 보기 (국가법령정보센터)
              </a>
            ) : null}
          </article>
        );
      })}
    </section>
  );
}
```

`web/app/page.tsx`:

```diff
--- a/web/app/page.tsx
+++ b/web/app/page.tsx
@@ -3,7 +3,8 @@
 // 상태는 서버가 보낸 STATE_SNAPSHOT(허용 목록)과 답 글뿐이다. 서버에 state를 보내지 않는다.
 import { useCallback, useEffect, useState } from "react";
 
-import { type AgUiEvent, newId, runTurn } from "@/lib/agui";
+import { EvidencePanel, PlanList, ReadingList } from "@/components/Panels";
+import { type AgUiEvent, EMPTY_VIEW, newId, runTurn, type View } from "@/lib/agui";
 import { AUTH_MODE, currentToken, signIn, signOut } from "@/lib/auth";
 
 const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
@@ -14,6 +15,7 @@
   const [devToken, setDevToken] = useState("");
   const [threadId] = useState(newId);
   const [lines, setLines] = useState<Line[]>([]);
+  const [view, setView] = useState<View>(EMPTY_VIEW);
   const [draft, setDraft] = useState("");
   const [busy, setBusy] = useState(false);
   const [error, setError] = useState("");
@@ -23,6 +25,7 @@
   }, []);
 
   const onEvent = useCallback((event: AgUiEvent) => {
+    if (event.type === "STATE_SNAPSHOT") setView(event.snapshot);
     if (event.type === "TEXT_MESSAGE_CONTENT") setLines((old) => [...old, { role: "assistant", text: event.delta }]);
     if (event.type === "RUN_ERROR") setError(event.message);
   }, []);
@@ -100,6 +103,9 @@
         </p>
         {error ? <p role="alert">{error}</p> : null}
       </section>
+      <PlanList plan={view.plan} />
+      <ReadingList reading={view.reading} />
+      <EvidencePanel evidence={view.evidence} />
       <form
         className="ask"
         onSubmit={(e) => {
```

- [ ] **Step 2: 확인**: 명령 B. Expected: `web-ok` [실측 11-07: `tsc` 통과].

- [ ] **Step 3: 커밋**

```bash
git add web/components/Panels.tsx web/app/page.tsx
git commit -m "feat(web): 계획 진행, 이렇게 읽었어요, 근거 패널"
```

장부에 확인점 줄을 남긴다: `CP2 (11-11): T5~T7b done? <yes/no, cut applied>`.

---

### Task 7c: 선택지 카드와 승인 카드 (done 4.1, 설계 6.3)

**배울 것:** 끼어들기 차례는 `RUN_FINISHED.outcome.type == "interrupt"`로 끝나고 카드는 `interrupts[0].metadata`에 있다. 답할 때는 같은 `threadId`로 `resume: [{interruptId, status: "resolved", payload}]`를 보낸다. 선택지 카드는 시간 제한(`timeout_s`)이 지나면 `{"timeout": true}`로 재개한다(그래프에는 시간 제한이 없다, 3c 판정). 카드 컴포넌트에 `key={card.id}`를 줘서 새 카드마다 상태를 새로 시작한다.

**Files:**
- Create: `web/components/ChoiceCardView.tsx`, `web/components/ApprovalCardView.tsx`
- Modify: `web/app/page.tsx`

- [ ] **Step 1: 파일**: `web/components/ChoiceCardView.tsx`

```tsx
"use client";
// 선택지 카드 (설계 6.3 질문 통로): 선택지, "기타" 직접 입력, 권장안으로 진행, 시간이 지나면 권장안으로 진행.
import { useEffect, useState } from "react";

import type { ChoiceCard } from "@/lib/agui";

type Reply = { selected: number } | { custom: string } | { timeout: true };

export function ChoiceCardView({ card, onReply }: { card: ChoiceCard; onReply: (reply: Reply) => void }) {
  const [custom, setCustom] = useState("");
  const [left, setLeft] = useState(card.timeout_s);

  // [왜] 그래프에는 시간 제한이 없다. 화면이 시간을 재고 {"timeout": true}로 재개한다(설계 6.3)
  useEffect(() => {
    if (left <= 0) {
      onReply({ timeout: true });
      return;
    }
    const timer = setTimeout(() => setLeft(left - 1), 1000);
    return () => clearTimeout(timer);
  }, [left, onReply]);

  return (
    <section aria-labelledby="choice-title" className="card">
      <h2 id="choice-title">{card.question}</h2>
      <div className="options">
        {card.options.map((option, i) => (
          <button key={i} type="button" onClick={() => onReply({ selected: i })}>
            {option.label}
            {i === card.recommended ? " (권장)" : ""}
            <span className="hint">{option.description}</span>
          </button>
        ))}
      </div>
      <label htmlFor="choice-custom">기타 (직접 입력)</label>
      <div className="row">
        <input id="choice-custom" value={custom} onChange={(e) => setCustom(e.target.value)} />
        <button type="button" disabled={!custom.trim()} onClick={() => onReply({ custom: custom.trim() })}>
          보내기
        </button>
      </div>
      <button type="button" className="secondary" onClick={() => onReply({ timeout: true })}>
        권장안으로 진행 ({left}초 뒤 자동)
      </button>
    </section>
  );
}
```

`web/components/ApprovalCardView.tsx`:

```tsx
"use client";
// 승인 카드 (설계 6.3 승인 통로): 할 일마다 승인·거절·고치기. 고치기는 도구별 칸만 연다.
// [왜] 자유 JSON 편집을 열면 모르는 인자가 그대로 도구에 간다. 서버가 고친 값을 다시 가리고 도구가 같은 검사를 한다
import { useState } from "react";

import type { ApprovalCard } from "@/lib/agui";

type Decision =
  | { type: "approve" }
  | { type: "reject"; message: string }
  | { type: "edit"; edited_action: { name: string; args: Record<string, unknown> } };

// 고칠 수 있는 도구와 칸. 모르는 도구는 승인·거절만 보인다
const EDITABLE: Record<string, { field: string; label: string; choices?: string[] }> = {
  save_preference: { field: "depth", label: "설명 깊이", choices: ["짧게", "보통", "자세히"] },
  save_item_card: { field: "name", label: "품목 이름" },
};

export function ApprovalCardView({
  card,
  onReply,
}: {
  card: ApprovalCard;
  onReply: (reply: { decisions: Decision[] }) => void;
}) {
  const [kinds, setKinds] = useState(card.actions.map(() => "approve"));
  const [values, setValues] = useState(card.actions.map((a) => String(a.args[EDITABLE[a.name]?.field] ?? "")));
  const [reasons, setReasons] = useState(card.actions.map(() => ""));
  const set = (list: string[], i: number, value: string) => list.map((old, j) => (j === i ? value : old));

  function send() {
    const decisions = card.actions.map((action, i): Decision => {
      if (kinds[i] === "reject") return { type: "reject", message: reasons[i] || "사용자가 거절했어요" };
      if (kinds[i] === "edit") {
        const field = EDITABLE[action.name].field;
        return { type: "edit", edited_action: { name: action.name, args: { ...action.args, [field]: values[i] } } };
      }
      return { type: "approve" };
    });
    onReply({ decisions });
  }

  return (
    <section aria-labelledby="approval-title" className="card">
      <h2 id="approval-title">승인이 필요해요</h2>
      {card.actions.map((action, i) => {
        const edit = EDITABLE[action.name] && action.allowed.includes("edit") ? EDITABLE[action.name] : null;
        return (
          <fieldset key={i}>
            <legend>{action.name}</legend>
            <p className="text">{action.description}</p>
            <label>
              <input type="radio" name={`d${i}`} checked={kinds[i] === "approve"} onChange={() => setKinds(set(kinds, i, "approve"))} />
              승인
            </label>
            <label>
              <input type="radio" name={`d${i}`} checked={kinds[i] === "reject"} onChange={() => setKinds(set(kinds, i, "reject"))} />
              거절
            </label>
            {edit ? (
              <label>
                <input type="radio" name={`d${i}`} checked={kinds[i] === "edit"} onChange={() => setKinds(set(kinds, i, "edit"))} />
                고치기
              </label>
            ) : null}
            {kinds[i] === "reject" ? (
              <label className="block">
                거절 이유 (선택)
                <input value={reasons[i]} onChange={(e) => setReasons(set(reasons, i, e.target.value))} />
              </label>
            ) : null}
            {edit && kinds[i] === "edit" ? (
              <label className="block">
                {edit.label}
                {edit.choices ? (
                  <select value={values[i]} onChange={(e) => setValues(set(values, i, e.target.value))}>
                    {edit.choices.map((choice) => (
                      <option key={choice}>{choice}</option>
                    ))}
                  </select>
                ) : (
                  <input value={values[i]} onChange={(e) => setValues(set(values, i, e.target.value))} />
                )}
              </label>
            ) : null}
          </fieldset>
        );
      })}
      <button type="button" onClick={send}>
        보내기
      </button>
    </section>
  );
}
```

`web/app/page.tsx`:

```diff
--- a/web/app/page.tsx
+++ b/web/app/page.tsx
@@ -3,8 +3,10 @@
 // 상태는 서버가 보낸 STATE_SNAPSHOT(허용 목록)과 답 글뿐이다. 서버에 state를 보내지 않는다.
 import { useCallback, useEffect, useState } from "react";
 
+import { ApprovalCardView } from "@/components/ApprovalCardView";
+import { ChoiceCardView } from "@/components/ChoiceCardView";
 import { EvidencePanel, PlanList, ReadingList } from "@/components/Panels";
-import { type AgUiEvent, EMPTY_VIEW, newId, runTurn, type View } from "@/lib/agui";
+import { type AgUiEvent, type Card, EMPTY_VIEW, newId, runTurn, type View } from "@/lib/agui";
 import { AUTH_MODE, currentToken, signIn, signOut } from "@/lib/auth";
 
 const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
@@ -16,6 +18,7 @@
   const [threadId] = useState(newId);
   const [lines, setLines] = useState<Line[]>([]);
   const [view, setView] = useState<View>(EMPTY_VIEW);
+  const [card, setCard] = useState<Card | null>(null);
   const [draft, setDraft] = useState("");
   const [busy, setBusy] = useState(false);
   const [error, setError] = useState("");
@@ -28,6 +31,10 @@
     if (event.type === "STATE_SNAPSHOT") setView(event.snapshot);
     if (event.type === "TEXT_MESSAGE_CONTENT") setLines((old) => [...old, { role: "assistant", text: event.delta }]);
     if (event.type === "RUN_ERROR") setError(event.message);
+    if (event.type === "RUN_FINISHED" && event.outcome?.type === "interrupt") {
+      const pending = event.outcome.interrupts[0];
+      setCard({ ...pending.metadata, id: pending.id });
+    }
   }, []);
 
   const turn = useCallback(
@@ -35,6 +42,7 @@
       if (!token) return;
       setBusy(true);
       setError("");
+      setCard(null);
       try {
         await runTurn(API_URL, token, { threadId, ...input }, onEvent);
       } catch (failure) {
@@ -53,6 +61,13 @@
     setDraft("");
     turn({ text });
   }
+
+  const reply = useCallback(
+    (payload: unknown) => {
+      if (card) turn({ resume: { interruptId: card.id, payload } });
+    },
+    [card, turn],
+  );
 
   if (!token) {
     return (
@@ -103,6 +118,8 @@
         </p>
         {error ? <p role="alert">{error}</p> : null}
       </section>
+      {card?.kind === "choice" ? <ChoiceCardView key={card.id} card={card} onReply={reply} /> : null}
+      {card?.kind === "approval" ? <ApprovalCardView key={card.id} card={card} onReply={reply} /> : null}
       <PlanList plan={view.plan} />
       <ReadingList reading={view.reading} />
       <EvidencePanel evidence={view.evidence} />
```

- [ ] **Step 2: 확인**: 명령 B. Expected: `web-ok` [실측 11-07: `tsc` 통과].

- [ ] **Step 3: 커밋**

```bash
git add web/components/ChoiceCardView.tsx web/components/ApprovalCardView.tsx web/app/page.tsx
git commit -m "feat(web): 선택지 카드(기타·권장안·시간 제한)와 승인 카드(승인·고치기·거절)"
```

---

### Task 7d: 화물 카드 (done 4.1, 결정 D3)

**Files:**
- Create: `web/components/CargoCards.tsx`
- Modify: `web/app/page.tsx`

- [ ] **Step 1: 파일**: `web/components/CargoCards.tsx`

```tsx
// 화물 카드 (설계 10절): 통관 단계, 항구, 단계 시각, 출처와 조회 시각.
// [왜] ETA·등급은 선박 위치 조회와 함께 2차로 미뤘다(계획 4b 결정 D3). 빈 칸 대신 그렇다고 적는다.
import type { Cargo } from "@/lib/agui";

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "모름";
}

export function CargoCards({ cargos }: { cargos: Cargo[] }) {
  if (!cargos.length) return null;
  return (
    <section aria-labelledby="cargo-title" className="panel">
      <h2 id="cargo-title">화물</h2>
      {cargos.map((c) => (
        <article key={c.number} className="cargo">
          <h3>{c.number}</h3>
          {c.error ? (
            <p>조회하지 못했어요: {c.error}</p>
          ) : (
            <dl>
              <dt>통관 단계</dt>
              <dd>{c.stage}</dd>
              <dt>항구</dt>
              <dd>{c.port ?? "모름"}</dd>
              <dt>단계 시각</dt>
              <dd>{when(c.stage_at)}</dd>
              <dt>ETA·등급</dt>
              <dd>선박 위치 조회 뒤(2차)</dd>
            </dl>
          )}
          <p className="meta">
            출처 {c.source ?? "모름"} · 조회 {when(c.fetched_at)}
          </p>
        </article>
      ))}
    </section>
  );
}
```

`web/app/page.tsx`:

```diff
--- a/web/app/page.tsx
+++ b/web/app/page.tsx
@@ -4,6 +4,7 @@
 import { useCallback, useEffect, useState } from "react";
 
 import { ApprovalCardView } from "@/components/ApprovalCardView";
+import { CargoCards } from "@/components/CargoCards";
 import { ChoiceCardView } from "@/components/ChoiceCardView";
 import { EvidencePanel, PlanList, ReadingList } from "@/components/Panels";
 import { type AgUiEvent, type Card, EMPTY_VIEW, newId, runTurn, type View } from "@/lib/agui";
@@ -122,6 +123,7 @@
       {card?.kind === "approval" ? <ApprovalCardView key={card.id} card={card} onReply={reply} /> : null}
       <PlanList plan={view.plan} />
       <ReadingList reading={view.reading} />
+      <CargoCards cargos={view.cargos} />
       <EvidencePanel evidence={view.evidence} />
       <form
         className="ask"
```

- [ ] **Step 2: 확인**: 명령 B. Expected: `web-ok` [실측 11-07].

- [ ] **Step 3: 커밋**

```bash
git add web/components/CargoCards.tsx web/app/page.tsx
git commit -m "feat(web): 화물 카드(단계·항구·시각·출처, ETA·등급은 2차 표시)"
```

---

### Task 7e: Supabase 로그인 화면 (자를 순서 3)

**배울 것:** `createClient(주소, 공개 키)`로 만든 클라이언트의 `auth.signInWithOAuth({provider: "google", options: {redirectTo}})`가 구글 로그인으로 보내고, 돌아오면 `auth.getSession()`의 `session.access_token`이 서버가 확인할 ES256 JWT다. 공개(anon) 키는 비밀이 아니고, 서버가 서명·aud·iss·소유자 목록을 다시 본다. Supabase 프로젝트가 없어 브라우저에서 실제로 로그인해 보지는 못한다. 확인은 타입 검사와 빌드까지다.

**Files:**
- Modify: `web/lib/auth.ts`, `web/package.json`, `web/package-lock.json`

- [ ] **Step 1: 파일**: `web/package.json`의 dependencies에 `"@supabase/supabase-js": "2.118.0"`을 더하고(아래 diff) 잠금 파일을 다시 만든다(명령 C).

```diff
--- a/web/package.json
+++ b/web/package.json
@@ -13,6 +13,7 @@
   },
   "dependencies": {
     "@fontsource-variable/noto-sans-kr": "5.3.1",
+    "@supabase/supabase-js": "2.118.0",
     "next": "16.4.3",
     "react": "19.3.1",
     "react-dom": "19.3.1"
```

`web/lib/auth.ts`를 바꾼다:

```ts
// 화면 로그인 (설계 10절 로그인, 계획 4b Task 7). 토큰만 다루고 사용자 id는 서버가 토큰에서 꺼낸다.
// - dev: 이 컴퓨터·e2e에서 개발 토큰을 직접 넣는다. 탭을 닫으면 잊는다(sessionStorage).
// - supabase: Supabase Auth 구글 로그인 세션의 access_token을 쓴다 (createClient, signInWithOAuth).
// [주의] 토큰을 번들에 넣지 않는다. NEXT_PUBLIC_ 값은 주소와 공개 키뿐이다.
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export const AUTH_MODE = process.env.NEXT_PUBLIC_AUTH === "supabase" ? "supabase" : "dev";
const DEV_KEY = "marvia-dev-token";

let client: SupabaseClient | null = null;

function supabase(): SupabaseClient {
  // [왜] 공개(anon) 키와 주소만 쓴다. 서버가 토큰 서명·소유자 목록을 다시 본다
  client ??= createClient(process.env.NEXT_PUBLIC_SUPABASE_URL ?? "", process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "");
  return client;
}

export async function currentToken(): Promise<string | null> {
  if (AUTH_MODE === "dev") return sessionStorage.getItem(DEV_KEY);
  const { data } = await supabase().auth.getSession();
  return data.session?.access_token ?? null;
}

export async function signIn(devToken?: string): Promise<void> {
  if (AUTH_MODE === "dev") {
    if (devToken) sessionStorage.setItem(DEV_KEY, devToken);
    return;
  }
  await supabase().auth.signInWithOAuth({ provider: "google", options: { redirectTo: window.location.origin } });
}

export async function signOut(): Promise<void> {
  if (AUTH_MODE === "dev") {
    sessionStorage.removeItem(DEV_KEY);
    return;
  }
  await supabase().auth.signOut();
}
```

- [ ] **Step 2: 확인**: 명령 B. Expected: `web-ok` [실측 11-07].

- [ ] **Step 3: 커밋**

```bash
git add web/lib/auth.ts web/package.json web/package-lock.json
git commit -m "feat(web): Supabase 구글 로그인 (NEXT_PUBLIC_AUTH=supabase)"
```

---
### Task 8: Docker 이미지와 compose 앱 (done 4.3, C8)

**배울 것:** 멀티스테이지 빌드는 빌드 도구(uv)가 있는 단계에서 `.venv`를 만들고 실행 단계에는 결과만 복사한다. 우리 코드는 `rules`·`prompts`·`migrations`를 소스 트리 기준(`Path(__file__).parents[n]`)으로 찾으므로 프로젝트를 `/app`에 편집 모드로 깔아 그 배치를 지킨다(`--no-editable`이면 site-packages로 가서 경로가 깨진다). `.dockerignore`를 `*`로 시작하는 허용 목록으로 두면 저장소 루트의 `.env`·`.local`이 빌드 맥락에 들어가지 않는다. 실행은 uid 10001이고 파일 주인은 root라 실행 중에 코드를 바꿀 수 없다. slim 이미지에는 curl이 없어 HEALTHCHECK는 파이썬 한 줄로 `/health`를 본다. 맥(arm64)에서 만든 이미지는 Cloud Run(amd64)에서 안 뜨므로 `--platform linux/amd64`로 한 번 빌드해 wheel이 다 있는지 본다.

[주의] compose의 `db`를 digest로 고정하고 `127.0.0.1:5433`으로 바꾸면 `docker compose up -d db`가 DB 컨테이너를 다시 만든다(데이터는 `pgdata_v2` 볼륨에 남는다). 다른 작업(평가 실행, 검증)이 DB를 쓰는 중이면 끝난 뒤에 한다. 지금 받아 둔 `pgvector/pgvector:pg16`(`sha256:7b822b0a…`)와 고정할 digest(`0dd3149a…`, CI와 같음)가 달라 새 이미지를 받는다. 같은 Postgres 16 안의 판 차이라 데이터 폴더는 그대로 읽힌다 [추정]. 컨테이너 안에서 `host.docker.internal:5433`으로 붙는 검사 스크립트는 127.0.0.1로만 연 포트에도 닿는다(시험용 Neo4j `127.0.0.1:7689`로 확인) [실측 11-07].

**Files:**
- Create: `src/marvia/prepare_db.py`, `Dockerfile`, `.dockerignore`, `web/Dockerfile`, `web/.dockerignore`, `tests/test_docker.py`
- Modify: `docker-compose.yml`

**Interfaces:**
- Produces: `python -m marvia.prepare_db` (표 준비, 여러 번 돌려도 같다), 이미지 `marvia-api:local`(운영 단계 `runtime`, 기본), compose profile `app`(`prepare`, `api` 127.0.0.1:8080, `web` 127.0.0.1:3000)

- [ ] **Step 1: 실패하는 시험**: `tests/test_docker.py` (새 파일)

<!-- fmt: off -->
```python
"""이미지·compose 경계 시험 (계획 4b Task 8, C8). 도커 없이 파일만 읽는다."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = [ROOT / "Dockerfile", ROOT / "web" / "Dockerfile"]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
PINNED = re.compile(r"@sha256:[0-9a-f]{64}$")


def test_the_build_context_is_an_allow_list_without_secrets_or_real_data():
    # [왜] 저장소 루트에 .env(키), .local(실제 응답 저장본)이 있다. COPY 층에 들어가면 이미지에서 지울 수 없다
    lines = [line.strip() for line in (ROOT / ".dockerignore").read_text().splitlines()]
    rules = [line for line in lines if line and not line.startswith("#")]
    assert rules[0] == "*"  # 모두 막고 시작한다
    opened = {line[1:] for line in rules if line.startswith("!")}
    assert opened == {
        "pyproject.toml",
        "uv.lock",
        "src",
        "rules",
        "prompts",
        "migrations",
        "fixtures/unipass",
        "corpus/graph",
    }


def test_every_image_is_pinned_by_digest():
    # [왜] 태그는 옮겨질 수 있다. 같은 커밋이 다른 날 다른 이미지로 빌드되지 않게 한다
    stages: set[str] = set()
    refs: list[str] = []
    for path in DOCKERFILES:
        for line in path.read_text().splitlines():
            if line.startswith("FROM "):
                parts = line.split()
                if parts[1] not in stages:  # [왜] "FROM base AS e2e"의 base는 앞 단계 이름이다
                    refs.append(parts[1])
                if len(parts) >= 4 and parts[2].upper() == "AS":
                    stages.add(parts[3])
    assert refs and all(PINNED.search(ref) for ref in refs), refs
    images = [service["image"] for service in COMPOSE["services"].values() if "build" not in service]
    assert images and all(PINNED.search(image) for image in images), images


def test_published_ports_open_on_this_computer_only():
    # [왜] 포트만 적으면 모든 주소에 열려 같은 망의 다른 기기가 기본 비밀번호로 DB·그래프에 붙는다
    for name, service in COMPOSE["services"].items():
        for port in service.get("ports", []):
            assert port.startswith("127.0.0.1:"), (name, port)
```
<!-- fmt: on -->

```bash
uv run pytest -q tests/test_docker.py
```

Expected: FAIL `FileNotFoundError: ... .dockerignore`

- [ ] **Step 2: 코드**: `src/marvia/prepare_db.py` (새 파일)

<!-- fmt: off -->
```python
"""DB 표를 준비한다: migrations/*.sql, 대화 기록(checkpointer)·장기 기억(Store) 표 (설계 8절, 계획 4b Task 8).

실행: python -m marvia.prepare_db (compose의 prepare 서비스, 배포의 Cloud Run 작업). 여러 번 돌려도 같다.
[왜] 운영 서버가 시작할 때 표를 만들면 CREATE INDEX CONCURRENTLY가 다른 연결의 트랜잭션을 기다리다 시작 탐침이
     실패할 수 있다(계획 4b 사전 부검 3번). 표 만들기를 한 번 도는 명령으로 떼어 둔다.
     서버의 setup()은 표가 있으면 아무것도 하지 않는다.
하지 않는 일: 코퍼스 색인(scripts/index_corpus.py), 그래프 적재(scripts/build_graph.py).
"""

from __future__ import annotations

from marvia.config import Settings
from marvia.db import connect
from marvia.graph.live import live_memory


def main() -> None:
    settings = Settings()
    with connect(settings.database_url):  # migrations/*.sql을 적용한다
        pass
    with live_memory(settings.database_url, settings.data_key.get_secret_value()):  # setup()이 표를 만든다
        pass
    print("표 준비 끝")


if __name__ == "__main__":
    main()
```
<!-- fmt: on -->

`.dockerignore` (새 파일):

```text
# 빌드 맥락 허용 목록 (계획 4b Task 8). 모두 막고 이미지에 필요한 것만 연다.
# [왜] 저장소 루트에 .env(키), .local(실제 응답 저장본), .venv 같은 로컬 폴더가 있다. COPY 층에 남으면 지울 수 없다
*
!pyproject.toml
!uv.lock
!src
!rules
!prompts
!migrations
!fixtures/unipass
!corpus/graph
**/__pycache__
```

`Dockerfile` (새 파일):

```dockerfile
# syntax=docker/dockerfile:1
# Marvia API 이미지 (설계 13절: 멀티스테이지, non-root, 계획 4b Task 8).
# 단계: build(uv로 .venv) → base(실행에 필요한 것만, uid 10001) → runtime(운영, 마지막 단계)
# [주의] 이미지는 digest로 고정한다. 태그는 옮겨질 수 있다. 맥(arm64)에서도 --platform linux/amd64로 한 번 빌드해 본다(Cloud Run)
FROM ghcr.io/astral-sh/uv:0.9.30@sha256:538e0b39736e7feae937a65983e49d2ab75e1559d35041f9878b7b7e51de91e4 AS uv

FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS build
COPY --from=uv /uv /bin/uv
# [왜] 바이트코드를 미리 만들어 실행 사용자가 /app에 쓰지 않아도 되게 한다. 이미지의 파이썬만 쓴다(내려받지 않음)
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# [왜] 의존성 층을 소스와 나눠, 코드만 바뀌면 이 층을 다시 쓰지 않는다
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY rules ./rules
COPY prompts ./prompts
COPY migrations ./migrations
COPY fixtures/unipass ./fixtures/unipass
COPY corpus/graph ./corpus/graph
# [주의] 프로젝트는 편집 모드(.pth가 /app/src를 가리킴)로 둔다. rules·prompts를 소스 트리 기준으로 찾는다(Path(__file__))
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS base
RUN useradd --uid 10001 --create-home --home-dir /home/marvia marvia
WORKDIR /app
# [왜] 파일 주인은 root로 두고 실행은 10001로 한다. 실행 중에 코드·규칙을 바꿀 수 없다
COPY --from=build /app /app
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 HOME=/home/marvia PORT=8080
USER 10001
EXPOSE 8080
# [왜] slim 이미지에는 curl이 없다. 파이썬 표준 라이브러리로 /health를 본다
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=2)"]

FROM base AS runtime
CMD ["python", "-m", "marvia.server"]
```

`web/.dockerignore` (새 파일):

```text
node_modules
.next
test-results
playwright-report
e2e/screenshots
.env*
```

`web/Dockerfile` (새 파일):

```dockerfile
# 화면 이미지 (계획 4b Task 8): 의존성 → 빌드 → 실행(standalone, node 사용자). 이미지는 digest로 고정한다
FROM node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS deps
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
# [왜] 컨테이너 안에서 npm ci를 한다. 호스트(맥)의 node_modules는 리눅스용 SWC 바이너리가 아니다
RUN npm ci

FROM node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS build
WORKDIR /app
# [주의] NEXT_PUBLIC_ 값은 빌드할 때 번들에 박힌다. 주소와 공개 값만 넣는다(토큰·키 금지)
ARG NEXT_PUBLIC_API_URL=http://localhost:8080
ARG NEXT_PUBLIC_AUTH=dev
ARG NEXT_PUBLIC_SUPABASE_URL=
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY=
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_PUBLIC_AUTH=$NEXT_PUBLIC_AUTH \
    NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
# [왜] 이미지에 있는 node 사용자(uid 1000)로 돈다. 파일 주인은 root라 실행 중에 바꿀 수 없다
USER node
EXPOSE 3000
CMD ["node", "server.js"]
```

`docker-compose.yml`:

```diff
--- a/docker-compose.yml
+++ b/docker-compose.yml
@@ -1,17 +1,21 @@
-# 로컬 개발·테스트용 Postgres·Neo4j 주문서 (설계 8절·5.5, 계획 1 Task 8, 계획 3b Task 3).
+# 로컬 개발·테스트용 Postgres·Neo4j와 API·화면 주문서 (설계 8절·5.5·13절, 계획 1 Task 8, 계획 3b Task 3, 계획 4b Task 8·9).
 # 하지 않는 일: 배포. 배포 DB는 Supabase이고 여기 비밀번호는 내 컴퓨터에서만 쓰는 값이다.
 # 켜기: docker compose up -d db neo4j neo4j-test / 끄기: docker compose stop db neo4j neo4j-test
+# 앱(profile app): docker compose --profile app up -d --build  (prepare가 표를 만든 뒤 api가 뜬다)
 name: marvia-v2 # [왜] v1 compose와 이름을 나눠 컨테이너·볼륨이 섞이지 않게 한다
 services:
   db:
     # [왜] pgvector가 미리 깔린 Postgres 16. 계획 2의 RAG 벡터 검색을 같은 DB에서 쓴다
-    image: pgvector/pgvector:pg16
+    # pgvector/pgvector:pg16 (여러 구조 묶음의 해시, CI와 같다). 태그는 옮겨질 수 있다
+    image: pgvector/pgvector@sha256:0dd3149a06e4579a0d70d8fef9945636cd514005e7237deb27f9b67886f8dc4f
     environment: # DB를 처음 만들 때 쓰는 계정·DB 이름 (src/marvia/config.py 기본 주소와 같다)
       POSTGRES_USER: marvia
       POSTGRES_PASSWORD: marvia
       POSTGRES_DB: marvia
     ports:
-      - "5433:5432" # 내 컴퓨터 5433번 문 → 상자 안 Postgres 5432번 문. [왜] 5432는 다른 Postgres와 겹치기 쉽다
+      # 내 컴퓨터 5433번 문 → 상자 안 Postgres 5432번 문. [왜] 5432는 다른 Postgres와 겹치기 쉽다
+      # [왜] 127.0.0.1: 이 컴퓨터에서만 연다. 같은 망의 다른 기기가 기본 비밀번호로 붙지 못한다
+      - "127.0.0.1:5433:5432"
     volumes:
       - pgdata_v2:/var/lib/postgresql/data # [왜] 상자를 지웠다 켜도 데이터가 남게 상자 밖 저장 공간에 둔다
   neo4j:
@@ -36,6 +40,40 @@
       - "127.0.0.1:7689:7687" # bolt만. 브라우저 문은 열지 않는다
     tmpfs:
       - /data
+  prepare:
+    # 표 만들기를 한 번 돌고 끝난다 (python -m marvia.prepare_db). [왜] 운영 서버 시작과 떼어 둔다
+    profiles: [app]
+    image: marvia-api:local
+    build: { context: ., target: runtime }
+    command: ["python", "-m", "marvia.prepare_db"]
+    environment:
+      MARVIA_DATABASE_URL: postgresql://marvia:marvia@db:5432/marvia
+      MARVIA_DATA_KEY: ${MARVIA_DATA_KEY:-}
+    depends_on: [db]
+  api:
+    # 화면 서버 (python -m marvia.server). 키는 셸 환경 변수에서 받는다. 비어 있으면 뜨지 않는다(fail-closed)
+    profiles: [app]
+    image: marvia-api:local
+    build: { context: ., target: runtime }
+    environment:
+      MARVIA_DATABASE_URL: postgresql://marvia:marvia@db:5432/marvia
+      MARVIA_NEO4J_URL: bolt://neo4j:7687
+      MARVIA_DATA_KEY: ${MARVIA_DATA_KEY:-}
+      MARVIA_ANTHROPIC_API_KEY: ${MARVIA_ANTHROPIC_API_KEY:-}
+      MARVIA_VOYAGE_API_KEY: ${MARVIA_VOYAGE_API_KEY:-}
+      MARVIA_AUTH: dev # [주의] 이 컴퓨터용. 배포는 supabase (docs/deploy.md)
+      MARVIA_DEV_TOKEN: ${MARVIA_DEV_TOKEN:-}
+      MARVIA_WEB_ORIGIN: http://localhost:3000
+    ports:
+      - "127.0.0.1:8080:8080" # [왜] 8000은 다른 서비스가 쓴다
+    depends_on:
+      prepare: { condition: service_completed_successfully }
+      neo4j: { condition: service_started }
+  web:
+    profiles: [app]
+    build: { context: ./web, args: { NEXT_PUBLIC_API_URL: "http://localhost:8080", NEXT_PUBLIC_AUTH: dev } }
+    ports:
+      - "127.0.0.1:3000:3000"
 volumes:
   pgdata_v2: {}
   neo4jdata_v2: {}
```

- [ ] **Step 3: 확인 (pytest)**: 명령 A. Expected: `677 passed`, 오류 0.

- [ ] **Step 4: 확인 (이미지, C8)**: 이 컴퓨터에서 실제로 돌리고 결과를 `docs/deploy.md`의 "로컬 확인" 표(T10)에 옮긴다.

```bash
set -o pipefail
docker build -q --target runtime -t marvia-api:local .
docker run --rm marvia-api:local sh -c 'id -u; ls -a /app; python -c "from marvia.tools.rules import load_rules; from marvia.prompts import render; load_rules(\"agent\"); print(len(render(\"agent\")) > 0)"'
docker images marvia-api:local --format '{{.Size}}'
docker buildx build --platform linux/amd64 --target runtime -t marvia-api:amd64 --load .
docker run --rm -e MARVIA_AUTH=supabase marvia-api:local 2>&1 | tail -1
docker run --rm -e K_SERVICE=x -e MARVIA_AUTH=dev -e MARVIA_DEV_TOKEN=t marvia-api:local 2>&1 | tail -1
```

Expected [실측 11-07]: `10001`; `/app`에 `.venv corpus fixtures migrations prompts pyproject.toml rules src uv.lock`만; `True`; `1.07GB`(1.2GB 이하); amd64 빌드 성공(약 49초); `RuntimeError: MARVIA_SUPABASE_URL이 없어 로그인을 확인할 수 없습니다`; `RuntimeError: Cloud Run에서는 개발 로그인(MARVIA_AUTH=dev)으로 시작하지 않습니다`.

compose 앱은 버리는 키로 띄워 본다(키 값은 셸에만 두고 찍지 않는다):

```bash
export MARVIA_DATA_KEY=$(docker run --rm marvia-api:local python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export MARVIA_DEV_TOKEN=local-dev MARVIA_ANTHROPIC_API_KEY=sk-not-real MARVIA_VOYAGE_API_KEY=not-real
docker compose --profile app up -d --build db neo4j prepare api
for i in $(seq 1 30); do [ "$(docker inspect -f '{{.State.Health.Status}}' marvia-v2-api-1)" = healthy ] && break; sleep 2; done
docker compose logs prepare | tail -1
curl -s http://127.0.0.1:8080/health; curl -s -o /dev/null -w " %{http_code}\n" -X POST http://127.0.0.1:8080/agui -d '{}'
docker compose --profile app stop api prepare
```

Expected [실측 11-07, 다른 포트의 버리는 compose 프로젝트로]: prepare `표 준비 끝`, api healthy 약 6초, `{"ok":true} 401`. (키가 가짜라 질문은 보내지 않는다. 유료 호출 없음.)

- [ ] **Step 5: 커밋**

```bash
git add src/marvia/prepare_db.py Dockerfile .dockerignore web/Dockerfile web/.dockerignore docker-compose.yml tests/test_docker.py
git commit -m "feat(docker): API·화면 멀티스테이지 non-root 이미지와 compose 앱, 표 준비 명령"
```

---
### Task 9: Playwright in Docker, 주요 흐름·접근성·스크린샷 (done 4.2, C9)

**배울 것:** 공식 Playwright 이미지에는 브라우저와 그 버전에 맞는 실행 파일이 `/ms-playwright`에 들어 있다. `@playwright/test`가 이미지 태그와 같은 판이어야 그 실행 파일을 찾는다. 시험 실행기는 그 이미지 위에서 `npm ci`만 하고 브라우저를 받지 않는다. compose e2e 망은 `internal: true`라 컨테이너가 바깥으로 나가지 못한다. 가짜 API는 질문 글로 각본을 고르고 "이번 차례에 이미 낸 모델 답 수"로 다음 줄을 고르므로 여러 대화·재개가 섞여도 어긋나지 않는다. 가짜 검색을 2초 늦춰 "진행 중인 할 일이 답보다 먼저 보인다"를 화면에서 잰다. `@axe-core/playwright`의 `new AxeBuilder({ page }).analyze()`가 접근성 위반을 돌려준다(serious·critical 0이 기준).

**Files:**
- Create: `e2e/fake_api.py`, `web/e2e.Dockerfile`, `web/playwright.config.ts`, `web/e2e/flows.spec.ts`, `web/e2e/screenshots/{answer,choice,approval}.png`
- Modify: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `web/package.json`, `web/package-lock.json`, `tests/test_docker.py`

**Interfaces:**
- Consumes: `server.build_app`, `auth.verifier` (dev), `graph.main.AgentDeps`
- Produces: compose profile `e2e`(`api-e2e`, `web-e2e`, `playwright`), 명령 `docker compose --profile e2e run --rm --build playwright`

- [ ] **Step 1: 실패하는 시험**: `tests/test_docker.py`

```diff
--- a/tests/test_docker.py
+++ b/tests/test_docker.py
@@ -1,12 +1,13 @@
-"""이미지·compose 경계 시험 (계획 4b Task 8, C8). 도커 없이 파일만 읽는다."""
+"""이미지·compose 경계 시험 (계획 4b Task 8·9, C8·C9). 도커 없이 파일만 읽는다."""
 
+import json
 import re
 from pathlib import Path
 
 import yaml
 
 ROOT = Path(__file__).resolve().parents[1]
-DOCKERFILES = [ROOT / "Dockerfile", ROOT / "web" / "Dockerfile"]
+DOCKERFILES = [ROOT / "Dockerfile", ROOT / "web" / "Dockerfile", ROOT / "web" / "e2e.Dockerfile"]
 COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
 PINNED = re.compile(r"@sha256:[0-9a-f]{64}$")
 
@@ -26,6 +27,7 @@
         "migrations",
         "fixtures/unipass",
         "corpus/graph",
+        "e2e/fake_api.py",
     }
 
 
@@ -51,3 +53,31 @@
     for name, service in COMPOSE["services"].items():
         for port in service.get("ports", []):
             assert port.startswith("127.0.0.1:"), (name, port)
+
+
+def test_the_e2e_network_cannot_reach_outside_and_the_runtime_image_has_no_fake_api():
+    assert COMPOSE["networks"]["e2e"]["internal"] is True
+    for name in ("api-e2e", "web-e2e", "playwright"):
+        assert COMPOSE["services"][name]["networks"] == ["e2e"], name
+    dockerfile = (ROOT / "Dockerfile").read_text()
+    runtime = dockerfile.split("FROM base AS runtime")[1]
+    assert "fake_api" not in runtime  # 가짜 API는 e2e 단계에만 복사한다
+    assert dockerfile.rstrip().endswith('CMD ["python", "-m", "marvia.server"]')  # 기본(마지막) 단계가 운영
+
+
+def test_the_playwright_image_matches_the_test_package_version():
+    # [왜] 이미지 태그와 @playwright/test 버전이 다르면 브라우저 실행 파일을 찾지 못한다
+    package = json.loads((ROOT / "web" / "package.json").read_text())
+    version = package["devDependencies"]["@playwright/test"]
+    image = next(
+        line.split()[1]
+        for line in (ROOT / "web" / "e2e.Dockerfile").read_text().splitlines()
+        if line.startswith("FROM ")
+    )
+    assert image.startswith(f"mcr.microsoft.com/playwright:v{version}-noble@sha256:")
+    # [왜] @axe-core/playwright는 playwright-core를 아무 버전이나 받는다. 같은 버전으로 묶지 않으면
+    #      npm이 최신판을 따로 깔아 타입이 둘로 갈린다(11-07 실측: 1.65.0과 1.64.1, next build 실패)
+    assert package["devDependencies"]["playwright-core"] == version
+    # [왜] 정확한 버전만 쓴다(save-exact). ^·~가 붙으면 잠금 파일 밖에서 버전이 바뀔 수 있다
+    versions = {**package["dependencies"], **package["devDependencies"]}
+    assert all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v in versions.values()), versions
```

```bash
uv run pytest -q tests/test_docker.py
```

Expected: FAIL (허용 목록에 `e2e/fake_api.py`가 없다, `web/e2e.Dockerfile`이 없다)

- [ ] **Step 2: 코드**: `e2e/fake_api.py` (새 파일)

<!-- fmt: off -->
```python
"""화면 e2e용 가짜 API (계획 4b Task 9). 실제 모델·Voyage·DB 없이 화면 서버(marvia.server)를 띄운다.

질문 글로 각본을 고르는 가짜 모델, 가짜 RAG·조문 조회·작성자, 메모리 대화 기록으로 그래프를 만든다.
UNI-PASS는 재생 데이터(DEMO 번호)다. 로그인은 개발 로그인(MARVIA_AUTH=dev)만 쓴다.
[주의] 운영 이미지에는 이 파일이 들어가지 않는다(Dockerfile의 e2e 단계에만 복사한다). 바깥 호출 0건:
       Anthropic·Voyage 클라이언트를 만들지 않고, compose e2e 망은 바깥으로 나가지 못한다(internal).
실행(컨테이너 안): python e2e/fake_api.py
"""

from __future__ import annotations

import os
import time
from datetime import date
from typing import Any

import uvicorn
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from marvia.auth import verifier
from marvia.config import Settings
from marvia.graph.main import AgentDeps, build_main_graph
from marvia.graph.rag import RagDeps
from marvia.graph.schemas import Draft, Plan, Step
from marvia.rag.models import Evidence
from marvia.rag.schemas import Grade, QueryAnalysis, Rewrite
from marvia.server import build_app
from marvia.tools.reimport import ItemFacts

UNIT = Evidence(
    unit_id="L001556@20261002#제241조.3항",
    law_name="관세법",
    heading="관세법 > 제9장 통관 > 제241조(수출ㆍ수입 또는 반송의 신고)",
    effective=date(2026, 10, 2),
    source_url="https://www.law.go.kr/법령/관세법",
    text="제241조 ③ 물품을 보세창고에 반입한 자는 반입일부터 30일 이내에 신고해야 한다.",
    score=0.9,
)
TWO = [{"label": "부산", "description": "부산항 기준"}, {"label": "인천", "description": "인천항 기준"}]
# 질문 글에 든 낱말 → 모델이 차례로 낼 도구 호출 (각 줄이 모델 호출 한 번). 끝나면 빈 답으로 루프를 끝낸다
SCRIPTS: dict[str, list[tuple[str, dict]]] = {
    "수입신고": [
        ("write_todos", {"todos": [{"content": "수입신고 기한 근거 찾기", "status": "in_progress"}]}),
        ("search_law", {"query": "수입신고 기한"}),
        ("calc_deadlines", {}),
    ],
    "장치기간": [("ask_user", {"question": "어느 항구 기준으로 볼까요?", "options": TWO})],
    "설명": [("save_preference", {"depth": "자세히"})],
}


class ScriptModel(BaseChatModel):
    """질문 글로 각본을 고르고, 이번 차례에 이미 낸 모델 답 수로 다음 줄을 고르는 가짜 모델.

    [왜] 상태를 모델 객체가 아니라 메시지에서 읽는다. 여러 대화·재개가 섞여도 각본이 어긋나지 않는다.
    """

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptModel:  # type: ignore[override]
        return self

    @property
    def _llm_type(self) -> str:
        return "e2e-script"

    def _generate(
        self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        last = max(i for i, m in enumerate(messages) if m.type == "human")
        question = str(messages[last].content)
        step = sum(m.type == "ai" for m in messages[last + 1 :])
        script = next((lines for key, lines in SCRIPTS.items() if key in question), [])
        if step < len(script):
            name, args = script[step]
            message = AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"e2e-{name}-{step}"}])
        else:
            message = AIMessage("")
        return ChatResult(generations=[ChatGeneration(message=message)])


def search(query: str, as_of: date) -> list[Evidence]:
    # [왜] 검색을 늦춰 "진행 중인 할 일"이 답보다 먼저 보이는지 e2e가 본다 (C9 실시간 계획)
    time.sleep(float(os.environ.get("MARVIA_E2E_SEARCH_DELAY", "2")))
    return [UNIT]


def fake_deps() -> AgentDeps:
    rag = RagDeps(
        analyze=lambda prompt: QueryAnalysis(
            question_type="문구 해석", as_of=None, search_query="수입신고 기한"
        ),
        search=search,
        rerank=lambda query, texts: [0.9] * len(texts),
        grade=lambda prompt: Grade(sufficient=True, reason="e2e", missing=""),
        rewrite=lambda prompt: Rewrite(search_query="수입신고 기한"),
    )

    def write(prompt: str) -> Draft:
        # [왜] 작성자 프롬프트에 든 것만 쓴다. 근거가 없으면 인용하지 않고, 화물이 없으면 토큰을 쓰지 않는다
        #      (검증자를 통과한다)
        # [주의] 작성자 지시문 자체에 "[BL1]" 예가 있다. 화물 줄("[BL1]: 단계")이 있을 때만 토큰을 쓴다
        cargo = "[BL1]:" in prompt
        lead = "[BL1]의 수입신고 기한과 근거를 아래에 정리했어요." if cargo else "확인한 내용을 정리했어요."
        cited = [UNIT.unit_id] if UNIT.unit_id in prompt else []
        return Draft(
            answer=lead, citations=cited, next_options=["관세사에게 신고 대행 묻기"], forwarder_message=""
        )

    nothing = ItemFacts(
        category="모름",
        same=[],
        different=[],
        prior_precise="모름",
        prior_result="모름",
        prior_cert_on=None,
        flags=[],
    )
    return AgentDeps(
        rag=rag,
        plan=lambda prompt: Plan(steps=[Step(action="write", query="", reason="e2e")]),
        item=lambda prompt: nothing,
        write=write,
        model=ScriptModel(),
        provision=lambda label, as_of: [UNIT] if label == "관세법 제241조제3항" else [],
    )


def main() -> None:
    settings = Settings()
    graph = build_main_graph(fake_deps(), InMemorySaver(), loop="agent", store=InMemoryStore())
    app = build_app(graph, verifier(settings), web_origin=settings.web_origin, forget=lambda user: None)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
```
<!-- fmt: on -->

`Dockerfile`:

```diff
--- a/Dockerfile
+++ b/Dockerfile
@@ -1,6 +1,6 @@
 # syntax=docker/dockerfile:1
 # Marvia API 이미지 (설계 13절: 멀티스테이지, non-root, 계획 4b Task 8).
-# 단계: build(uv로 .venv) → base(실행에 필요한 것만, uid 10001) → runtime(운영, 마지막 단계)
+# 단계: build(uv로 .venv) → base(실행에 필요한 것만, uid 10001) → e2e(가짜 API, 화면 시험용) / runtime(운영, 마지막 단계)
 # [주의] 이미지는 digest로 고정한다. 태그는 옮겨질 수 있다. 맥(arm64)에서도 --platform linux/amd64로 한 번 빌드해 본다(Cloud Run)
 FROM ghcr.io/astral-sh/uv:0.9.30@sha256:538e0b39736e7feae937a65983e49d2ab75e1559d35041f9878b7b7e51de91e4 AS uv
 
@@ -33,5 +33,9 @@
 HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
   CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=2)"]
 
+FROM base AS e2e
+COPY e2e/fake_api.py /app/e2e/fake_api.py
+CMD ["python", "/app/e2e/fake_api.py"]
+
 FROM base AS runtime
 CMD ["python", "-m", "marvia.server"]
```

`.dockerignore`:

```diff
--- a/.dockerignore
+++ b/.dockerignore
@@ -9,4 +9,5 @@
 !migrations
 !fixtures/unipass
 !corpus/graph
+!e2e/fake_api.py
 **/__pycache__
```

`docker-compose.yml`:

```diff
--- a/docker-compose.yml
+++ b/docker-compose.yml
@@ -2,6 +2,7 @@
 # 하지 않는 일: 배포. 배포 DB는 Supabase이고 여기 비밀번호는 내 컴퓨터에서만 쓰는 값이다.
 # 켜기: docker compose up -d db neo4j neo4j-test / 끄기: docker compose stop db neo4j neo4j-test
 # 앱(profile app): docker compose --profile app up -d --build  (prepare가 표를 만든 뒤 api가 뜬다)
+# 화면 시험(profile e2e): docker compose --profile e2e run --rm --build playwright  (바깥으로 나가지 못하는 망)
 name: marvia-v2 # [왜] v1 compose와 이름을 나눠 컨테이너·볼륨이 섞이지 않게 한다
 services:
   db:
@@ -74,6 +75,35 @@
     build: { context: ./web, args: { NEXT_PUBLIC_API_URL: "http://localhost:8080", NEXT_PUBLIC_AUTH: dev } }
     ports:
       - "127.0.0.1:3000:3000"
+  api-e2e:
+    # 화면 시험용 가짜 API (e2e/fake_api.py). 실제 모델·DB를 쓰지 않는다
+    profiles: [e2e]
+    build: { context: ., target: e2e }
+    environment:
+      MARVIA_AUTH: dev
+      MARVIA_DEV_TOKEN: e2e-token # 시험용 값. 운영에 쓰지 않는다
+      MARVIA_WEB_ORIGIN: http://web-e2e:3000
+    networks: [e2e]
+  web-e2e:
+    profiles: [e2e]
+    build: { context: ./web, args: { NEXT_PUBLIC_API_URL: "http://api-e2e:8080", NEXT_PUBLIC_AUTH: dev } }
+    networks: [e2e]
+  playwright:
+    profiles: [e2e]
+    build: { context: ./web, dockerfile: e2e.Dockerfile }
+    environment:
+      E2E_BASE_URL: http://web-e2e:3000
+      E2E_DEV_TOKEN: e2e-token
+    volumes:
+      - ./web/e2e/screenshots:/work/e2e/screenshots # 스크린샷을 저장소에 남긴다
+    depends_on:
+      api-e2e: { condition: service_healthy }
+      web-e2e: { condition: service_started }
+    networks: [e2e]
+networks:
+  e2e:
+    # [왜] 바깥으로 나가지 못하는 망. 시험 중 모델·임베딩 API 호출은 0건일 수밖에 없다
+    internal: true
 volumes:
   pgdata_v2: {}
   neo4jdata_v2: {}
```

`web/package.json` (그 뒤 명령 C):

```diff
--- a/web/package.json
+++ b/web/package.json
@@ -6,7 +6,8 @@
     "dev": "next dev --port 3000",
     "build": "next build",
     "start": "next start --port 3000",
-    "typecheck": "tsc --noEmit"
+    "typecheck": "tsc --noEmit",
+    "e2e": "playwright test"
   },
   "engines": {
     "node": ">=22.12.0"
@@ -19,9 +20,12 @@
     "react-dom": "19.3.1"
   },
   "devDependencies": {
+    "@axe-core/playwright": "4.14.0",
+    "@playwright/test": "1.64.1",
     "@types/node": "22.20.5",
     "@types/react": "19.3.0",
     "@types/react-dom": "19.3.0",
+    "playwright-core": "1.64.1",
     "typescript": "5.9.3"
   }
 }
```

`web/e2e.Dockerfile` (새 파일):

```dockerfile
# Playwright 시험 실행 이미지 (계획 4b Task 9, C9). 브라우저는 이 이미지 안에만 있다(호스트에 설치하지 않는다)
# [주의] 이미지 태그(v1.64.1)와 package.json의 @playwright/test(1.64.1)가 같아야 브라우저 실행 파일을 찾는다
FROM mcr.microsoft.com/playwright:v1.64.1-noble@sha256:2f05f8a734509a7b3f26a912639488ee08f58a7b292d14d62271bcff9038768f
WORKDIR /work
COPY package.json package-lock.json .npmrc ./
RUN npm ci
RUN test "$(node -p "require('@playwright/test/package.json').version")" = "1.64.1"
COPY playwright.config.ts ./
COPY e2e ./e2e
ENV NEXT_TELEMETRY_DISABLED=1
CMD ["npx", "playwright", "test"]
```

`web/playwright.config.ts` (새 파일):

```ts
// Playwright 설정 (계획 4b Task 9). compose e2e 망 안에서 돈다: 화면 http://web-e2e:3000, API http://api-e2e:8080
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // [왜] 가짜 API는 대화마다 따로지만 화면 하나를 함께 쓴다. 깜빡이는 실패를 숨기지 않게 다시 돌리지 않는다
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://web-e2e:3000",
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
    viewport: { width: 1000, height: 1400 },
  },
});
```

`web/e2e/flows.spec.ts` (새 파일):

```ts
// 화면 주요 흐름 (계획 4b Task 9, C9): 질문→답·근거·화물, 실시간 계획, 선택지, 승인(고치기·거절).
// 가짜 API(e2e/fake_api.py)라 실제 모델 답이 아니다. 스크린샷에는 DEMO 번호만 있다.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const TOKEN = process.env.E2E_DEV_TOKEN ?? "e2e-token";
const outside: string[] = [];

test.beforeEach(async ({ page }) => {
  // [왜] 화면이 모델·임베딩 공급자에 닿지 않는지 센다. 닿으면 막고 적는다 (바깥 호출 0건)
  await page.route(/(anthropic\.com|voyageai\.com)/, (route) => {
    outside.push(route.request().url());
    return route.abort();
  });
  await page.goto("/");
  await page.getByLabel("개발 로그인 토큰").fill(TOKEN);
  await page.getByRole("button", { name: "들어가기" }).click();
});

test.afterAll(() => {
  expect(outside).toEqual([]);
});

async function ask(page: Page, text: string) {
  await page.getByLabel("질문이나 화물 단서 (B/L·화물관리번호)").fill(text);
  await page.locator("form.ask").getByRole("button", { name: "보내기" }).click();
}

async function accessible(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  const serious = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
}

const answers = (page: Page) => page.locator('.chat li[data-role="assistant"]');

test("질문하면 계획이 답보다 먼저 보이고, 답·근거·화물 카드가 뜬다", async ({ page }) => {
  await ask(page, "DEMO0001 언제까지 수입신고 해야 해요?");
  // 가짜 검색이 2초 늦다. 그동안 진행 중인 할 일이 보이고 답은 아직 없다 (실시간 계획)
  await expect(page.locator('.plan li[data-status="in_progress"]')).toBeVisible();
  expect(await answers(page).count()).toBe(0);
  await expect(answers(page)).toContainText("수입신고 기한과 근거");
  await expect(page.getByRole("heading", { name: "이렇게 읽었어요" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "DEMO0001" })).toBeVisible();
  await expect(page.getByText("시행일 2026-10-02")).toBeVisible();
  await expect(page.getByRole("link", { name: /원문 보기/ })).toHaveAttribute("href", /^https:\/\/www\.law\.go\.kr\//);
  await accessible(page);
  await page.screenshot({ path: "e2e/screenshots/answer.png", fullPage: true });
});

test("선택지 카드에서 고르면 이어서 답한다", async ({ page }) => {
  await ask(page, "장치기간이 궁금해요");
  await expect(page.getByRole("heading", { name: "어느 항구 기준으로 볼까요?" })).toBeVisible();
  await expect(page.getByRole("button", { name: /부산 \(권장\)/ })).toBeVisible();
  await accessible(page);
  await page.screenshot({ path: "e2e/screenshots/choice.png", fullPage: true });
  await page.getByRole("button", { name: /인천/ }).click();
  await expect(answers(page)).toContainText("확인한 내용을 정리했어요");
});

test("승인 카드에서 고친 값으로 저장한다", async ({ page }) => {
  await ask(page, "앞으로 자세히 설명해 줘");
  await expect(page.getByRole("heading", { name: "승인이 필요해요" })).toBeVisible();
  await accessible(page);
  await page.screenshot({ path: "e2e/screenshots/approval.png", fullPage: true });
  await page.getByLabel("고치기").check();
  await page.getByLabel("설명 깊이").selectOption("짧게");
  await page.locator(".card").getByRole("button", { name: "보내기" }).click();
  await expect(answers(page)).toContainText("설명 깊이 '짧게' 저장");
});

test("승인 카드에서 거절하면 하지 않는다", async ({ page }) => {
  await ask(page, "앞으로 자세히 설명해 줘");
  await page.getByLabel("거절").check();
  await page.locator(".card").getByRole("button", { name: "보내기" }).click();
  await expect(answers(page)).toContainText("확인한 내용을 정리했어요");
  await expect(answers(page)).not.toContainText("이번 차례에 한 일");
});
```

- [ ] **Step 3: 확인 (pytest)**: 명령 A. Expected: `679 passed`, 오류 0.

- [ ] **Step 4: 확인 (Playwright, C9)**

```bash
set -o pipefail
mkdir -p web/e2e/screenshots
docker compose --profile e2e build api-e2e web-e2e playwright
docker compose --profile e2e run --rm playwright 2>&1 | tail -8
docker compose --profile e2e down
ls ~/Library/Caches/ms-playwright   # C12: 시작 때 목록과 같아야 한다
```

Expected [실측 11-07]: `4 passed`(질문→답·근거·화물 카드 약 3.3초, 선택지, 승인 고치기, 승인 거절), `web/e2e/screenshots/`에 `answer.png`·`choice.png`·`approval.png`. 처음 돌렸을 때 가짜 작성자가 지시문 속 `[BL1]` 예를 화물로 착각해 둘이 실패했고, 화물 줄(`[BL1]:`)로 고른 뒤 넷 모두 통과했다(위 코드가 고친 것).

- [ ] **Step 5: 스크린샷을 눈으로 본다**: 한글이 네모로 나오지 않는지, 화면에 DEMO 번호 말고 다른 번호가 없는지.

- [ ] **Step 6: 커밋** (코드와 스크린샷을 나눈다)

```bash
git add e2e/fake_api.py Dockerfile .dockerignore docker-compose.yml web/e2e.Dockerfile web/playwright.config.ts web/e2e/flows.spec.ts web/package.json web/package-lock.json tests/test_docker.py
git commit -m "test(web): Playwright 주요 흐름·접근성 검사를 공식 이미지와 바깥 막힌 compose 망에서 돌림"
git add web/e2e/screenshots/answer.png web/e2e/screenshots/choice.png web/e2e/screenshots/approval.png
git commit -m "docs: 화면 주요 흐름 스크린샷 (가짜 모델, DEMO 번호)"
```

장부에 확인점 줄을 남긴다: `CP3 (11-12): T8~T9 done? <yes/no, cut applied>`.

---
### Task 10: 배포 준비 (done 4.4, C10)

**배울 것:** GitHub Actions의 WIF는 워크플로가 받은 OIDC 토큰(`permissions: id-token: write`)을 GCP 서비스 계정 자격으로 바꾼다. 키 파일이 저장소·비밀값에 없다. `google-github-actions/auth`의 입력은 `workload_identity_provider`와 `service_account`다 [문서 11-07 v3.0.0 action.yml·README]. Cloud Run 배포는 `gcloud run deploy --image --region --allow-unauthenticated --port --timeout --set-env-vars --set-secrets KEY=비밀:버전`, 표 준비는 `gcloud run jobs deploy --command --args`와 `gcloud run jobs execute --wait`다 [문서 11-07 gcloud 참조]. 브라우저는 Cloud Run을 바로 부르고(인증은 앱 층의 JWT), Vercel 함수로 SSE를 중계하지 않는다.

**Files:**
- Create: `.github/workflows/deploy.yml`, `docs/deploy.md`

- [ ] **Step 1: 워크플로**: `.github/workflows/deploy.yml` (새 파일)

```yaml
# 손으로 시작하는 배포 (done 4.4, 설계 13절, 계획 4b Task 10). push로는 돌지 않는다.
# API 이미지를 amd64로 빌드해 Artifact Registry에 올리고, 표 준비 작업(Cloud Run job)을 돌린 뒤 Cloud Run에 배포한다.
# GCP 인증은 키 파일 없이 WIF(GitHub OIDC 토큰 → 서비스 계정)로 한다. 키는 Secret Manager에만 있다.
# [주의] 저장소 변수 MARVIA_DEPLOY_ENABLED가 'true'가 아니면 아무것도 하지 않는다(계정·키를 만들기 전 실수 방지).
#        필요한 저장소 변수와 GCP 준비는 docs/deploy.md에 있다.
name: deploy

on:
  workflow_dispatch:

permissions:
  contents: read
  id-token: write # WIF: GitHub OIDC 토큰을 받는다

concurrency:
  group: deploy
  cancel-in-progress: false

jobs:
  api:
    if: vars.MARVIA_DEPLOY_ENABLED == 'true'
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    env:
      IMAGE: ${{ vars.GCP_REGION }}-docker.pkg.dev/${{ vars.GCP_PROJECT }}/marvia/api:${{ github.sha }}
    steps:
      # [주의] 바깥 액션은 커밋 해시로 고정한다. 태그는 옮겨질 수 있다
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: google-github-actions/auth@7c6bc770dae815cd3e89ee6cdf493a5fab2cc093 # v3.0.0
        with:
          workload_identity_provider: ${{ vars.GCP_WIF_PROVIDER }}
          service_account: ${{ vars.GCP_DEPLOY_SA }}
      - uses: google-github-actions/setup-gcloud@aa5489c8933f4cc7a4f7d45035b3b1440c9c10db # v3.0.1
      - name: 이미지 빌드·올리기 (Cloud Run은 amd64)
        run: |
          gcloud auth configure-docker "${{ vars.GCP_REGION }}-docker.pkg.dev" --quiet
          docker build --platform linux/amd64 --target runtime -t "$IMAGE" .
          docker push "$IMAGE"
      - name: 표 준비 (Cloud Run job, 여러 번 돌려도 같다)
        run: |
          gcloud run jobs deploy marvia-prepare --image "$IMAGE" --region "${{ vars.GCP_REGION }}" \
            --command python --args=-m,marvia.prepare_db \
            --set-secrets "MARVIA_DATABASE_URL=marvia-database-url:latest,MARVIA_DATA_KEY=marvia-data-key:latest"
          gcloud run jobs execute marvia-prepare --region "${{ vars.GCP_REGION }}" --wait
      - name: API 배포
        run: |
          gcloud run deploy marvia-api --image "$IMAGE" --region "${{ vars.GCP_REGION }}" \
            --allow-unauthenticated --port 8080 --timeout 300 \
            --set-env-vars "MARVIA_AUTH=supabase,MARVIA_SUPABASE_URL=${{ vars.MARVIA_SUPABASE_URL }},MARVIA_WEB_ORIGIN=${{ vars.MARVIA_WEB_ORIGIN }},MARVIA_GRAPH=off" \
            --set-secrets "MARVIA_DATABASE_URL=marvia-database-url:latest,MARVIA_DATA_KEY=marvia-data-key:latest,MARVIA_ANTHROPIC_API_KEY=marvia-anthropic-key:latest,MARVIA_VOYAGE_API_KEY=marvia-voyage-key:latest,MARVIA_OWNER_IDS=marvia-owner-ids:latest"
```

- [ ] **Step 2: 문법 검사**

```bash
docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667 -no-color; echo "exit $?"
```

Expected: `exit 0` [실측 11-07]. (`-color=never`는 이 판에서 받지 않는다. `-no-color`를 쓴다.)

- [ ] **Step 3: 절차서**: `docs/deploy.md` (새 파일). "로컬 확인" 표의 값은 T8·T9에서 실제로 나온 값으로 바꿔 적는다. 아래는 계획을 쓸 때 잰 값이다.

````markdown
# Marvia v2 배포 절차 (done 4.4, 설계 13절, 계획 4b Task 10)

API는 Cloud Run(서울, `asia-northeast3`), 화면은 Vercel, DB는 Supabase, 그래프는 AuraDB 무료판(지금 기본값 `MARVIA_GRAPH=off`라 처음 배포에는 필요 없다)이다. 키는 GCP Secret Manager에만 두고 저장소에는 이름만 둔다. GitHub Actions는 키 파일 없이 WIF(GitHub OIDC 토큰 → 서비스 계정)로 GCP에 들어간다.

계정·프로젝트·키를 만드는 일과 실제 배포는 직접 한다. 아래 "직접 할 일"은 아직 하지 않았고, "로컬 확인"은 계정 없이 이 컴퓨터에서 실제로 돌린 명령과 결과다.

## 로컬 확인 (dry-run, 11-07 실측)

| 확인 | 명령 | 결과 |
|---|---|---|
| amd64 이미지 빌드 | `docker buildx build --platform linux/amd64 --target runtime -t marvia-api:amd64 --load .` | 성공, 약 49초 (onnxruntime·kiwipiepy amd64 wheel 있음) |
| 실행 사용자 | `docker run --rm marvia-api:local id -u` | `10001` |
| 이미지 안 규칙·지시문 | `docker run --rm marvia-api:local python -c "from marvia.tools.rules import load_rules; from marvia.prompts import render; load_rules('agent'); render('agent')"` | 성공 |
| 이미지에 없는 것 | `docker run --rm marvia-api:local sh -c 'ls -a /app'` | `.env`·`.local`·`scripts`·`tests`·`e2e` 없음 |
| 크기 | `docker images marvia-api:local` | 1.07GB |
| 로그인 설정 없음 | `docker run --rm -e MARVIA_AUTH=supabase marvia-api:local` | `RuntimeError: MARVIA_SUPABASE_URL이 없어 로그인을 확인할 수 없습니다` |
| Cloud Run에서 개발 로그인 | `docker run --rm -e K_SERVICE=x -e MARVIA_AUTH=dev -e MARVIA_DEV_TOKEN=t marvia-api:local` | `RuntimeError: Cloud Run에서는 개발 로그인(MARVIA_AUTH=dev)으로 시작하지 않습니다` |
| 키 없음 | `uv run pytest -q tests/graph/test_server.py -k without_model` | 시작 거절 시험 통과 |
| `PORT`로 듣기 | e2e 이미지를 `-e PORT=9090`으로 띄우고 컨테이너 안에서 `/health` | `{"ok":true}`, HEALTHCHECK healthy 약 8초 |
| compose 앱(표 준비 → API) | 버리는 키로 `docker compose --profile app up -d db neo4j prepare api` | prepare `표 준비 끝`, api healthy 6초, `/health` 200, 토큰 없는 `/agui` 401 |
| 배포 워크플로 문법 | `docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667 -no-color` | 오류 0 |

계정이 필요한 명령(gcloud, Vercel, Supabase)은 돌리지 않았다. 아래 gcloud 명령의 모양은 참조 문서(`run deploy`, `run jobs deploy`, `run jobs execute`, `artifacts repositories create`, `secrets create`, `secrets versions add`)와 google-github-actions/auth v3.0.0 README로 확인했다 [문서 11-07]. `services enable`과 IAM 역할 이름은 확인하지 않았다 [추정].

## 직접 할 일 1: Supabase (DB, 로그인)

1. 프로젝트를 만들고(지역은 서울에 가까운 곳), Authentication에서 Google 제공자를 켠다. 내 계정으로 한 번 로그인한 뒤 새 가입을 막는다(Authentication 설정의 가입 허용 끔). 내 사용자 id(UUID)를 적어 둔다. 이것이 `MARVIA_OWNER_IDS`다.
2. DB 주소는 공유 풀러의 **세션 모드(5432)** 주소를 쓴다. [왜] 무료판 직접 연결은 IPv6뿐이고, 트랜잭션 모드(6543)는 prepared statement를 받지 않는다(계획 4b 사전 부검 3번, Supabase 연결 문서).
3. 표와 코퍼스를 옮긴다. 코퍼스는 다시 임베딩하지 않고 로컬 표를 그대로 옮긴다(Voyage 비용 없음):

    ```bash
    docker compose exec -T db pg_dump -U marvia -d marvia -t corpus_units --no-owner > corpus_units.sql
    # 받은 Supabase 주소로 (주소는 셸에만, 저장소·기록에 남기지 않는다)
    psql "$SUPABASE_SESSION_URL" -c 'CREATE EXTENSION IF NOT EXISTS vector'
    psql "$SUPABASE_SESSION_URL" -f corpus_units.sql
    ```

    나머지 표(감시, 대화 기록, 장기 기억)는 배포 워크플로의 `marvia-prepare` 작업(`python -m marvia.prepare_db`)이 만든다.

## 직접 할 일 2: GCP (Cloud Run, Artifact Registry, Secret Manager, WIF)

`PROJECT_ID`, `REPO`(예: `HJU5022/Marvia`)를 정한 뒤:

```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com iamcredentials.googleapis.com --project "$PROJECT_ID"
gcloud artifacts repositories create marvia --repository-format=docker --location=asia-northeast3 --project "$PROJECT_ID"
# 키는 값 파일을 셸에서 바로 넣는다. 화면·기록에 찍지 않는다
for name in marvia-database-url marvia-data-key marvia-anthropic-key marvia-voyage-key marvia-owner-ids; do
  gcloud secrets create "$name" --replication-policy=automatic --project "$PROJECT_ID"
done
printf %s "$VALUE" | gcloud secrets versions add marvia-data-key --data-file=- --project "$PROJECT_ID"   # 키마다 한 번씩
```

WIF는 google-github-actions/auth v3.0.0 README의 "Workload Identity Federation through a Service Account" 순서를 따른다 [문서 11-07]:

```bash
gcloud iam service-accounts create "marvia-deploy" --project "${PROJECT_ID}"
gcloud iam workload-identity-pools create "github" --project="${PROJECT_ID}" --location="global" --display-name="GitHub Actions Pool"
gcloud iam workload-identity-pools providers create-oidc "marvia" \
  --project="${PROJECT_ID}" --location="global" --workload-identity-pool="github" \
  --display-name="Marvia repo" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --attribute-condition="assertion.repository == '${REPO}'" \
  --issuer-uri="https://token.actions.githubusercontent.com"
POOL=$(gcloud iam workload-identity-pools describe "github" --project="${PROJECT_ID}" --location="global" --format="value(name)")
gcloud iam service-accounts add-iam-policy-binding "marvia-deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="${PROJECT_ID}" --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL}/attribute.repository/${REPO}"
gcloud iam workload-identity-pools providers describe "marvia" --project="${PROJECT_ID}" --location="global" --workload-identity-pool="github" --format="value(name)"
```

서비스 계정에는 배포에 필요한 역할만 준다: Cloud Run 관리(`roles/run.admin`), 서비스 계정 사용(`roles/iam.serviceAccountUser`), Artifact Registry 쓰기(`roles/artifactregistry.writer`), 비밀 읽기(`roles/secretmanager.secretAccessor`, Cloud Run 실행 계정에도). 역할 이름은 GCP IAM 문서로 다시 확인한다 [추정].

## 직접 할 일 3: GitHub 저장소 변수와 배포

저장소 Settings → Variables(비밀이 아닌 값): `GCP_PROJECT`, `GCP_REGION=asia-northeast3`, `GCP_WIF_PROVIDER`(위 마지막 명령의 값), `GCP_DEPLOY_SA=marvia-deploy@<프로젝트>.iam.gserviceaccount.com`, `MARVIA_SUPABASE_URL`, `MARVIA_WEB_ORIGIN`(Vercel 주소), 마지막에 `MARVIA_DEPLOY_ENABLED=true`.

Actions 탭에서 `deploy` 워크플로를 손으로 돌린다(`workflow_dispatch`만 있다. push로는 돌지 않는다). 순서: amd64 이미지 빌드·올리기 → `marvia-prepare` 작업으로 표 준비 → `marvia-api` 배포(요청 시간 제한 300초, 로그인은 Supabase 토큰).

배포 뒤 확인: `curl https://<cloud-run 주소>/health` → `{"ok":true}`, 토큰 없는 `POST /agui` → 401.

## 직접 할 일 4: Vercel (화면)

프로젝트의 Root Directory를 `web`으로, 환경 변수 `NEXT_PUBLIC_API_URL`(Cloud Run 주소), `NEXT_PUBLIC_AUTH=supabase`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`(공개 키)를 넣는다. 브라우저는 Cloud Run을 바로 부르고(Vercel 함수로 SSE를 중계하지 않는다), API는 `MARVIA_WEB_ORIGIN` 하나만 CORS로 연다. Supabase Authentication의 Redirect URL에 Vercel 주소를 넣는다.

## 직접 할 일 5: AuraDB (그래프를 켤 때만)

`MARVIA_GRAPH=on`으로 바꿀 때만 필요하다. 무료판 한도와 쉬는 조건은 확인하지 못했다 [미확인]. 그래프는 단위 7,412개, `REFERS_TO` 18,099개다(계획 3b). 켜면 `MARVIA_NEO4J_URL`·`MARVIA_NEO4J_PASSWORD`를 비밀로 더하고 `scripts/build_graph.py`로 적재한다.

## 열지 않는 것

- 규정 검색 MCP HTTP(`scripts/serve_mcp.py`)는 배포에서 열지 않는다. 에이전트는 같은 프로세스 안의 메모리 통로로 부른다(설계 9절, 14절 "MCP 공개 → 내부 도구로만"). 연다면 배포 주소의 Host 검사를 먼저 본다.
- 바깥 메시지 발송 도구는 만들지 않았다(설계 6.3에서 2차, 보낼 통로가 없음).
````

- [ ] **Step 4: 커밋**

```bash
git add .github/workflows/deploy.yml docs/deploy.md
git commit -m "docs: 배포 절차서와 손으로 시작하는 배포 워크플로 (WIF, Cloud Run, 로컬 확인 기록)"
```

---

### Task 11: 문서 (11-14)

**Files:**
- Modify: `docs/specs/2026-10-28-marvia-v2-design.md`, 이 계획 문서(결과 표)

- [ ] **Step 1: 설계 문서에 날짜 줄**: 아래 diff대로 3절·8절·10절·11절·13절·변경 기록을 고친다.

````diff
--- a/docs/specs/2026-10-28-marvia-v2-design.md
+++ b/docs/specs/2026-10-28-marvia-v2-design.md
@@ -43,7 +43,7 @@
 ```
 [화면] Next.js ── AG-UI 이벤트로 계획·진행·선택지·승인 카드를 실시간 표시
    │  AG-UI (SSE)
-[API] FastAPI ── ag-ui-langgraph 엔드포인트, 로그인
+[API] Starlette ── AG-UI 엔드포인트(ag-ui-protocol로 직접), 로그인 (11-07 바꿈: FastAPI·ag-ui-langgraph 대신, 10절)
    │
 [에이전트] LangGraph
   메인 그래프 (직접 짠 StateGraph) ── 루프: `create_agent` + 도메인 도구 + 미들웨어(할 일 목록, 승인, 호출 한도)
@@ -268,9 +268,11 @@
 - Postgres(Supabase)
   - `users`, `cargos`(사용자별 화물: 가린 번호와 해시, 마지막 상태), `corpus_units`(`unit_id`, 원문, 맥락 문장, 임베딩, 키워드 tsvector, 메타데이터)
   - LangGraph checkpointer·Store 테이블은 라이브러리가 만든다. 실제 실행은 Postgres(`PostgresSaver`·`PostgresStore`)에 두고 시험은 메모리를 쓴다 (11-06)
-  - 체크포인트는 AES-GCM(`EncryptedSerializer`)으로 암호화한다. 키는 `MARVIA_DATA_KEY`에서 HKDF(info `marvia-checkpoint`)로 뽑고, 키가 없거나 틀리면 실행 길이 열리기 전에 멈춘다. 문자열 칸 `text`·`answer`는 라이브러리가 직렬화기를 거치지 않고 `checkpoints` 표에 그대로 넣어 평문으로 남는다. 서버 가장자리에서 되돌려 푸는 화면 계획에서 닫는다 (done 4.1) (11-06)
+  - 체크포인트는 AES-GCM(`EncryptedSerializer`)으로 암호화한다. 키는 `MARVIA_DATA_KEY`에서 HKDF(info `marvia-checkpoint`)로 뽑고, 키가 없거나 틀리면 실행 길이 열리기 전에 멈춘다. 문자열 칸은 라이브러리가 직렬화기를 거치지 않고 `checkpoints` 표에 그대로 넣으므로, 실제 번호가 든 `text`(원문)·`answer`(되돌린 답)는 저장하지 않는 칸(`UntrackedValue`)으로 둔다. 답은 그 차례의 실행 결과에서만 읽는다. 끼어들기·재개를 지난 뒤 체크포인트 세 표에 시험 번호가 0줄이다 (11-06, 11-07 R-035)
   - 감시 표(`watches`, `watch_events`): 실제 번호는 앱이 Fernet으로 암호화해 두고 같은 번호 검사는 HMAC-SHA256 해시로 한다. 암호화 키와 해시 키는 `MARVIA_DATA_KEY`에서 HKDF로 따로 뽑는다. 키가 없거나 Fernet 키 모양이 아니면 감시를 끈다. 변화는 답에 보인 뒤에만 본 것으로 표시한다. `forget_user`가 한 사용자의 감시와 변화 기록을 지운다 (11-06)
-  - 마이그레이션은 SQL 파일로 두고 API 시작 때 적용한다
+  - 마이그레이션은 SQL 파일로 둔다. 운영은 표 준비를 한 번 도는 명령(`python -m marvia.prepare_db`, compose `prepare`, Cloud Run 작업)으로 하고 서버 시작에서는 하지 않는다 (11-07)
+  - 검색·조문 조회는 autocommit 읽기 연결 풀에서 부를 때마다 연결을 빌린다. 읽은 뒤 열린 트랜잭션(idle in transaction)이 남지 않는다 (11-07 R-066)
+  - 계정 삭제는 감시 목록과 변화, 장기 기억(품목 카드·설정), 그 사용자의 대화 기록을 함께 지운다. 화물 하나의 감시는 `unwatch_cargo`가 승인 뒤에 끈다 (11-07 R-033)
 - Store 네임스페이스: `("users", uid, "items")` 품목 카드, `("users", uid, "prefs")` 설명 깊이 같은 설정(값은 규칙의 목록 안에서만)
 - 품목 카드는 승인 뒤에만 Store `("users", uid, "items")`에 저장한다. 이름은 짧게(규칙 `memory.max_item_name`), 화물 번호·토큰·문장 부호를 넣지 않는다 (11-06).
 - 저장 기준: 승인된, 다음 수입에도 유효한 사실만 저장한다. 이번 대화 값은 state에만 둔다. B/L 원문과 지시문처럼 보이는 문장은 저장하지 않는다.
@@ -288,6 +290,7 @@
 - Next.js(App Router). AG-UI 이벤트를 받아 그린다.
 - 구성: 채팅 / 계획 진행(할 일 목록과 현재 단계) / "이렇게 읽었어요" 표시 / 선택지 카드 / 승인 카드 / 답변과 근거 패널(조문 원문, 시행일, 출처 링크) / 화물 카드(통관 단계, ETA, 등급).
 - 로그인: Supabase Auth. 사용자 id로 thread와 Store를 나눈다.
+- 구현 (11-07, 계획 4b): 서버는 ag-ui-langgraph 어댑터 없이 `ag-ui-protocol` 1.0.0의 이벤트로 `POST /agui` 하나를 직접 쓴다(어댑터는 화면이 보낸 메시지·state를 그래프 입력에 합치고 공책 전체를 보낸다). 받는 값은 마지막 사용자 글과 재개 값뿐이고, 보내는 값은 허용 목록(할 일, 읽은 번호, 화물 카드, 근거 패널, 카드)뿐이다. 사용자는 서명을 확인한 토큰(ES256, JWKS)과 소유자 목록에서만 꺼내고, 대화 키는 서버가 "사용자/이름"으로 만든다. 화면은 Next.js 16 한 쪽이고 SSE를 `fetch`로 읽는다(CopilotKit·`@ag-ui/client` 없이). 화물 카드의 ETA·등급은 선박 위치 조회와 함께 2차로 미루고 카드에 그렇게 적는다. 승인 카드에서 고친 값과 거절 글은 서버가 그 대화의 가림 표로 다시 가린 뒤 재개하고, 대화에 없던 번호는 실행하지 않는다. 주요 흐름 넷과 접근성(axe)은 공식 Playwright 이미지 안에서 가짜 모델로 시험한다
 
 ## 11. 평가와 관측
 
@@ -303,7 +306,7 @@
 - LLM 채점은 사람 채점 10건과 일치율을 확인한 뒤 쓴다. 확인 전에는 "LLM 채점, 사람 일치 미확인"을 값과 함께 붙인다. 일치율은 계산 줄을 맥락에 넣지 않은 첫 점수 파일(`ae1891c` 답)에서는 계산 문항을 뺀 7건으로, 계산·화물 줄을 넣은 점수 파일(`contexts_rule: cited+calc`)에서는 10건 모두로 센다. 사람 채점이 충실도에만 있으므로 정밀도·재현율은 늘 미확인이다.
 - GitHub Actions (11-06 구현): 키 없이 린트·형식·타입·시험을 돌리고, 저장소에 커밋한 파생 값 줄을 지금 지표 코드로 다시 채점해 바닥값 아래면 실패시킨다. 바닥값은 코드가 기준 실행에서 만들고(`run_eval.py floors`), 저장한 결과가 평가셋 문항을 모두 덮어야 통과한다. 모델 응답은 저장소에 두지 않으므로 응답 재생은 하지 않는다.
 - 간접 주입 시험 (11-06 구현): promptfoo가 Docker 안에서 다섯 통로(검색 결과 본문, 저장된 품목 카드, 공식 페이지 제목, 서류 사진 글, 사용자 글)에 같은 주입 글을 넣고, 같은 사례를 pytest가 가짜 모델로 키 없이 돈다. 차례가 실제로 돌지 않은 경우는 통과로 치지 않는다. 실제 모델 5/5 통과, 주입을 따르는 가짜 모델 5/5 실패 [실측 11-06].
-- Langfuse v4: 노드·도구·LLM 호출마다 트레이스(OTel), 프롬프트는 레포 파일이 원본이고 Langfuse에 같은 글을 등록한다, 평가 점수를 트레이스에 붙인다. 아직 하지 않았다(키, 트레이스 가림 R-010·R-022·R-039 시험이 먼저).
+- Langfuse v4: 노드·도구·LLM 호출마다 트레이스(OTel), 프롬프트는 레포 파일이 원본이고 Langfuse에 같은 글을 등록한다, 평가 점수를 트레이스에 붙인다. 아직 하지 않았다(키). 트레이스 가림 문은 닫았다: 콜백 값을 걸어 다니며 번호 덩어리를 가리는 `trace.scrub`(Langfuse `mask=` 훅 모양)과, 감시 변화·Send 두 갈래·화물 조회·직접 입력·조사 서브에이전트·답을 지나는 기록 콜백 시험이 있다 (11-07 R-010·R-022·R-039).
 
 ## 12. 신뢰 경계
 
@@ -324,9 +327,9 @@
 | 에이전트 | LangGraph 1.x, langgraph-checkpoint-postgres, PostgresStore |
 | LLM | Anthropic API, 기본 `claude-haiku-5-5`. `init_chat_model`로 만들어 모델 이름만 바꾸면 다른 모델로 돈다. 구조화 출력은 `method="json_schema"` |
 | 임베딩·리랭커 | Voyage AI API 직접: 임베딩 `voyage-4`, 리랭커 `rerank-3` (11-02 문서 확인: 두 모델 모두 무료 2억 토큰, 그 뒤 백만 토큰당 $0.06·$0.05) |
-| 로컬 | docker compose: api, Postgres + pgvector, Neo4j |
+| 로컬 | docker compose: Postgres + pgvector, Neo4j, profile app(표 준비 → api :8080, 화면 :3000), profile e2e(가짜 모델 API, 화면, Playwright, 바깥 막힌 망). 모든 포트는 127.0.0.1, 이미지는 digest 고정 (11-07) |
 | 배포 | API Cloud Run(서울), 화면 Vercel, DB Supabase, 그래프 AuraDB 무료판, 해수부 릴레이는 기존 Cloud Run 유지 |
-| CI/CD | GitHub Actions, WIF(키 파일 없이 GCP 인증), Secret Manager, Docker 멀티스테이지(non-root) |
+| CI/CD | GitHub Actions, WIF(키 파일 없이 GCP 인증), Secret Manager, Docker 멀티스테이지(non-root, uid 10001). 배포 워크플로는 손으로만 시작하고(`workflow_dispatch`), 절차와 로컬 확인 기록은 `docs/deploy.md` (11-07) |
 | 저장소 규칙 | `main`은 v1 동결, 작업은 `v2`, 1차 완성 뒤 검토를 거쳐 `main`에 합친다 |
 
 ## 14. 일정 (목표: 11-01 일요일)
@@ -376,3 +379,4 @@
 - 11-06: Postgres 체크포인터·Store, 체크포인트 AES-GCM 암호화(`text`·`answer` 제외), 감시 표 암호화와 해시, `MARVIA_DATA_KEY` (8절)
 - 11-06: 저장 기억·공식 페이지·사진 글은 데이터, 바깥 호스트 허용 목록, 키 비출력 (12절)
 - 11-07: 계획 3b 구현 반영. 별표 읽기, 그래프 확장 자리, GraphRAG 구현 범위, 실제 UNI-PASS 클라이언트, MCP 구현 (5.2, 5.4, 5.5, 7.2, 9). 측정 결과(11절)는 충전 뒤 더한다
+- 11-07: 계획 4b. 원문·답 저장 안 함(8절), 읽기 연결 풀·표 준비 명령·계정 삭제(8절), AG-UI 직접 엔드포인트와 Starlette(3절·10절), 트레이스 가림(11절), 로컬 compose와 배포 워크플로(13절)
````

- [ ] **Step 2: 이 문서 끝에 "실행 결과" 표**: 태스크마다 커밋, 시험 수, 확인점에서 자른 것, C1~C12 판정(통과·못 넘음과 근거)을 적는다.

- [ ] **Step 3: done 체크리스트 증거 줄(저장소 밖 진행 기록)**: 4.1(화면, R-035·R-048·R-033 닫힘), 4.2(Playwright 4 흐름, 스크린샷), 4.3(이미지, compose), 4.4(절차서, 워크플로, 실제 배포는 직접 할 일), 1.4(재개 다시 가림 닫힘, 바깥 발송 도구는 만들지 않은 이유), 3.9(가림 문 닫힘, Langfuse는 키 때문에 계속 미룸).

- [ ] **Step 4: 커밋**

```bash
git add docs/specs/2026-10-28-marvia-v2-design.md docs/plans/2026-11-07-marvia-v2-plan-4b-screen-deploy.md
git commit -m "docs: 설계에 계획 4b 반영(저장 안 하는 칸, 읽기 풀, AG-UI 직접 엔드포인트, 가림 문, 배포)"
```

---
## 끝나면 되는 것

- 체크포인트 세 표에 실제 번호 0줄(C1), 읽기 연결 idle in transaction 0(C2), 콜백 값 가림(C3), 로그인 없는 요청·남의 대화 거절과 서버 길 user_id 강제(C4), 승인 카드에서 돌아온 번호 다시 가림(C5).
- `python -m marvia.server`가 AG-UI 이벤트로 계획 진행·읽은 번호·화물 카드·근거·선택지·승인 카드·답을 보내고, 화면이 그것을 그린다. 감시 끄기와 계정 삭제가 있다.
- compose로 API·화면이 이 컴퓨터에서 돌고, Playwright 주요 흐름 넷·axe·스크린샷이 Docker 안에서 통과한다.
- 배포 절차서와 손으로 시작하는 워크플로가 있고, 계정 없이 돌릴 수 있는 확인은 모두 돌린 결과가 적혀 있다. 실제 배포는 직접 할 일이다.

## 설계와 대조

| 설계 | 이 계획 | 차이 |
|---|---|---|
| 3절 "[API] FastAPI ── ag-ui-langgraph 엔드포인트" | Starlette, `ag-ui-protocol`로 직접 쓴 엔드포인트 | T11에서 날짜와 함께 고친다(결정과 근거) |
| 6.3 질문·승인 두 통로, 시간 초과는 화면이 잰다 | 카드 둘, 선택지 시간 제한 `rules/server.yaml question.timeout_s` | 없음 |
| 8절 `text`·`answer` 평문 | 저장하지 않는 칸 | T11에서 고친다 |
| 8절 "마이그레이션은 API 시작 때 적용" | `prepare_db` 한 번 도는 명령 | T11에서 고친다 |
| 10절 화물 카드(통관 단계, ETA, 등급) | 단계·항구·시각·출처, ETA·등급은 2차 표시 | D3 |
| 10절 로그인 Supabase | 서버 ES256 확인(시험 있음), 화면 구글 로그인(타입 검사·빌드까지) | 실제 로그인은 프로젝트를 만든 뒤 |
| 11절 Langfuse | 가림 문만 닫고 연결은 미룸 | 키 없음 |
| 12절 실제 번호는 트레이스에 가지 않는다 | `scrub`과 시험, 연결은 미룸 | 없음 |
| 13절 compose: api, Postgres, Neo4j | + 화면, 표 준비, e2e | 없음 |
| 13절 배포(Cloud Run 서울, Vercel, Supabase, AuraDB, WIF, Secret Manager) | 절차서와 워크플로, 로컬 확인 | 실제 배포는 직접 할 일 |
| 14절 빼는 순서 "AG-UI(단순 SSE 채팅으로)", "MCP 공개(내부 도구로만)", "자동 배포(손 배포)" | 엔드포인트가 이미 단순 SSE 모양, MCP HTTP는 배포에서 열지 않음, 배포는 손으로 시작 | 없음 |

## 확인하지 못한 것

- 실제 Supabase 프로젝트로 로그인(JWKS를 네트워크로 받는 길, 구글 로그인 돌아오기) [미확인]. 서버 확인은 시험 안에서 만든 ES256 키로만 봤다.
- gcloud·Vercel·Supabase 명령은 계정이 없어 돌리지 않았다. `services enable`과 IAM 역할 이름은 문서로 확인하지 않았다 [추정].
- 브라우저가 끊겼을 때 그래프가 다음 갱신에서 멈추는지(멈춤 깃발) [추정, 시험 없음].
- Starlette가 동기 iterator를 스레드를 바꿔 가며 부를 때의 ContextVar 오류는 작업 스레드 하나로 피했다. 오류 자체를 재현하지는 않았다 [추정].
- 실제 모델로 화면 한 차례(충전 전). 화면과 스크린샷은 가짜 모델이다.
- Cloud Run·Vercel 앞에서 SSE가 모이지 않고 흐르는지 [추정]. 이 컴퓨터의 Next standalone과 Starlette에서는 계획이 답보다 먼저 보였다 [실측].
- 풀 크기 8과 Supabase 세션 풀러 연결 한도의 관계 [추정].
- AuraDB 무료판 한도와 쉬는 조건 [미확인].
- DB 이미지를 CI digest로 바꿀 때 기존 데이터 폴더가 그대로 읽히는지 [추정, 같은 Postgres 16].
- 중간 커밋 중 T2a·T5a·T5b·T8 상태만 따로 돌렸다. 나머지 중간 상태는 마지막 상태(679 통과)와 diff로만 맞췄다. 화면은 단계마다 `tsc`만, `next build`와 Playwright는 마지막 상태로 돌렸다.
- amd64 이미지는 빌드만 했고 실행하지 않았다.

## 실행 결과 (11-07)

시험 수는 626에서 740으로 늘었다(마지막 상태에서 `MARVIA_REQUIRE_DB=1 uv run pytest -q` 740 통과, 종료 코드 0, ruff·형식·pyright 0). 모델은 모두 가짜였고 유료 호출은 없다. 커밋은 `32f05e6` 다음부터 `ca8e669`까지 `v2`에만 올렸다.

### 확인점

| 확인점 | 목표일 | 결과 |
|---|---|---|
| CP1 (T0~T4: 닫을 문 다섯, 로그인) | 11-09 | 11-07에 끝남. 자르기 없음 |
| CP2 (T5~T7: 서버 엔드포인트, 감시 끄기·계정 삭제, 화면) | 11-11 | 11-07에 끝남. 자르기 없음 |
| CP3 (T8~T9: 이미지, compose, Playwright) | 11-12 | 11-07에 끝남. 자르기 없음 |
| T10 배포 준비, T11 문서 | 11-14 | T10 11-07에 끝남. T11은 이 절로 마무리 |

### 태스크별

| 태스크 | 커밋 | 시험 수 (끝난 뒤) | 비고 |
|---|---|---|---|
| T1 원문·답 저장 안 함 | `98db365`, `e81941b` | 626 | `text`·`answer`를 저장하지 않는 칸으로. 먼저 돌린 시험이 `assert ('text' not in {'text': 'DEMO0001 ...'` 로 실패했다 |
| T2 읽기 연결 풀 | `4163e6d`, `8a0757e`, `4ad2616`, 보정 `997e994`, `f547915` | 650 | 검색·조문 조회가 부를 때마다 autocommit 연결을 빌린다. 질의는 MCP 상한에서 자른다 |
| T3 트레이스 가림 | `6caf00f`, 보정 `e5aef9c`, `784c28a`, `9e987e7` | 654 | `scrub`. Langfuse가 `mask(data=...)`로 부르는 모양에 맞췄다 |
| T4 로그인·서버 길 | `3f1801f`, `2c813f1`, `cca50c6`, `e7edf74`, 보정 `df21018`, `afc0bc5` | 695 | ES256 JWKS, 소유자 목록, 서버 표시가 붙은 그래프는 `user_id` 없이 멈춤, LangSmith 환경 변수가 켜져 있으면 시작 거절 |
| T5a 엔드포인트 | `6ad54b1`, 보정 `9dfd788`, `7c71ab5`, `041aeff`, `d3f1476`, `fa45134`, `a1362d1` | 723 | `POST /agui`, `GET /health`, 허용 목록 보기, thread 잠금 |
| T5b 재개 값 다시 가림 | `d096f17`, 보정 `4ace552`, `6c17a7c`, `569f200` | 701 (당시) | 고친 인자·거절 글을 그 대화의 가림 표로 다시 가림 |
| T6 감시 끄기·계정 삭제 | `b062588`, `347e6a9`, 보정 `0a9b059`, `387f4ba`, `cc1aa92`, `878918c` | 732 | `unwatch_cargo`, `DELETE /account` |
| T7 화면 | `097afd2`, `37916d0`, `d8128b4`, `b1aec4e`, `fdc91ee`, `7614b42`, `521c8dc`, 보정 `a9f7b45`, `d97356b`, `ed31350`, `a5a02f5` | (화면은 `tsc`·`next build`) | Next.js 한 쪽. 구글 로그인은 타입 검사와 빌드까지 |
| T8 이미지·compose | `710d781`, 보정 `28844ae`, `9c7a573` | 733 | uid 10001, 허용 목록 `.dockerignore`, digest 고정, 포트 127.0.0.1 |
| T9 Playwright | `fc9853d`, `3e42f4c`, 보정 `c3f5dd4`, `6e064fd`, `ca8e669` | 740 | 흐름 넷, axe, 스크린샷 셋 |
| T10 배포 준비 | `4c36bed`, 보정 `aab1f0a` | 735 (당시) | 손으로 시작하는 워크플로, `docs/deploy.md` |

한 커밋의 코드 파일은 가장 많은 것이 10개(`8a0757e`)였다. 잠금 파일·`docs/`·`graphify-out/`·PNG는 세지 않았다(C11).

### 검사 C1~C12

| # | 판정 | 근거 |
|---|---|---|
| C1 R-035 DB 스캔 | 통과 | `tests/graph/test_postgres_memory.py::test_no_checkpoint_row_holds_a_real_number`. 끼어들기·재개(고친 인자 `DEMO0002`) 뒤 `text`·`answer`가 없고 세 표에 `DEMO0001`·`DEMO0002`가 0줄 |
| C2 R-066 | 통과 | `tests/rag/test_read_pool.py` 두 시험. 보정에서 autocommit을 빼면 `assert 1 == 0`으로 실패함을 보였다. 태그 ckpt/4b-t2에서 다시 돌려 R-066 충족 |
| C3 트레이스 가림 | 통과 | `tests/graph/test_trace.py`. 가리기 전 값에는 `DEMO0001~0004`가 모두 있고 가린 값에는 0개. 보정에서 길마다 지났는지와 `on_tool_error`를 시험에 넣었다. 태그 ckpt/4b-t3에서 다시 돌려 654 통과 |
| C4 인증 | 통과 | `tests/test_auth.py`, `tests/graph/test_server.py`, `tests/graph/test_agent.py::test_the_server_graph_refuses_to_run_without_a_user_id`. 태그 ckpt/4b-t4에서 다시 돌려 R-048·R-069·R-070·R-072 충족 |
| C5 재개 다시 가림 | 통과 | `tests/graph/test_resume.py`와 `test_server.py`의 승인 카드 시험. 다시 가리기를 끄면 모델 입력에 `DEMO0001`이 나오는 대조가 같은 시험 안에 있다. 키·숫자 값의 번호는 보정에서 닫았다 |
| C6 이벤트 순서 | 통과 | `tests/graph/test_server.py`. 끝 이벤트는 정확히 하나이고 카드를 만들다 죽어도 인코딩에 실패해도 `RUN_ERROR` 하나로 끝난다 |
| C7 화면 입력 무시 | 통과 | `test_state_and_forwarded_props_from_the_browser_are_ignored`와 R-072 시험(설정은 서버 값으로만 짓고, 실제 실행에서 `user_of`가 본 설정도 확인) |
| C8 이미지 | 통과 | uid 10001, `/app`에 허용 목록의 것만, 규칙·지시문 불러오기 성공, arm64 1.07GB, amd64 빌드 성공(71초)과 크기 1.18GB(상한 1.2GB, 여유 작음), 시작 거절 두 가지, 모든 바깥 이미지 `@sha256:` 고정, 포트 모두 `127.0.0.1:`. 태그 ckpt/4b-t8에서 다시 돌려 별도 이미지 빌드로도 확인 |
| C9 Playwright | 통과 | 흐름 4 통과(`workers: 1`, `retries: 0`), axe serious·critical 0, 브라우저의 Anthropic·Voyage 요청 0, e2e 망은 internal, 스크린샷 3장(가짜 모델). `playwright-core` 판 검사는 `6e064fd`에서 더했다. 태그 ckpt/4b-t10에서 다시 돌려도 4 통과 |
| C10 배포 준비 | 통과 | 워크플로는 `workflow_dispatch`만이고 actionlint 오류 0, `PORT`는 단위 시험으로, 키·로그인 설정이 없으면 시작 거절. `docs/deploy.md`의 "로컬 확인" 줄은 실제로 돌린 것만 적었다 |
| C11 R-067 | 통과 | `git show --name-only`로 센 커밋당 코드 파일 최대 10개. 서버 연결 일은 부르는 곳별 커밋(2a 풀, 2b 연결, 2c 자르기, 5a, 5b, 6a, 6b) |
| C12 호스트 청결 | 통과 | `~/Library/Caches/ms-playwright`의 목록이 시작 때와 같다(`b`, `chromium_headless_shell-1228`, `chromium-1228`, `ffmpeg-1011`). 호스트에서 `npm`·`npx`·`playwright install`을 돌리지 않았고 호스트에 `web/node_modules`·`.next`가 없다 |

### 검토에서 나온 것과 닫은 커밋

| 대상 | 나온 것 | 닫은 커밋 |
|---|---|---|
| T1 | 주석 둘이 사실과 다름 | `e81941b` |
| T2 | 열린 트랜잭션 시험이 autocommit을 빼도 통과, 질의 자르기 직접 길 시험 없음 | `997e994`, `f547915` |
| T3 | 계획이 적은 Langfuse 훅 모양이 틀림(`mask(data=...)`), 튜플·번호 키에서 죽음, `status_message`는 가려지지 않음 | `e5aef9c`, `784c28a`, `9e987e7` |
| T4 | 공개키 목록 받기 오류가 날것의 예외로 나감, 시계 차이 0, http 주소 허용, 운영 길 시험 없음 | `df21018`, `afc0bc5` |
| T5a | 끝 이벤트가 빠지는 길, `selected` 확인 없음, 마지막 메시지 밖을 읽음, 로그인 확인이 이벤트 루프를 막음, 주소 0.0.0.0 고정, 인코딩 실패, 시험 빈틈 | `9dfd788`, `7c71ab5`, `041aeff`, `d3f1476`, `fa45134`, `a1362d1` |
| T5b | 고친 인자의 키·숫자 값, 결정의 덤 키가 모델과 체크포인트에 닿음 | `4ace552`, `6c17a7c`, `569f200` |
| T6 | 계정 삭제 트랜잭션이 공유 감시 연결 위에서 열림, 돌고 있는 차례를 막지 않음, 앞머리 겹침·`unwatch_cargo` 0줄 시험 없음, 지시문에 규칙 한 줄 없음, 기억 이름 공간 둘만 지움, 집합을 잠금 밖에서 바꿈 | `0a9b059`, `387f4ba`, `cc1aa92`, `878918c` |
| T7 | 스트림이 말없이 끊김, 토큰을 새로 받지 않음, 새 카드로 초점이 안 감, 영어 오류 글 | `a9f7b45`, `d97356b`, `ed31350`, `a5a02f5`, `521c8dc` |
| T8 | prepare가 DB 준비를 기다리지 않음, 주석이 사실과 다름, 시험 빈틈 | `28844ae`, `9c7a573` |
| T9 | 승인 카드에 영어 도구 이름, 이미지의 `playwright-core` 판 미확인, 스크린샷이 시각에 따라 달라짐 | `c3f5dd4`, `6e064fd`, `ca8e669` |
| T10 | 서명 키 안내 빠짐, 확인 출처 불분명 | `aab1f0a` |

### 계획 글에서 바뀐 결정

| 결정 | 바뀐 것 | 이유 |
|---|---|---|
| 서버 틀 | Starlette 유지, FastAPI 쓰지 않음 | 이미 잠겨 있었고 경로가 셋뿐 |
| 그래프 설정 | 서버가 만든 값(대화 키, 확인한 사용자 id, 서버 표시)으로만 짓는다 (R-072) | 호출 때 `configurable`이 묶어 둔 값을 덮어쓴다 |
| 듣는 주소 | 기본 127.0.0.1, 컨테이너만 `MARVIA_HOST=0.0.0.0` (R-074) | 로컬 서버는 127.0.0.1에만 연다는 전역 제약 |
| 인스턴스 | Cloud Run `--max-instances 1` (R-073) | 대화 잠금이 프로세스 안에서만 지켜짐. 늘릴 때는 `pg_try_advisory_lock` |
| 계정 삭제 | 대화 기록 삭제는 자기 연결에서, 돌고 있는 차례가 있으면 409, 기억은 사용자 이름 공간 전체 | 공유 감시 연결의 트랜잭션이 다른 사용자 문장을 삼킨다 |
| 승인 고치기 | 고친 인자를 JSON 글로 만든 뒤 번호가 하나라도 남으면 거절 | 고친 인자는 JSON 알림으로 모델에 간다 |
| 승인 카드 글 | 도구 이름 대신 한국어 이름(`approval.labels`) | 화면 카드와 같은 이름 |
| 취소한 선택지 카드 | `{"timeout": true}`로 권장안 | 빈 값으로 재개하면 다시 멈춘다 |
| 바깥 메시지 발송 도구 | 만들지 않음 | 보낼 통로가 없고 6.3에서 2차 |

### 확인하지 못한 것

- 실제 Supabase 프로젝트로 로그인: 공개키 목록을 네트워크로 받는 길, 실제 토큰 만료, 구글 로그인 돌아오기 [미확인]. 서버 확인은 시험 안에서 만든 ES256 키로만 봤다.
- 컨테이너를 `PORT`를 바꿔 띄우는 확인 [미확인]. `PORT`는 `main()`의 단위 시험으로만 봤다.
- Cloud Run job과 service 배포, gcloud·Vercel 명령, Vercel 앞에서 SSE가 모이지 않고 흐르는지 [미확인].
- amd64의 e2e 단계 빌드와 실행. amd64는 runtime 단계 빌드만 했다.
- 네 흐름 밖의 브라우저 동작(브라우저가 끊었을 때 그래프가 다음 갱신에서 멈추는지 포함) [추정].
- 실제 모델로 화면 한 차례(충전 전). 화면과 스크린샷은 가짜 모델이다.
- 3b 유료 측정은 충전을 기다린다. 평가 수치는 새 지시문(`unwatch_cargo` 규칙 한 줄, `cc1aa92`)에서 다시 재지 않았다.
- 옛 평문 체크포인트 줄(R-038)은 배포 전에 따로 정리해야 한다.
