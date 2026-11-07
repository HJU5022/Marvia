# Marvia v2 계획 6b: Langfuse 트레이스 연결 (기본 꺼짐, 내보내는 값 모두 가림)

> 진행 방법: 태스크를 T0부터 차례로 하고, 단계마다 체크박스(`- [ ]`)로 표시한다. 커밋 하나는 동작 하나다. 키 셋이 모두 있을 때만 트레이서가 켜지므로, 키가 없는 시험·평가·서버는 커밋마다 지금과 똑같이 돈다.

**Goal:** 노드·도구·LLM 호출을 Langfuse 트레이스로 남길 수 있게 연결한다. 기본은 꺼짐이고 `MARVIA_LANGFUSE_PUBLIC_KEY`·`MARVIA_LANGFUSE_SECRET_KEY`·`MARVIA_LANGFUSE_HOST`가 모두 있을 때만 켜진다. 내보내는 span의 모든 칸(이름, 속성, 사건, 상태, 자원)에서 화물 번호를 가린다. 서버·CLI·평가가 같은 콜백 하나를 쓴다 (done 3.9, 설계 11절·12절).

**Architecture:** 켜고 끄기는 `trace.tracer_callbacks` 한 곳에서 정하고, SDK를 다루는 일은 새 모듈 `langfuse_trace.py`에만 둔다. 키가 없으면 `langfuse`를 import하지도 않는다. 가림은 네 겹이고 겹마다 맡는 칸이 다르다.

```
설정 MARVIA_LANGFUSE_* 셋 ── trace.tracer_callbacks(settings)
   ├─ 하나라도 비면 []  (langfuse import 없음, 스레드·소켓 0)
   └─ 셋 다 있으면 [가린 콜백 하나] (프로세스에 하나, functools.cache) = langfuse_trace.build(...)
langfuse_trace.build:
   Langfuse(⓪ should_export_span=is_langfuse_span   SDK span만 내보냄 (다른 라이브러리 OTel span 버림)
            ① mask=scrub                            input·output·metadata (JSON으로 바꾸기 전)
            ② mask_otel_spans=scrub_spans            그 밖의 span 속성 (status_message 등)
   ) + ③ ScrubbedHandler(CallbackHandler)            오류를 가린 사본으로 → span 상태 설명
서버 main → build_app(callbacks=) → graph.with_config(callbacks)
CLI scripts/try_agent.py → 실행 설정 callbacks
평가 scripts/run_eval.py → evaluate_item(callbacks=) → drive, meta.tracing on/off
서버 시작 검사(auth.check_startup): 접두어 없는 LANGFUSE_* 환경 변수가 있으면 뜨지 않음 (R-069 옆)
```

**Tech Stack:** 새 의존성 langfuse 5.0.4 하나(함께 오는 패키지 11개: opentelemetry-sdk 1.45.2, opentelemetry-exporter-otlp-proto-http 1.45.2 등). LangChain 콜백(`langfuse.langchain.CallbackHandler`)으로 붙인다. 시험은 OTel `InMemorySpanExporter`를 `span_exporter`로 줘서 키·Langfuse 서버·네트워크 없이 내보낸 span을 읽는다 [실측 11-07: 범위 조사와 이 계획의 검증 사본].

**Spec:** `docs/specs/2026-10-28-marvia-v2-design.md` (11절 Langfuse 줄, 12절 신뢰 경계, 15절). done 3.9. 범위 조사(11-07)의 사실과 결정을 따른다. 따르지 않은 곳과 검증 중 새로 안 사실은 "결정과 근거"에 적었다.

## 계획 나눔

| 계획 | 범위 | 상태 |
|---|---|---|
| 3a~6a | 답, 도구 루프, 기억·조사·감시, 평가, GraphRAG·MCP, 화면·배포 준비, 컨테이너 번호 | 완료 (11-02~11-07) |
| **6b (이 문서)** | Langfuse 트레이스 연결: 기본 꺼짐, 네 겹 가림, 서버·CLI·평가 한 콜백 (done 3.9) | 11-08 시작, 11-08 끝 |
| 6b 뒤 | 실제 Langfuse 서버로 보내 보기(키), 배포에서 켜기 | 직접 할 일 |
| 2차 | Langfuse 프롬프트 등록, 평가 점수 붙이기 | 설계 15절 (아래 결정) |

## 결정과 근거 (11-07)

| 결정 | 이유 | 틀렸을 때 비용 |
|---|---|---|
| langfuse 5.0.4를 `==`로 고정하고 LangChain 콜백(`langfuse.langchain.CallbackHandler`)으로 붙인다 | 2주 넘은 판 중 가장 새 판이다(5.0.4 10-21, 5.1.0 10-30, 5.2.0 11-05) [실측 11-07 PyPI, 범위 조사]. 실행 설정의 콜백 하나가 메인 그래프, Send 갈래, 도구 안에서 부른 서브그래프, 미들웨어, 조사 서브에이전트, 모델 호출을 모두 덮는다 [실측 11-07: 문 시험 SDK span 144개] | 5.0.4 뒤에 고친 버그를 받지 못한다. 판을 올리면 문 시험이 내보낸 span을 다시 본다 |
| 켜짐은 키 셋(`MARVIA_LANGFUSE_PUBLIC_KEY`·`SECRET_KEY`·`HOST`)이 모두 있을 때뿐이다. 하나라도 비면 `trace.tracer_callbacks`가 `[]`를 돌려주고 `langfuse`를 import하지 않는다 | 11-07 결정. 키 없이 `Langfuse()`를 만들어도 연결은 0이지만, 키가 있으면 `tracing_enabled=False`여도 일꾼 스레드 3개가 뜬다 [실측 11-07 범위 조사]. 그래서 "만들지 않음"으로 끈다 | 셋 중 일부만 넣으면 아무 말 없이 꺼진 채 뜬다(시작 거절이 아니다). 트레이스가 보이지 않으면 셋을 모두 넣었는지 본다 |
| 키와 주소는 `Langfuse(public_key=, secret_key=, base_url=)` 인자로만 넘긴다 | SDK는 인자로 받지 않은 값을 `LANGFUSE_*` 환경 변수에서 읽는다(`langfuse/_client/client.py`) [문서 SDK 소스]. pydantic-settings는 `.env`를 `os.environ`에 쓰지 않아 루트 `.env`의 v1 `LANGFUSE_*`는 읽히지 않는다 | 없음 |
| 서버 시작 검사(`auth.check_startup`)가 접두어 없는 `LANGFUSE_` 이름의 환경 변수를 모두 거절한다 | 11-07 결정. LangSmith 추적 변수(R-069)와 같은 자리다. 환경 변수만으로 가림 밖의 연결이 생기거나 SDK 설정(환경 이름, 표본 비율, 끄기)이 바뀌지 않게 한다. 시험은 셸에 걸린 `LANGFUSE_*`를 지우는 autouse 준비물로 돈다 | 습관대로 `LANGFUSE_*`를 넣은 사람은 거절 글을 본다. CLI·평가는 이 검사를 하지 않는다(키는 인자로만 넘긴다) |
| 가림은 네 겹이고 겹마다 맡는 칸이 다르다. ⓪ `should_export_span=is_langfuse_span`: Langfuse SDK가 만든 span만 내보낸다. ① `mask=scrub`: input·output·metadata. ② `mask_otel_spans=scrub_spans`: 그 밖의 span 속성의 글과 글 목록. ③ `ScrubbedHandler`: `on_chain_error`·`on_tool_error`·`on_llm_error`·`on_retriever_error`에 가린 사본 예외를 넘기고, 오류 도구 결과(`ToolMessage(status="error")`)의 글을 가린다 | 11-07 결정의 세 겹(①②③)에 ⓪을 더했다(다음 줄). SDK는 `mask`를 input·output·metadata에만 부른다. `status_message`는 ②만 닿고, OTel span 상태 설명(`status.description`)과 사건(event)은 두 hook 어느 쪽도 고치지 못한다. SDK는 ERROR 단계일 때만 상태 설명을 쓴다(`langfuse/_client/span.py`의 `_set_otel_span_status_if_error`) [문서 SDK 소스] | SDK가 새 속성을 만들면 ②가 가린다(①의 칸 이름 밑이면 ①). 문 시험이 span 전체를 읽으므로 시나리오가 지나는 길에서 번호가 실리면 잡는다 |
| ⓪을 더한다 (범위 조사 밖, 11-08 검증 중 발견) | 키를 준 `Langfuse(...)`는 전역 OTel TracerProvider가 없으면 자기 것을 전역으로 놓는다(`resource_manager.py`의 `_init_tracer_provider`) [실측 11-08: 만들기 전 `ProxyTracerProvider`, 뒤 `TracerProvider`. 범위 조사의 "전역은 그대로"는 import 뒤만 본 값이었다]. 그 뒤 mcp 2.x 서버의 `tools/call` span은 `gen_ai.tool.name` 속성 때문에 SDK 기본 거름(`is_default_export_span`)을 지난다. 이 span은 ①·③을 거치지 않고, 예외가 나면 예외 사건(`record_exception`)과 상태 설명에 `str(e)`를 싣는다(`mcp/server/_otel.py`) [문서 소스]. RAG 기본 길이 `rag_via=mcp`다. 검증 사본에서 트레이서를 켠 채 tests/rag를 돌리면 MCP 서버 span 13개(`tools/call search_regulations`)가 기본 거름으로 내보내지고, ⓪을 주면 0개다 [실측 11-08] | Langfuse 화면에 MCP 서버 span이 없다. 같은 검색은 콜백의 도구 span이 남긴다 |
| ②는 ①의 칸(`langfuse.observation.input`·`output`·`metadata.*`, `langfuse.trace.metadata.*`)을 건너뛴다 | SDK는 input·output을 `json.dumps`(ASCII 이스케이프)로 적는다. JSON 글을 다시 가리면 이스케이프가 번호 후보로 잡혀 JSON이 깨진다 [실측 11-07: `"관세법 제241조의 기한"`을 담은 JSON에서 `\uc81c241`이 `[가림]`이 되어 `JSONDecodeError`]. ①이 JSON으로 바꾸기 전에 같은 규칙으로 가린다 | ①을 거치지 않고 그 칸에 값을 쓰는 SDK 길이 생기면 ②가 잡지 못한다. ① 빼기 시험이 그 칸에서 번호를 찾으므로 ①이 빠지는 것은 잡는다 |
| ③은 끼어들기(`GraphBubbleUp`)를 가리지 않고 그대로 넘긴다 | SDK는 끼어들기를 오류 단계로 보지 않아(DEFAULT) 상태 설명을 쓰지 않는다. 질문 글(식별 끼어들기는 실제 번호 조각을 싣는다)이 드는 `status_message` 속성은 ②가 가린다. 원래 예외를 넘기므로 SDK의 재개 트레이스 잇기도 그대로다 | ②가 빠지면 식별 끼어들기의 번호가 나간다. ② 빼기 시험이 이것을 본다 |
| 문 시험은 내보낸 span마다 OTel `ReadableSpan.to_json()`(이름, 문맥, 부모, 시각, 상태, 속성, 사건, 연결, 자원)과 계측 범위를 글로 바꿔 번호를 찾는다. 정한 칸 목록을 보지 않는다 | 11-07 결정: span 객체 전체를 읽는다 | 시나리오가 지나지 않는 길(승인 카드 편집 재개, 긴 대화 요약, 계획자 루프, 실제 MCP 검색)은 이 시험이 보지 않는다. 같은 콜백과 같은 네 겹을 지난다 [추정] |
| 시험은 `span_exporter=InMemorySpanExporter()`로 받고, 공개키를 시험마다 새로 만든다 | exporter만 바뀌고 ⓪~②는 그대로 돈다(⓪은 span 처리기, ①은 속성을 만들 때, ②는 SDK가 exporter를 감싼 `LangfuseTransformingSpanExporter`) [실측 11-07 범위 조사와 문 시험]. SDK는 공개키마다 클라이언트를 하나만 둔다 | 실제 OTLP HTTP 내보내기(인증, 압축, 묶음 크기, 재시도)는 보지 않는다(직접 할 일 2) |
| 콜백 하나를 프로세스가 함께 쓴다(`functools.cache`) | SDK 콜백은 끼어들어 멈춘 실행의 트레이스를 기억했다가 재개(`Command(resume=...)`)를 같은 트레이스로 잇는다(`_pending_resume_trace_contexts`, 1024개까지) [문서 SDK 소스]. 콜백 상태는 run_id별 표라 동시에 도는 차례를 받는다 [추정] | 동시 차례가 많을 때 span 부모가 섞이는지는 보지 않았다 |
| 서버는 `build_app`의 그래프 기본 설정(`with_config(callbacks=...)`)에 콜백을 둔다. 차례마다 만드는 실행 설정에는 넣지 않는다 | 차례 실행 설정은 R-072 시험이 그대로 비교한다. 기본 설정의 콜백은 실행 설정과 합쳐진다 [실측: 기존 `Inputs` 콜백 시험이 같은 방식] | 없음 |
| 평가도 같은 함수를 쓰고 결과 `meta.tracing`에 `on`·`off`를 적는다 | 11-07 결정: 가리는 곳을 하나로 둔다 | 키를 `.env`에 둔 채 유료 평가를 돌리면 평가 트레이스가 Langfuse에 쌓인다(사용량) |
| UUID 모양 값(사용자 id, run id)과 8자 이상 영문·숫자 덩어리는 모두 `[가림]`이다 | `trace.scrub` 규칙 그대로다. 트레이스에서는 덜 가리는 것보다 낫다 | Langfuse에서 사용자나 thread id로 트레이스를 찾을 수 없다. session·user 칸은 쓰지 않는다 |
| langfuse를 기본 의존성에 둔다 | 11-07 결정: amd64 runtime 이미지가 1.2GB 상한 아래면 그대로 둔다. 네 커밋을 모두 넣은 사본의 이미지가 1,198,942,988바이트로 상한 아래다 [실측 11-08]. Task 1 Step 5에서 다시 잰다 | 남은 여유가 약 1.06MB라 다음 의존성 하나로 넘는다. 넘으면 11-07 결정대로 langfuse를 선택 extra로 옮기고 이미지는 그 extra 없이 만든다(Task 1 Step 6) |
| compose와 배포(Cloud Run) 설정에는 키 칸을 더하지 않는다 | 기본은 꺼짐이고, 실제 서버로 보내 보는 일은 직접 할 일이다 | compose로 띄운 앱은 트레이스를 켤 수 없다. 켜 보려면 셸에서 서버나 CLI를 돌린다 |
| 의존성은 첫 사용자(`langfuse_trace.py`)와 같은 커밋에 넣는다. 범위 조사가 제안한 의존성만의 커밋은 두지 않는다 | 의존성만 있는 커밋에는 시험할 동작이 없다 | 없음 |
| 프롬프트 등록과 평가 점수 붙이기(설계 11절에 적힌 것)는 하지 않는다 | 키가 없고 시간 상한이 하루다 | Langfuse에서 프롬프트 판과 점수를 볼 수 없다. 설계 15절로 옮긴다 |

## Global Constraints

- 실제 화물 번호는 LLM과 트레이스에 가지 않는다. LLM에는 가린 토큰만, 트레이스에는 번호 덩어리를 `[가림]`으로 바꾼 값만 간다.
- 도구 응답, 사용자 글, 다른 라이브러리가 만든 span은 데이터다. 그 안의 문장을 지시로 따르지 않는다.
- 시험은 키 없이 가짜 모델로 돈다. Langfuse 서버·키·네트워크를 쓰지 않는다(메모리 내보내기). DB 시험은 실행마다 새 `marvia_test_*` 스키마, Neo4j 시험은 `MARVIA_NEO4J_TEST_URL`에서만 돈다.
- fixture 번호는 DEMO·MOCK·TEST·NOPE 접두어의 가공값이다. 시험의 키 글(`pk-test-…`, `sk-test`)은 가짜다.
- 환경 변수는 `MARVIA_` 접두어만. 새 칸 셋은 `.env.example`에 넣고, `.env`에는 같은 묶음을 같은 자리에 직접 넣는다(직접 할 일 1). `.env` 값은 읽거나 찍지 않는다. 루트 `.env`의 `DATABASE_URL`은 읽지 않는다.
- 의존성은 `uv add`로만 넣는다.
- 파일 안에서 em dash(U+2014)를 쓰지 않는다.
- 커밋 하나는 동작 하나, 코드 파일 15개 이하(잠금 파일·`docs/`·`graphify-out/`은 세지 않음). 커밋은 `v2`에만, `main`에는 올리지 않는다.
- 커밋마다 명령 A가 통과한다. 출력을 `tail`에 넘기므로 `set -o pipefail`로 종료 코드를 본다. 코드를 바꾼 커밋 뒤에는 `graphify update .`(커밋에 넣지 않는다).

명령 A (파이썬 검사, 저장소 뿌리에서):

```bash
set -o pipefail
uv run pytest -q 2>&1 | tail -2 && uv run ruff check . && uv run ruff format --check . && uv run pyright | tail -1
```

- 코드 블록 검증: v2 HEAD(`c215b05`)를 내보낸 깨끗한 사본에 이 문서의 diff를 커밋 순서대로 넣고, 커밋마다 Docker(`ghcr.io/astral-sh/uv@sha256:e5b65587…`, compose의 Postgres, 커밋마다 새로 띄운 시험용 Neo4j)에서 `MARVIA_REQUIRE_DB=1`, `MARVIA_REQUIRE_NEO4J=1`로 시험 전체와 `ruff check`·`ruff format --check`·`pyright`를 돌렸다: HEAD 794 → 커밋 1 800 → 커밋 2 804 → 커밋 3 807 → 커밋 4 809 통과(건너뜀 0), 커밋마다 ruff·형식·pyright 오류 0 [실측 11-07~08]. 각 커밋의 "먼저 실패" 줄은 앞 커밋의 코드에 그 커밋의 시험 파일만 얹어 돌려 얻었다. amd64 이미지 크기(C5)는 같은 사본에서 잰 값이다.

---
## 사전 등록: 검사 C1~C6 (구현 전에 고정)

이 절은 첫 구현 커밋 전에 이 문서와 함께 커밋하고, 결과를 본 뒤 기준을 고치지 않는다. 고칠 일이 생기면 이유와 시각을 따로 적고 원래 기준의 판정도 함께 적는다.

| # | 검사 | 통과 기준 | 시험·명령 | 지금 HEAD |
|---|---|---|---|---|
| C1 | 꺼짐이 기본 | 키 셋 중 하나라도 비면 `tracer_callbacks(settings) == []`. 새 파이썬 프로세스에서 키 없이 부르면 콜백 없음, `langfuse`가 `sys.modules`에 없음, 스레드 증가 0, 소켓 연결 0. 셋 다 있으면 두 번 불러도 같은 콜백 하나이고 `langfuse_trace.build`에 공개키·비밀키·주소가 그 순서로 간다(시험은 build를 가짜로 바꿔 SDK를 만들지 않는다). `Settings` repr에 키 값이 없다. 서버 시작 검사가 `LANGFUSE_PUBLIC_KEY`·`LANGFUSE_SECRET_KEY`·`LANGFUSE_TRACING_ENVIRONMENT`를 거절하고, `MARVIA_LANGFUSE_*`만 있으면 뜬다 | `tests/graph/test_trace.py::test_without_keys_tracing_is_off_with_no_sdk_thread_or_socket`, `::test_tracing_stays_off_unless_all_three_settings_are_given`(2), `::test_all_three_settings_give_one_shared_tracer_and_keys_stay_hidden`, `tests/test_auth.py::test_the_server_refuses_to_start_with_a_raw_langfuse_env_var`(3) | `tracer_callbacks` 없음(`ImportError`), `Settings`에 칸 없음, `LANGFUSE_SECRET_KEY=x`가 있어도 `check_startup`이 통과한다(`DID NOT RAISE`) [실측 11-07] |
| C2 | 문: 내보낸 span 전체에 번호 0 | 같은 콜백으로 (1) 번호 둘과 애매한 덩어리 `MOCK12345678TEST87654321` → 식별 끼어들기(질문에 실제 번호) → 재개 → Send 갈래 → news(감시 변화 DEMO0004) → `lookup_cargo` → `ask_user` 끼어들기 → 직접 입력 DEMO0003 → `research`(서브에이전트 안 `search_law`) → 답, (2) 모델 오류(`OutputParserException`, DEMO0006, Guards가 받음), (3) 도구 예외(`calc_deadlines` 안 `ValueError`, DEMO0005, 차례가 멈춤), (4) 오류 도구 결과(`ToolMessage(status="error")`, DEMO0007), (5) 다른 라이브러리 OTel span(MCP 서버 꼴: `gen_ai.tool.name`, 예외 사건과 상태 설명에 DEMO0008)을 돌린다. 내보낸 span 전체(`to_json`과 계측 범위)에 번호 10개(DEMO0001~0008, MOCK12345678, TEST87654321)가 0개이고 `[가림]`이 있다. 네 겹을 모두 뺀 대조 실행에는 10개가 모두 있다. SDK span 수는 대조와 같다(대조보다 다른 라이브러리 span 하나만 적다). 답에는 DEMO0001이 남고 대조의 답과 같다. 소켓 연결 0 | `tests/graph/test_trace.py::test_every_exported_span_field_is_free_of_numbers` | `ModuleNotFoundError: No module named 'langfuse'` [실측 11-07]. 범위 조사(11-07): `mask=scrub`만 넣으면 도구 오류 번호가 `status_message`와 상태 설명에, 끼어들기 질문 번호가 `status_message`에 남는다 |
| C3 | 겹마다 맡는 칸 | 한 겹씩 빼면 그 겹이 맡은 번호가 남는다: ⓪ → DEMO0008(다른 라이브러리 span), ① → DEMO0001~0004·MOCK12345678·TEST87654321(입력·출력), ② → MOCK12345678·TEST87654321(식별 끼어들기의 `status_message`), ③ → DEMO0005~0007(상태 설명). ②가 예외를 내면 그 묶음을 하나도 내보내지 않고, ①이 예외를 내면 값을 통째로 바꾼 글만 나간다 | `::test_removing_any_one_layer_leaves_its_numbers`(4), `::test_a_failing_mask_exports_nothing_or_masks_the_value_whole` | C2와 같은 `ModuleNotFoundError` [실측 11-07] |
| C4 | 콜백 하나 | 서버(`main` → `build_app(callbacks=)`), CLI(`try_agent.py`의 실행 설정), 평가(`run_eval.py` → `evaluate_item(callbacks=)`, `meta.tracing`)가 모두 `trace.tracer_callbacks`를 쓴다. `langfuse`를 import하는 파일은 `src/marvia/langfuse_trace.py` 하나다. 서버 한 차례를 메모리 내보내기로 돌리면 span이 있고 DEMO0001이 0개, 화면 답에는 DEMO0001이 있다 | `tests/graph/test_server.py::test_a_traced_turn_exports_spans_without_numbers_and_still_answers_with_them`, `::test_main_listens_on_loopback_unless_marvia_host_says_otherwise`(콜백 칸을 더함), `tests/graph/test_eval_run.py::test_evaluate_item_runs_the_graph_with_the_tracer_callbacks`, 명령 B | `build_app`에 `callbacks` 칸 없음(`TypeError`), `server`에 `tracer_callbacks` 없음(`AttributeError`), `evaluate_item`에 `callbacks` 칸 없음(`TypeError`), 명령 B의 두 grep 모두 0줄 [실측 11-07] |
| C5 | 이미지 크기 | amd64 runtime 이미지가 1,200,000,000바이트 이하(Docker가 세는 이미지 크기 = `docker image ls`의 DISK USAGE, `docker run`으로 한 번 층을 푼 뒤). 이미지 안에서 `import langfuse, marvia.langfuse_trace` 성공. 넘으면 Task 1 Step 6 | Task 1 Step 5의 명령 | 1,178,755,521바이트(DISK USAGE 1.18GB) [실측 11-07]. 네 커밋을 넣은 사본 1,198,942,988바이트, import 성공 [실측 11-08] |
| C6 | 회귀·크기 | 시험 수가 794에서 줄지 않고(마지막 809), 건너뜀 0, ruff·형식·pyright 오류 0. `set_v2` sha 시험 통과(평가셋 그대로). 커밋마다 코드 파일 15개 이하 | 명령 A, `git show --stat` | 794 통과, 건너뜀 0 [실측 11-07, Docker] |

**C2·C3 시나리오 넓힘 (11-08 새벽, Task 1 검토 뒤).** 원래 시나리오의 thread_id에는 번호가 없었다. LangGraph는 `configurable.thread_id`를 트레이스 메타데이터(`langfuse.trace.metadata.*`)에 옮기고, SDK는 이 칸을 `mask` 없이 쓰며, 처음 코드(e33c587)는 ② 겹이 이 칸을 건너뛰게 했다. 그래서 사용자가 정하는 thread_id(화면의 대화 id, CLI의 `--thread`)에 번호가 들면 그대로 나갔다 [실측 11-08: thread_id `DEMO0002`가 그대로 내보내짐]. 문 시나리오의 thread_id를 `gate-DEMO0009`로 바꾸고 ② 겹이 그 칸도 가리게 했다(8048a6f). 판정: 원래 시나리오로는 e33c587에서 C2·C3 통과, 넓힌 시나리오로는 e33c587에서 C2 실패(`assert ['DEMO0009'] == []`), 8048a6f에서 C2·C3 통과. 통과 기준 글은 바꾸지 않았다.

명령 B (C4, 저장소 뿌리에서):

```bash
grep -rlE '^[[:space:]]*(from|import) langfuse' src scripts eval
grep -rln 'tracer_callbacks(' src scripts | sort
```

Expected [실측 11-08, 검증 사본]: 첫 줄은 `src/marvia/langfuse_trace.py` 하나. 둘째 줄은 `scripts/run_eval.py`, `scripts/try_agent.py`, `src/marvia/server.py`, `src/marvia/trace.py`(정의).

## 비용

이 계획에는 유료 모델 호출, Langfuse 호출, 실제 UNI-PASS 호출이 없다($0). 시험은 가짜 모델과 메모리 내보내기로 돈다. 실제 Langfuse로 보내 보는 일(모델 호출 한 차례)은 직접 할 일 2다.

## 시간 상한, 확인점, 자를 순서

남은 날은 11-08 하루다(코드 동결 11-16). 11-08 저녁까지 끝나지 않으면 자를 순서대로 자르고 끝낸다.

| 태스크 | 닫는 것 | 어림 | 날짜 | 끝났다는 증거 |
|---|---|---|---|---|
| T0 사전 등록 | C1~C6 고정 | 0.2시간 | 11-08 | 이 문서 커밋 |
| T1 네 겹으로 가린 핸들러 | C2·C3·C5 | 3시간 | 11-08 | 800 통과, 이미지 1.2GB 이하 |
| T2 키 셋이 있을 때만 | C1 일부 | 1시간 | 11-08 | 804 통과 |
| T3 `LANGFUSE_*` 시작 거절 | C1 일부 | 0.5시간 | 11-08 | 807 통과 |
| **CP1 (11-08 낮 3시)** | T1~T3 끝났나. 아니면 자를 순서 1·2를 바로 자른다 | | | |
| T4 서버·CLI·평가 연결 | C4 | 1.5시간 | 11-08 | 809 통과 |
| T5 문서 | 설계 11·12·15절, 배포 문서의 크기 줄 | 0.5시간 | 11-08 | |
| 합 | | 약 6.7시간 | | |

자르는 순서 (먼저 자르는 것부터):
1. 평가 연결(T4의 `evaluate_item`·`run_eval.py`) → 평가는 지금처럼 트레이스 없이 돈다. `meta.tracing` 칸도 없다. C4는 서버·CLI로만 판정하고 못 넘은 부분을 적는다
2. CLI 연결(T4의 `try_agent.py`)
3. 가림 함수 실패 시험(T1의 `test_a_failing_mask_exports_nothing_or_masks_the_value_whole`) → C3의 둘째 문장은 "확인하지 못한 것"으로 옮긴다

자르지 않는 것: 꺼짐이 기본(C1), 네 겹과 문 시험(C2, C3의 겹 빼기), `LANGFUSE_*` 시작 거절, 서버 연결, 이미지 크기(C5), 각 태스크의 시험.

## 파일 구조

| 파일 | 책임 | 태스크 |
|---|---|---|
| `pyproject.toml`, `uv.lock` | langfuse 5.0.4 (`uv add`) | T1 |
| `src/marvia/langfuse_trace.py` (새 파일) | 네 겹: `scrub_spans`, `ScrubbedHandler`, `build` | T1 |
| `src/marvia/trace.py` | `tracer_callbacks`, 머리 주석 | T2 |
| `src/marvia/config.py`, `.env.example` | `MARVIA_LANGFUSE_*` 세 칸 | T2 |
| `src/marvia/auth.py`, `tests/conftest.py` | `LANGFUSE_*` 시작 거절, 시험이 셸의 `LANGFUSE_*`를 지움 | T3 |
| `src/marvia/server.py`, `scripts/try_agent.py`, `src/marvia/eval/run.py`, `scripts/run_eval.py` | 세 길 연결 | T4 |
| `docs/specs/2026-10-28-marvia-v2-design.md`, `docs/deploy.md` | 11·12·15절과 변경 기록, 이미지 크기 줄 | T5 |
| `tests/graph/test_trace.py`, `tests/test_auth.py`, `tests/graph/test_server.py`, `tests/graph/test_eval_run.py` | 시험 | 모두 |

---
### Task 0: 사전 등록

- [ ] **Step 1: 이 문서를 첫 구현 커밋 전에 커밋한다.** 결과를 본 뒤 C1~C6의 기준을 고치지 않는다.

```bash
git add docs/plans/2026-11-07-marvia-v2-plan-6b-langfuse.md
git commit -m "docs: 계획 6b Langfuse 트레이스 연결과 사전 등록 검사 C1~C6"
```

### Task 1: 네 겹으로 가린 Langfuse 핸들러 (C2, C3, C5)

**배울 것:** Langfuse v5는 OpenTelemetry 위에 있다. LangChain 콜백이 실행(체인·도구·모델)마다 OTel span을 열고 닫으며, input·output·metadata를 JSON 글 속성으로 적는다. 내보내기 전에 끼어들 자리가 둘 있다: `mask`(SDK가 속성을 만들 때 input·output·metadata에 부른다)와 `mask_otel_spans`(내보내기 직전 속성 전체를 보고, 바꿀 속성만 돌려주며, 예외를 내면 그 묶음을 버린다). span 상태(코드와 설명)와 사건(event)은 속성이 아니라 둘 다 고치지 못한다. 그래서 상태 설명을 만드는 오류는 콜백에 들어오기 전에 가린 사본으로 바꾼다(③). 키를 준 클라이언트는 전역 TracerProvider를 놓으므로 다른 라이브러리의 span도 같은 내보내기로 오고, ⓪이 SDK span만 남긴다. 시험은 `span_exporter`로 메모리 내보내기를 주고 `get_client(public_key=...).flush()` 뒤 `get_finished_spans()`로 읽는다.

#### 커밋 1: feat(trace): 네 겹으로 가린 Langfuse 핸들러 (langfuse 5.0.4)

**Files:**
- Create: `src/marvia/langfuse_trace.py`
- Modify: `pyproject.toml`, `uv.lock` (`uv add`로만)
- Test: `tests/graph/test_trace.py`

**Interfaces:**
- Produces: `langfuse_trace.build(public_key: str, secret_key: str, host: str, exporter: SpanExporter | None = None) -> CallbackHandler`, `langfuse_trace.scrub_spans(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult`, `langfuse_trace.ScrubbedHandler`, `langfuse_trace.ScrubbedError`, `langfuse_trace.PAYLOAD`

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_trace.py
+++ b/tests/graph/test_trace.py
@@ -1,15 +1,28 @@
-"""트레이스 가림 문 시험 (R-010·R-022·R-039, done 3.9). 트레이서 없이 기록 콜백으로 본다. 키 없이 돈다."""
+"""트레이스 가림 문 시험 (R-010·R-022·R-039, done 3.9, 계획 6b). 기록 콜백·메모리 내보내기로 키 없이 본다."""
 
 import json
+import socket
+from uuid import uuid4
 
+import pytest
 from langchain_core.callbacks import BaseCallbackHandler
+from langchain_core.exceptions import OutputParserException
 from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
-from langchain_core.messages import AIMessage
+from langchain_core.messages import AIMessage, ToolMessage
+from langchain_core.outputs import ChatGeneration, ChatResult
+from langchain_core.runnables import RunnableLambda
+from langchain_core.tools import tool
+from langfuse import Langfuse, get_client
+from langfuse.langchain import CallbackHandler
 from langgraph.checkpoint.memory import InMemorySaver
 from langgraph.errors import GraphInterrupt
 from langgraph.store.memory import InMemoryStore
 from langgraph.types import Command, Send
+from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
+from opentelemetry.trace import StatusCode, get_tracer
 
+from marvia import langfuse_trace
+from marvia.graph import tools
 from marvia.graph.main import build_main_graph
 from marvia.graph.schemas import Draft
 from marvia.trace import MASK, scrub
@@ -171,3 +184,160 @@ def test_scrub_hides_hyphen_only_numbers_whole_and_keeps_an_outer_bracket():
     assert scrub("HDMU-1234567-001 도착") == f"{MASK} 도착"
     assert scrub("MAEU-1234567-89 도착") == f"{MASK} 도착"
     assert scrub("컨테이너(DEMU1234560)로") == f"컨테이너({MASK})로"
+
+
+# 계획 6b: Langfuse로 내보낸 span 전체를 본다. 메모리 내보내기라 키·서버·네트워크가 없다
+
+# 시나리오에 넣은 번호. 어느 칸으로 나가는지에 따라 묶었다
+SAID = ("DEMO0001", "DEMO0002", "DEMO0003", "DEMO0004")  # 질문·직접 입력·감시 변화: 입력과 출력
+FAILED = ("DEMO0005", "DEMO0006", "DEMO0007")  # 도구 예외·모델 오류·도구 오류 결과: span 상태 설명
+ASKED = ("MOCK12345678", "TEST87654321")  # 애매한 덩어리: 식별 끼어들기의 질문 글(status_message)
+OTHER = ("DEMO0008",)  # 다른 라이브러리 span의 예외 사건과 상태 설명
+GATE = SAID + FAILED + ASKED + OTHER
+# 가림 네 겹: ⓪ should_export_span, ① mask, ② mask_otel_spans, ③ 오류를 가리는 콜백(errors)
+LAYERS = ("should_export_span", "mask", "mask_otel_spans", "errors")
+
+
+def strip(patch, *layers):
+    """가림 겹을 뺀다. ⓪①②는 build가 Langfuse에 넘기는 인자에서 빼고, ③은 SDK 콜백을 그대로 쓴다."""
+    patch.setattr(
+        langfuse_trace, "Langfuse", lambda **kw: Langfuse(**{k: v for k, v in kw.items() if k not in layers})
+    )
+    if "errors" in layers:
+        patch.setattr(langfuse_trace, "ScrubbedHandler", CallbackHandler)
+
+
+class Scripted(ToolModel):
+    """ToolModel과 같되 차례가 예외이면 그 예외를 낸다(모델 오류 길)."""
+
+    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
+        step = next(self.messages)
+        if isinstance(step, Exception):
+            raise step
+        return ChatResult(generations=[ChatGeneration(message=step)])
+
+
+def tracer():
+    """메모리 내보내기에 붙인 가린 콜백. [왜] SDK는 공개키마다 클라이언트를 하나만 둔다. 시험마다 새 키"""
+    exporter = InMemorySpanExporter()
+    key = f"pk-test-{uuid4().hex}"
+    return exporter, key, langfuse_trace.build(key, "sk-test", "http://127.0.0.1:9", exporter)
+
+
+def exported(exporter, key) -> list[str]:
+    """내보낸 span마다 SDK가 span 전체를 적는 글(to_json: 이름·속성·사건·상태·연결·자원)과 계측 범위."""
+    client = get_client(public_key=key)
+    client.flush()
+    client.shutdown()  # [왜] 키를 받은 클라이언트가 띄운 일꾼 스레드를 멈춘다
+    # [왜] to_json은 한글을 \u로 적는다. 다시 읽어 한글 그대로 적어야 [가림]이 보인다
+    return [
+        json.dumps(json.loads(span.to_json()), ensure_ascii=False) + repr(span.instrumentation_scope)
+        for span in exporter.get_finished_spans()
+    ]
+
+
+def gate_run(agent_deps, monkeypatch, callbacks: list) -> str:
+    """한 대화와 오류 두 길을 같은 콜백으로 돌리고 대화의 답을 돌려준다."""
+    # 1) 번호 둘 + 애매한 덩어리 → 식별 끼어들기 → 재개 → Send 갈래 → news(감시 변화) → lookup_cargo
+    #    → ask_user 끼어들기 → 직접 입력 → research(서브에이전트 안 search_law) → 답
+    script = [
+        say("lookup_cargo", {"tokens": ["[BL1]"]}, 1),
+        say("ask_user", {"question": "어느 화물부터 볼까요?", "options": TWO}, 2),
+        say("research", {"question": "수입신고 기한의 근거"}, 3),
+        say("search_law", {"query": "수입신고 기한"}, 4),  # 조사 서브에이전트 안
+        AIMessage("관세법 제241조가 30일을 정해요."),
+        AIMessage(""),
+    ]
+    news = [{"id": 1, "number": "DEMO0004", "old_stage": "", "new_stage": "반입신고"}]
+    watch = WatchDeps(add=lambda *row: None, news=lambda user: news, ack=lambda user, ids: None)
+    citing = Draft(
+        answer="[BL1]은 반입일부터 30일 안에 신고해요.", citations=[], next_options=[], forwarder_message=""
+    )
+    deps = agent_deps(model=ToolModel(messages=iter(script)), watch=watch, write=lambda prompt: citing)
+    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
+    config = {"configurable": {"thread_id": "gate"}, "callbacks": callbacks}
+    out = graph.invoke({"text": "DEMO0001 DEMO0002 MOCK12345678TEST87654321 언제까지 신고해요?"}, config)
+    assert "MOCK12345678" in out["__interrupt__"][0].value["question"]  # 식별 끼어들기는 실제 번호를 싣는다
+    out = graph.invoke(Command(resume={"selected": 0}), config)
+    assert out["__interrupt__"][0].value["question"] == "어느 화물부터 볼까요?"
+    answer = graph.invoke(Command(resume={"custom": "DEMO0003부터 봐 주세요"}), config)["answer"]
+    # 2) 모델 오류: Guards가 받아 부분 답으로 끝낸다
+    broken = agent_deps(model=Scripted(messages=iter([OutputParserException("DEMO0006 모양이 틀린 답")])))
+    graph = build_main_graph(broken, InMemorySaver(), loop="agent", store=InMemoryStore())
+    graph.invoke({"text": "어디쯤이에요?"}, {"configurable": {"thread_id": "llm"}, "callbacks": callbacks})
+
+    # 3) 도구 오류: 도구 안에서 난 예외는 차례를 멈춘다
+    def fail(cargos, today):
+        raise ValueError("DEMO0005 기한 계산 실패")
+
+    monkeypatch.setattr(tools, "cargo_deadlines", fail)
+    failing = agent_deps(model=ToolModel(messages=iter([say("calc_deadlines", {}, 5)])))
+    graph = build_main_graph(failing, InMemorySaver(), loop="agent", store=InMemoryStore())
+    with pytest.raises(ValueError, match="DEMO0005"):
+        graph.invoke(
+            {"text": "언제까지예요?"}, {"configurable": {"thread_id": "tool"}, "callbacks": callbacks}
+        )
+
+    # 4) 도구가 오류 결과(status="error")를 돌려주는 길: Langfuse가 그 글을 span 상태 설명에 넣는다
+    @tool
+    def refuse(token: str) -> ToolMessage:
+        """오류 결과를 돌려주는 도구."""
+        return ToolMessage("DEMO0007 조회 실패", tool_call_id="t7", status="error")
+
+    call = {"name": "refuse", "args": {"token": "[BL1]"}, "id": "t7", "type": "tool_call"}
+    refuse.invoke(call, {"callbacks": callbacks})
+
+    # 5) 다른 라이브러리의 OTel span(MCP 서버 꼴): 트레이서가 놓은 전역 TracerProvider로 들어온다
+    with get_tracer("mcp-python-sdk").start_as_current_span(
+        "tools/call search_law", attributes={"gen_ai.tool.name": "search_law"}
+    ) as span:
+        span.record_exception(ValueError("DEMO0008 검색 실패"))
+        span.set_status(StatusCode.ERROR, "DEMO0008 검색 실패")
+    return answer
+
+
+def test_every_exported_span_field_is_free_of_numbers(agent_deps, monkeypatch):
+    calls: list = []
+    monkeypatch.setattr(socket.socket, "connect", lambda self, address: calls.append(address))
+    exporter, key, handler = tracer()
+    answer = gate_run(agent_deps, monkeypatch, [handler])
+    spans = exported(exporter, key)
+    dump = "".join(spans)
+    with monkeypatch.context() as bare:  # [왜] 가림을 모두 빼면 실패하는 시험인지 같은 길로 먼저 본다
+        strip(bare, *LAYERS)
+        raw_exporter, raw_key, raw_handler = tracer()
+        raw_answer = gate_run(agent_deps, bare, [raw_handler])
+        raw = exported(raw_exporter, raw_key)
+    assert [number for number in GATE if number not in "".join(raw)] == []
+    assert [number for number in GATE if number in dump] == []
+    # [왜] 가려도 SDK span은 하나도 빠지지 않는다. 빠지는 것은 다른 라이브러리 span(⓪) 하나뿐이다
+    assert MASK in dump and len(spans) == len(raw) - len(OTHER)
+    assert "DEMO0001" in answer and answer == raw_answer  # 가림은 트레이스에만, 답은 그대로
+    assert calls == []  # Langfuse 주소로 연결하지 않았다
+
+
+@pytest.mark.parametrize(
+    "layer, left",
+    [("should_export_span", OTHER), ("mask", SAID + ASKED), ("mask_otel_spans", ASKED), ("errors", FAILED)],
+)
+def test_removing_any_one_layer_leaves_its_numbers(agent_deps, monkeypatch, layer, left):
+    strip(monkeypatch, layer)
+    exporter, key, handler = tracer()
+    gate_run(agent_deps, monkeypatch, [handler])
+    dump = "".join(exported(exporter, key))
+    assert [number for number in left if number not in dump] == []
+
+
+def test_a_failing_mask_exports_nothing_or_masks_the_value_whole(monkeypatch):
+    def boom(**_):
+        raise RuntimeError("가림 실패")
+
+    step = RunnableLambda(lambda text: text)
+    for name, expected in (("scrub_spans", "nothing"), ("scrub", "masked")):
+        with monkeypatch.context() as broken:
+            broken.setattr(langfuse_trace, name, boom)
+            exporter, key, handler = tracer()
+            step.invoke("DEMO0001", {"callbacks": [handler]})
+            spans = exported(exporter, key)
+        # [왜] ②가 죽으면 SDK가 묶음을 통째로 버리고, ①이 죽으면 값을 통째로 가린 글로 바꾼다
+        assert spans == [] if expected == "nothing" else spans and "DEMO0001" not in "".join(spans), name
```

```bash
uv run pytest -q tests/graph/test_trace.py
```

Expected: FAIL. 모음 오류 `ModuleNotFoundError: No module named 'langfuse'`

- [ ] **Step 2: 의존성**

```bash
uv add "langfuse==5.0.4"
uv run pytest -q tests/graph/test_trace.py
```

Expected: `pyproject.toml`의 dependencies에 `"langfuse==5.0.4",` 한 줄(`langchain-anthropic` 다음). 새로 설치되는 패키지 11개: backoff 2.2.1, googleapis-common-protos 1.76.0, langfuse 5.0.4, opentelemetry-exporter-http-transport 0.66b2, opentelemetry-exporter-otlp-common 0.66b2, opentelemetry-exporter-otlp-proto-common 1.45.2, opentelemetry-exporter-otlp-proto-http 1.45.2, opentelemetry-proto 1.45.2, opentelemetry-sdk 1.45.2, opentelemetry-semantic-conventions 0.66b2, wrapt 2.5.2. `uv.lock`은 더하기만 있다(이미 잠긴 패키지의 판이 바뀌지 않는다). 시험은 아직 FAIL: 모음 오류 `ImportError: cannot import name 'langfuse_trace' from 'marvia'` [실측 11-07]

- [ ] **Step 3: 코드**

```diff
--- /dev/null
+++ b/src/marvia/langfuse_trace.py
@@ -0,0 +1,115 @@
+"""Langfuse로 내보내는 트레이스를 네 겹으로 가린다 (설계 11절·12절, 계획 6b, done 3.9).
+
+⓪ should_export_span=is_langfuse_span: Langfuse SDK가 만든 span만 내보낸다. 다른 라이브러리의 OTel span
+   (MCP 서버의 gen_ai span 등)은 ①·③을 거치지 않고 예외 사건·상태 설명을 그대로 싣는다.
+① mask=scrub: span의 input·output·metadata를 JSON으로 바꾸기 전에 가린다(trace.scrub).
+② mask_otel_spans=scrub_spans: 내보내기 직전 span 속성 중 ①이 맡지 않는 글(status_message 등)을 가린다.
+③ ScrubbedHandler: 오류를 가린 사본으로 넘긴다. span 상태 설명(status.description)은 ①·②가 닿지 않는다.
+하나라도 빼면 tests/graph/test_trace.py의 문 시험이 실패한다(test_removing_any_one_layer_leaves_its_numbers).
+하지 않는 일: 켜고 끄기와 키 읽기(trace.tracer_callbacks). 이 모듈은 키가 셋 다 있을 때만 불러온다.
+"""
+
+from __future__ import annotations
+
+from typing import Any
+
+from langchain_core.messages import ToolMessage
+from langfuse import Langfuse
+from langfuse.langchain import CallbackHandler
+from langfuse.span_filter import is_langfuse_span
+from langfuse.types import MaskOtelSpansParams, MaskOtelSpansResult, OtelSpanPatch
+from langgraph.errors import GraphBubbleUp
+from opentelemetry.sdk.trace.export import SpanExporter
+
+from marvia.trace import scrub, scrub_text
+
+# [왜] ①이 JSON으로 바꾸기 전에 가린 칸이다. ②가 JSON 글을 다시 가리면 \u 이스케이프가 깨진다
+#      (11-07 실측: "제241조"를 적은 \uc81c241이 번호 후보로 가려져 JSON을 읽을 수 없게 된다)
+PAYLOAD = (
+    "langfuse.observation.input",
+    "langfuse.observation.output",
+    "langfuse.observation.metadata",
+    "langfuse.trace.metadata",
+)
+
+
+def _clean(value: Any) -> Any:
+    """속성 값 하나를 가린다. 글 목록(OTel은 tuple로 둔다)은 글만 가린다."""
+    if isinstance(value, str):
+        return scrub_text(value)
+    if isinstance(value, (list, tuple)):
+        return tuple(scrub_text(item) if isinstance(item, str) else item for item in value)
+    return value
+
+
+def scrub_spans(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult:
+    """② 내보내기 직전 span 속성의 글을 가린다. 바뀐 속성만 고친다.
+
+    [주의] 여기서 예외가 나면 Langfuse는 그 묶음을 통째로 버린다(아무것도 나가지 않는다).
+    """
+    patches = {}
+    for key, span in params.spans.items():
+        changed = {
+            name: _clean(value)
+            for name, value in span.attributes.items()
+            if not name.startswith(PAYLOAD) and _clean(value) != value
+        }
+        if changed:
+            patches[key] = OtelSpanPatch(set_attributes=changed)
+    return MaskOtelSpansResult(span_patches=patches)
+
+
+class ScrubbedError(Exception):
+    """가린 오류 글만 지닌 예외. 원래 예외는 Langfuse에 넘기지 않는다."""
+
+
+def _scrubbed(error: BaseException) -> BaseException:
+    """오류를 가린 사본으로 바꾼다. 끼어들기(GraphBubbleUp)는 그대로 둔다."""
+    # [왜] 끼어들기는 Langfuse가 오류 단계로 보지 않아(DEFAULT) span 상태 설명을 쓰지 않는다.
+    #      질문 글이 드는 status_message 속성은 ②가 가린다
+    if isinstance(error, GraphBubbleUp):
+        return error
+    # [왜] 예외 이름은 코드가 정한 글이라 남긴다. 글은 scrub이 str()이 죽는 예외까지 받아 가린다
+    return ScrubbedError(f"{type(error).__name__}: {scrub(error)}")
+
+
+class ScrubbedHandler(CallbackHandler):
+    """③ 오류와 오류 도구 결과를 가린 사본으로 받는 Langfuse 콜백."""
+
+    def on_chain_error(self, error: BaseException, **kwargs: Any) -> Any:
+        return super().on_chain_error(_scrubbed(error), **kwargs)
+
+    def on_tool_error(self, error: BaseException, **kwargs: Any) -> Any:
+        return super().on_tool_error(_scrubbed(error), **kwargs)
+
+    def on_llm_error(self, error: BaseException, **kwargs: Any) -> Any:
+        return super().on_llm_error(_scrubbed(error), **kwargs)
+
+    def on_retriever_error(self, error: BaseException, **kwargs: Any) -> Any:
+        return super().on_retriever_error(_scrubbed(error), **kwargs)
+
+    def on_tool_end(self, output: Any, **kwargs: Any) -> Any:
+        # [왜] 도구가 오류 결과(status="error")를 내면 Langfuse가 그 글을 span 상태 설명에도 넣는다
+        if isinstance(output, ToolMessage) and output.status == "error":
+            output = output.model_copy(update={"content": scrub(output.content)})
+        return super().on_tool_end(output, **kwargs)
+
+
+def build(
+    public_key: str, secret_key: str, host: str, exporter: SpanExporter | None = None
+) -> CallbackHandler:
+    """가린 Langfuse 클라이언트를 만들고 그 콜백을 돌려준다. exporter는 시험이 메모리로 받을 때만 준다."""
+    # [왜] 키와 주소는 인자로만 넘긴다. 인자가 없으면 SDK가 LANGFUSE_* 환경 변수를 읽는다
+    # [주의] SDK는 전역 OTel TracerProvider가 없으면 자기 것을 전역으로 놓는다(resource_manager.py).
+    #        그 뒤 다른 라이브러리의 span도 여기로 오고, 기본 거름은 gen_ai 속성이 있으면 내보낸다
+    Langfuse(
+        public_key=public_key,
+        secret_key=secret_key,
+        base_url=host,
+        should_export_span=is_langfuse_span,
+        mask=scrub,
+        mask_otel_spans=scrub_spans,
+        span_exporter=exporter,
+    )
+    # [왜] 콜백은 공개키로 위 클라이언트를 찾는다(langfuse.get_client의 공개키별 등록부)
+    return ScrubbedHandler(public_key=public_key)
```

- [ ] **Step 4: 확인**: 명령 A. Expected: `800 passed`, 오류 0.

- [ ] **Step 5: 이미지 크기와 이미지 안 import (C5)**: 저장소 뿌리에서 돌리고 결과를 T5에서 `docs/deploy.md`의 크기 줄에 옮긴다.

```bash
set -o pipefail
docker buildx build --platform linux/amd64 --target runtime -t marvia-api:6b-amd64 --load .
docker run --rm --platform linux/amd64 marvia-api:6b-amd64 python -c "import langfuse, marvia.langfuse_trace; print('ok')"
docker image ls marvia-api:6b-amd64
curl -sG --unix-socket "$(docker context inspect --format '{{.Endpoints.docker.Host}}' | sed 's#unix://##')" \
  http://localhost/images/json --data-urlencode 'filters={"reference":["marvia-api:6b-amd64"]}' \
  | python3 -c 'import json,sys; print([i["Size"] for i in json.load(sys.stdin)])'
docker image rm marvia-api:6b-amd64
```

Expected [실측 11-08, 검증 사본]: 빌드 성공(약 1~2분), `ok`, DISK USAGE `1.2GB`, 바이트 `[1198942988]` 근처(1,200,000,000 이하). [주의] 이 컴퓨터의 Docker(containerd 이미지 저장소)에서는 `docker image inspect`의 `.Size`가 받은 층(압축)만 센다(337,618,194). 계획 4b의 1.18GB는 DISK USAGE와 같은 값이고, 다른 플랫폼 이미지는 `docker run`으로 한 번 층을 풀기 전까지 DISK USAGE도 압축 크기만 보인다. 그래서 `docker run` 뒤에 읽는다.

- [ ] **Step 6 (C5를 넘을 때만): langfuse를 선택 extra로**. 11-07 결정대로 이미지에는 넣지 않는다. 이 단계는 검증 사본에서 돌리지 않았다.

```bash
uv remove langfuse
uv add --optional tracing "langfuse==5.0.4"
uv add --dev "langfuse==5.0.4"   # [왜] 시험은 키 없이도 SDK를 쓴다(문 시험). 이미지(--no-dev)에는 들어가지 않는다
```

`docs/deploy.md`에 "트레이스를 켜는 이미지는 Dockerfile의 두 `uv sync`에 `--extra tracing`을 더해 따로 만든다. 기본 이미지에서 키 셋을 넣으면 첫 차례 전에 `ModuleNotFoundError`로 서버가 뜨지 않는다"를 적고, Step 4·5를 다시 돈다.

- [ ] **Step 7: 커밋**

```bash
git add pyproject.toml uv.lock src/marvia/langfuse_trace.py tests/graph/test_trace.py
git commit -m "feat(trace): 네 겹으로 가린 Langfuse 핸들러 (langfuse 5.0.4)"
```

### Task 2: 키 셋이 모두 있을 때만 켠다 (C1)

**배울 것:** 꺼짐을 "만들지 않음"으로 지킨다. `tracer_callbacks`는 키 셋을 보고, 하나라도 비면 SDK를 import하는 줄에 닿지 않는다(함수 안 import). 이미 langfuse를 불러온 시험 프로세스로는 "import하지 않음"을 볼 수 없어 새 파이썬 프로세스에서 `sys.modules`·스레드 수·소켓 연결을 본다. 셋이 다 있으면 `functools.cache`가 콜백을 하나만 만들어 프로세스가 함께 쓴다. `SecretStr`은 repr에 값을 내지 않는다.

#### 커밋 2: feat(trace): 키가 셋 다 있을 때만 트레이서 콜백

**Files:**
- Modify: `src/marvia/config.py`, `src/marvia/trace.py`, `.env.example`
- Test: `tests/graph/test_trace.py`

**Interfaces:**
- Consumes: `langfuse_trace.build` (커밋 1)
- Produces: `trace.tracer_callbacks(settings: Settings) -> list`, `Settings.langfuse_public_key: SecretStr`, `Settings.langfuse_secret_key: SecretStr`, `Settings.langfuse_host: str`

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_trace.py
+++ b/tests/graph/test_trace.py
@@ -1,7 +1,10 @@
 """트레이스 가림 문 시험 (R-010·R-022·R-039, done 3.9, 계획 6b). 기록 콜백·메모리 내보내기로 키 없이 본다."""
 
 import json
+import os
 import socket
+import subprocess
+import sys
 from uuid import uuid4
 
 import pytest
@@ -21,11 +24,12 @@ from langgraph.types import Command, Send
 from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
 from opentelemetry.trace import StatusCode, get_tracer
 
-from marvia import langfuse_trace
+from marvia import langfuse_trace, trace
+from marvia.config import Settings
 from marvia.graph import tools
 from marvia.graph.main import build_main_graph
 from marvia.graph.schemas import Draft
-from marvia.trace import MASK, scrub
+from marvia.trace import MASK, scrub, tracer_callbacks
 from marvia.watch import WatchDeps
 
 NUMBERS = ("DEMO0001", "DEMO0002", "DEMO0003", "DEMO0004")
@@ -341,3 +345,49 @@ def test_a_failing_mask_exports_nothing_or_masks_the_value_whole(monkeypatch):
             spans = exported(exporter, key)
         # [왜] ②가 죽으면 SDK가 묶음을 통째로 버리고, ①이 죽으면 값을 통째로 가린 글로 바꾼다
         assert spans == [] if expected == "nothing" else spans and "DEMO0001" not in "".join(spans), name
+
+
+OFF = """
+import socket, sys, threading
+calls = []
+socket.socket.connect = lambda self, address: calls.append(address)
+from marvia.config import Settings
+from marvia.trace import tracer_callbacks
+before = threading.active_count()
+callbacks = tracer_callbacks(Settings(_env_file=None))
+print(callbacks, "langfuse" in sys.modules, threading.active_count() - before, calls)
+"""
+
+
+def test_without_keys_tracing_is_off_with_no_sdk_thread_or_socket():
+    # [왜] 이미 langfuse를 불러온 이 시험 프로세스가 아니라 새 프로세스에서 본다
+    env = {name: value for name, value in os.environ.items() if not name.startswith("MARVIA_LANGFUSE_")}
+    done = subprocess.run([sys.executable, "-c", OFF], capture_output=True, text=True, check=True, env=env)
+    assert done.stdout.split() == ["[]", "False", "0", "[]"]  # 콜백 없음, SDK 안 부름, 스레드 0, 연결 0
+
+
+@pytest.mark.parametrize(
+    "given",
+    [{"langfuse_public_key": "pk-x", "langfuse_secret_key": "sk-x"}, {"langfuse_host": "https://x.test"}],
+)
+def test_tracing_stays_off_unless_all_three_settings_are_given(monkeypatch, given):
+    for name in ("MARVIA_LANGFUSE_PUBLIC_KEY", "MARVIA_LANGFUSE_SECRET_KEY", "MARVIA_LANGFUSE_HOST"):
+        monkeypatch.delenv(name, raising=False)  # [왜] 셸에 걸린 값이 빈 칸을 채우지 않게 한다
+    assert tracer_callbacks(Settings(_env_file=None, **given)) == []
+
+
+def test_all_three_settings_give_one_shared_tracer_and_keys_stay_hidden(monkeypatch):
+    built = []
+    monkeypatch.setattr(langfuse_trace, "build", lambda *keys: built.append(keys) or object())
+    trace._handler.cache_clear()
+    settings = Settings(
+        _env_file=None,
+        langfuse_public_key="pk-x",
+        langfuse_secret_key="sk-secret",
+        langfuse_host="https://x.test",
+    )
+    first, second = tracer_callbacks(settings), tracer_callbacks(settings)
+    trace._handler.cache_clear()
+    assert len(first) == 1 and first[0] is second[0]  # [왜] 멈춘 차례와 재개한 차례가 한 트레이스로 이어진다
+    assert built == [("pk-x", "sk-secret", "https://x.test")]
+    assert "sk-secret" not in repr(settings) and "pk-x" not in repr(settings)
```

```bash
uv run pytest -q tests/graph/test_trace.py
```

Expected: FAIL. 모음 오류 `ImportError: cannot import name 'tracer_callbacks' from 'marvia.trace'`

- [ ] **Step 2: 코드**

```diff
--- a/.env.example
+++ b/.env.example
@@ -43,3 +43,10 @@ MARVIA_DEV_TOKEN=
 MARVIA_WEB_ORIGIN=
 # 서버가 듣는 주소. 비우면 127.0.0.1. 컨테이너 안에서만 0.0.0.0으로 둔다(Dockerfile·compose가 준다)
 MARVIA_HOST=
+
+# 트레이스(Langfuse). 셋이 모두 있어야 켜진다. 비우면 꺼진다(기본). 보내는 값은 모두 화물 번호를 가린 값이다
+# hajeongun.dev 계정의 Langfuse 프로젝트 설정에서 키를 만든다. 접두어 없는 LANGFUSE_* 이름은 쓰지 않는다(서버가 뜨지 않는다)
+MARVIA_LANGFUSE_PUBLIC_KEY=
+MARVIA_LANGFUSE_SECRET_KEY=
+# Langfuse 주소. 예: https://cloud.langfuse.com (EU), https://us.cloud.langfuse.com (US), 직접 띄운 서버 주소
+MARVIA_LANGFUSE_HOST=
--- a/src/marvia/config.py
+++ b/src/marvia/config.py
@@ -73,3 +73,9 @@ class Settings(BaseSettings):
     dev_token: SecretStr = SecretStr("")  # MARVIA_DEV_TOKEN. auth=dev일 때만 받는 고정 토큰
     host: str = "127.0.0.1"  # MARVIA_HOST. 서버가 듣는 주소. 컨테이너(Dockerfile·compose)만 0.0.0.0으로 연다
     web_origin: str = "http://localhost:3000"  # MARVIA_WEB_ORIGIN. 화면 주소. CORS는 이 origin만 연다
+
+    # 트레이스 (계획 6b, 설계 11절·12절). [왜] 셋이 모두 있을 때만 Langfuse로 보낸다. 하나라도 비면 SDK를
+    # 불러오지도 않는다(trace.tracer_callbacks). 보내는 값은 모두 번호를 가린 값이다(langfuse_trace)
+    langfuse_public_key: SecretStr = SecretStr("")  # MARVIA_LANGFUSE_PUBLIC_KEY
+    langfuse_secret_key: SecretStr = SecretStr("")  # MARVIA_LANGFUSE_SECRET_KEY
+    langfuse_host: str = ""  # MARVIA_LANGFUSE_HOST (예: https://cloud.langfuse.com). 비밀이 아니다
--- a/src/marvia/trace.py
+++ b/src/marvia/trace.py
@@ -1,12 +1,11 @@
-"""트레이스(콜백·Langfuse)로 나가는 값에서 화물 번호를 가린다 (설계 12절, done 3.9 문: R-010·R-022·R-039).
-
-하지 않는 일: 트레이서 연결. Langfuse 키가 없어 연결은 미뤘다.
-[주의] 연결할 때 scrub만 mask=에 끼워서는 모자라다. Langfuse는 mask(data=...)로
-       input·output·metadata만 부르고, 오류 길(on_chain_error·on_tool_error)의
-       status_message(str(error))는 mask에 넘기지 않는다.
-       애매한 번호를 묻는 끼어들기(identify의 ask)는 실제 번호 조각을 질문에 넣으므로 GraphInterrupt의
-       str()에 실제 번호가 든다. 연결하는 쪽이 오류 길도 가려야 하고(예: 핸들러를 감싸 가린 예외를 넘김),
-       그 문 시험은 내보낸 span 속성(status_message 포함)을 보고 ask 끼어들기를 시나리오에 넣어야 한다.
+"""트레이스로 나가는 값에서 화물 번호를 가리고, 트레이서를 켤지 정한다 (설계 12절, done 3.9, 계획 6b).
+
+scrub: 콜백 값을 걸어 다니며 번호 덩어리를 가린다. Langfuse의 mask=로 쓴다(langfuse_trace의 ①).
+tracer_callbacks: 그래프 실행 설정에 넣을 콜백. 서버·CLI·평가가 모두 이 함수로만 트레이서를 붙인다.
+하지 않는 일: Langfuse SDK 다루기(langfuse_trace.py). 키가 없으면 이 모듈은 langfuse를 import하지 않는다.
+[주의] scrub만으로는 모자라다. Langfuse는 mask=에 input·output·metadata만 넘기고, 오류 글(status_message,
+       span 상태 설명)은 넘기지 않는다. 애매한 번호를 묻는 끼어들기(identify의 ask)는 실제 번호 조각을
+       질문에 넣는다. 그래서 langfuse_trace가 ②·③으로 오류 길을 따로 가린다.
 [왜] 상태 없이 글 모양으로 찾는다. 콜백에는 그 대화의 가림 표가 오지 않고, 번호는 노드 입력·출력,
      도구 결과, Send 묶음, 도구 안에서 부른 서브그래프, 답 어디에든 들 수 있다.
 [주의] 번호처럼 생긴 다른 글(8자 이상 영문·숫자 덩어리)도 함께 가린다. 트레이스에서는 덜 가리는 것보다 낫다.
@@ -18,11 +17,13 @@
 from __future__ import annotations
 
 import dataclasses
+import functools
 from typing import Any
 
 from langgraph.types import Send
 from pydantic import BaseModel
 
+from marvia.config import Settings
 from marvia.identify.parse import find_spans
 
 MASK = "[가림]"
@@ -93,3 +94,24 @@ def _walk(value: Any, active: set[int]) -> Any:
         return {field.name: _walk(getattr(value, field.name), active) for field in dataclasses.fields(value)}
     # [주의] 모르는 객체(날짜, 예외, 도구 실행 정보 등)는 글로 바꿔 가린다. 원래 객체를 그대로 내보내지 않는다
     return _text_of(value)
+
+
+@functools.cache
+def _handler(public_key: str, secret_key: str, host: str) -> Any:
+    """프로세스가 함께 쓰는 가린 Langfuse 콜백 하나."""
+    from marvia.langfuse_trace import build  # [왜] 여기서만 SDK를 불러온다. 꺼져 있으면 스레드·소켓이 없다
+
+    return build(public_key, secret_key, host)
+
+
+def tracer_callbacks(settings: Settings) -> list:
+    """그래프 실행 설정의 callbacks에 넣을 목록. MARVIA_LANGFUSE_* 셋 중 하나라도 비면 []다(기본은 꺼짐).
+
+    [왜] 콜백 하나를 함께 쓴다. 끼어들기로 멈춘 차례와 재개한 차례가 한 트레이스로 이어진다.
+    """
+    keys = (
+        settings.langfuse_public_key.get_secret_value(),
+        settings.langfuse_secret_key.get_secret_value(),
+        settings.langfuse_host,
+    )
+    return [_handler(*keys)] if all(keys) else []
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `804 passed`, 오류 0.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/config.py src/marvia/trace.py .env.example tests/graph/test_trace.py
git commit -m "feat(trace): 키가 셋 다 있을 때만 트레이서 콜백"
```

### Task 3: 접두어 없는 `LANGFUSE_*`가 있으면 서버가 뜨지 않는다 (C1)

**배울 것:** SDK는 인자로 받지 않은 키·주소·설정을 환경 변수에서 읽는다. LangSmith(R-069)처럼 환경 변수만으로 켜지는 길을 시작 검사에서 막는다. 시험 프로세스는 셸의 환경 변수를 물려받으므로, 셸에 `LANGFUSE_*`가 남아 있어도 기존 시작 검사 시험이 흔들리지 않게 autouse 준비물이 지운다.

#### 커밋 3: feat(auth): LANGFUSE_* 환경 변수가 있으면 서버가 뜨지 않음

**Files:**
- Modify: `src/marvia/auth.py`
- Test: `tests/test_auth.py`, `tests/conftest.py`

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -1,5 +1,6 @@
 """모든 시험이 함께 쓰는 준비물: 로컬 DB의 시험용 스키마(db, test_url). 처음엔 tests/rag에만 있었다."""
 
+import os
 from uuid import uuid4
 
 import psycopg
@@ -24,6 +25,13 @@ def unipass_replay_only(monkeypatch):
     monkeypatch.setenv("MARVIA_UNIPASS_MODE", "replay")
 
 
+@pytest.fixture(autouse=True)
+def no_raw_langfuse_env(monkeypatch):
+    """셸에 걸린 LANGFUSE_* 환경 변수를 지운다. [왜] 서버 시작 검사가 그 이름을 거절한다 (계획 6b)"""
+    for name in [name for name in os.environ if name.startswith("LANGFUSE_")]:
+        monkeypatch.delenv(name)
+
+
 @pytest.fixture
 def db():
     """시험용 스키마에 표를 만들고 끝나면 스키마째 지운다. 로컬 DB가 꺼져 있으면 건너뛴다."""
--- a/tests/test_auth.py
+++ b/tests/test_auth.py
@@ -9,7 +9,15 @@ import jwt
 import pytest
 from cryptography.hazmat.primitives.asymmetric import ec
 
-from marvia.auth import DEV_USER, AuthError, check_startup, dev_verifier, supabase_verifier, user_from_header
+from marvia.auth import (
+    DEV_USER,
+    TRACING_VARS,
+    AuthError,
+    check_startup,
+    dev_verifier,
+    supabase_verifier,
+    user_from_header,
+)
 from marvia.config import Settings
 
 BASE = "https://demo.supabase.test"
@@ -134,6 +142,28 @@ def test_the_server_refuses_to_start_with_langsmith_tracing_on(monkeypatch, name
     check_startup(ok)  # 꺼 두면 뜬다
 
 
+@pytest.mark.parametrize(
+    "name", ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_TRACING_ENVIRONMENT"]
+)
+def test_the_server_refuses_to_start_with_a_raw_langfuse_env_var(monkeypatch, name):
+    # [왜] SDK가 이 이름을 직접 읽어 가림 연결(MARVIA_LANGFUSE_*) 밖에서 켜질 수 있다 (계획 6b)
+    for var in ("K_SERVICE", *TRACING_VARS):
+        monkeypatch.delenv(var, raising=False)
+    monkeypatch.setenv(name, "x")
+    ok = Settings(
+        _env_file=None,
+        supabase_url=BASE,
+        owner_ids="owner-1",
+        langfuse_public_key="pk-x",
+        langfuse_secret_key="sk-x",
+        langfuse_host="https://x.test",
+    )
+    with pytest.raises(RuntimeError, match=name):
+        check_startup(ok)
+    monkeypatch.delenv(name)
+    check_startup(ok)  # MARVIA_LANGFUSE_*만 있으면 뜬다
+
+
 def over_the_wire(monkeypatch, reply):
     """JWKS 받기를 네트워크 없이 바꿔 끼운다. reply가 예외면 던지고, 아니면 그 바이트를 200 본문으로 준다."""
     asked = []
```

```bash
uv run pytest -q tests/test_auth.py -k langfuse
```

Expected: `3 failed`, 모두 `Failed: DID NOT RAISE RuntimeError`

- [ ] **Step 2: 코드**

```diff
--- a/src/marvia/auth.py
+++ b/src/marvia/auth.py
@@ -4,7 +4,8 @@
 - supabase(기본): Supabase Auth가 발급한 JWT를 공개키(JWKS, ES256)로 확인한다. aud·iss·exp·sub가 없으면
   거절하고, sub가 소유자 목록(MARVIA_OWNER_IDS)에 없으면 403이다. 우리 쪽에 JWT 비밀값을 두지 않는다.
 - dev: 이 컴퓨터에서 화면을 돌려 볼 때만 쓰는 고정 토큰(MARVIA_DEV_TOKEN). 사용자는 DEV_USER 하나다.
-시작 검사(check_startup)는 트레이싱 환경 변수(R-069)와 로그인 설정(https, 소유자, 개발 로그인)을 본다.
+시작 검사(check_startup)는 트레이싱 환경 변수(R-069, 계획 6b의 LANGFUSE_*)와
+로그인 설정(https, 소유자, 개발 로그인)을 본다.
 하지 않는 일: 로그인 화면·가입(Supabase가 한다), 토큰 발급. 가입 막기는 Supabase 설정에서 한다(배포 절차서).
 """
 
@@ -54,6 +55,11 @@ def check_startup(settings: Settings) -> None:
             raise RuntimeError(
                 f"{name}=true라 트레이스가 켜집니다. 가림(scrub) 없이 밖으로 나가므로 시작하지 않습니다"
             )
+    # [왜] Langfuse SDK는 인자로 받지 않은 키·주소·설정을 LANGFUSE_* 환경 변수에서 읽는다. 가림을 거치는
+    #      연결은 MARVIA_LANGFUSE_*(trace.tracer_callbacks)뿐이라, 접두어 없는 이름이 있으면 뜨지 않는다
+    raw = sorted(name for name in os.environ if name.startswith("LANGFUSE_"))
+    if raw:
+        raise RuntimeError(f"{raw[0]} 환경 변수가 있습니다. Langfuse는 MARVIA_LANGFUSE_*로만 켭니다")
     if settings.auth == "dev":
         # [왜] K_SERVICE는 Cloud Run이 넣는 환경 변수다. 개발 로그인이 운영에 켜진 채 배포되는 일을 막는다
         if os.environ.get("K_SERVICE"):
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `807 passed`, 오류 0.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/auth.py tests/test_auth.py tests/conftest.py
git commit -m "feat(auth): LANGFUSE_* 환경 변수가 있으면 서버가 뜨지 않음"
```

### Task 4: 서버·CLI·평가가 같은 콜백을 쓴다 (C4)

**배울 것:** LangGraph는 실행 설정의 `callbacks`를 서브그래프, Send 갈래, 도구 안에서 부른 서브그래프까지 넘긴다. 컴파일한 그래프에 `with_config(callbacks=...)`로 둔 콜백은 차례마다 넘기는 실행 설정과 합쳐진다. 서버는 이 방식으로, CLI와 평가는 실행 설정 dict에 직접 넣는다.

#### 커밋 4: feat(server): 서버·CLI·평가가 같은 트레이서 콜백을 씀

**Files:**
- Modify: `src/marvia/server.py`, `scripts/try_agent.py`, `src/marvia/eval/run.py`, `scripts/run_eval.py`
- Test: `tests/graph/test_server.py`, `tests/graph/test_eval_run.py`

**Interfaces:**
- Consumes: `trace.tracer_callbacks` (커밋 2), `langfuse_trace.build` (커밋 1, 시험만)
- Produces: `build_app(..., callbacks: Sequence[BaseCallbackHandler] = ())`, `evaluate_item(..., callbacks: Sequence[BaseCallbackHandler] = ())`, 평가 결과 `meta["tracing"]`(`"on"`·`"off"`)

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_eval_run.py
+++ b/tests/graph/test_eval_run.py
@@ -4,6 +4,7 @@ import json
 from dataclasses import replace
 from pathlib import Path
 
+from langchain_core.callbacks import BaseCallbackHandler
 from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
 from langchain_core.messages import AIMessage, HumanMessage
 
@@ -444,3 +445,19 @@ def test_run_problems_treat_a_missing_or_live_unipass_mode_as_invalid():
     assert run_problems(base, [], clean, set()) == expect
     assert run_problems(base | {"unipass_mode": "live"}, [], clean, set()) == expect
     assert run_problems(base | {"unipass_mode": "replay"}, [], clean, set()) == []
+
+
+def test_evaluate_item_runs_the_graph_with_the_tracer_callbacks(agent_deps):
+    # [왜] 평가도 서버·CLI와 같은 트레이서 콜백(trace.tracer_callbacks)을 받는다 (계획 6b)
+    class Seen(BaseCallbackHandler):
+        def __init__(self):
+            self.chains = 0
+
+        def on_chain_start(self, serialized, inputs, **kwargs):
+            self.chains += 1
+
+    seen = Seen()
+    evaluate_item(
+        agent_deps(), item("DEMO0001 언제까지 수입신고 해요?"), "planner", TODAY, PRICES, callbacks=[seen]
+    )
+    assert seen.chains > 0
--- a/tests/graph/test_server.py
+++ b/tests/graph/test_server.py
@@ -5,6 +5,7 @@ import json
 import logging
 import threading
 from types import SimpleNamespace
+from uuid import uuid4
 
 import psycopg
 import pytest
@@ -12,11 +13,14 @@ from cryptography.fernet import Fernet
 from langchain_core.callbacks import BaseCallbackHandler
 from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
 from langchain_core.messages import AIMessage
+from langfuse import get_client
 from langgraph.checkpoint.memory import InMemorySaver
 from langgraph.store.memory import InMemoryStore
+from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
 from psycopg.conninfo import make_conninfo
 from starlette.testclient import TestClient
 
+from marvia import langfuse_trace
 from marvia.auth import TRACING_VARS, AuthError
 from marvia.config import Settings
 from marvia.graph.live import live_memory
@@ -468,11 +472,13 @@ def test_main_listens_on_loopback_unless_marvia_host_says_otherwise(
     monkeypatch.setattr(server.psycopg, "connect", fake)
     monkeypatch.setattr(server, "agent_deps", lambda *a: None)
     monkeypatch.setattr(server, "build_main_graph", lambda *a, **k: None)
-    monkeypatch.setattr(server, "build_app", lambda *a, **k: None)
+    monkeypatch.setattr(server, "tracer_callbacks", lambda settings: ["tracer"])
+    monkeypatch.setattr(server, "build_app", lambda *a, **k: seen.update(callbacks=k["callbacks"]))
     monkeypatch.setattr(server.uvicorn, "run", lambda app, **kwargs: seen.update(kwargs))
     monkeypatch.setenv("PORT", "9999")
     server.main()
-    assert seen == {"host": expected, "port": 9999}
+    # [왜] 서버도 CLI·평가와 같은 트레이서 콜백(trace.tracer_callbacks)을 앱에 넘긴다 (계획 6b)
+    assert seen == {"host": expected, "port": 9999, "callbacks": ["tracer"]}
 
 
 def test_a_failed_run_sends_the_fixed_error_text_and_the_next_request_is_served():
@@ -701,3 +707,19 @@ def test_deleting_an_account_while_turns_start_and_finish_never_gives_500():
     [w.start() for w in workers]
     [w.join(60) for w in workers]
     assert codes and set(codes) <= {200, 204, 409}, sorted(set(codes))
+
+
+def test_a_traced_turn_exports_spans_without_numbers_and_still_answers_with_them(agent_deps):
+    # [왜] 서버 길도 가린 콜백을 지난다 (계획 6b). 메모리 내보내기라 키·서버·네트워크가 없다
+    exporter, key = InMemorySpanExporter(), f"pk-test-{uuid4().hex}"
+    tracer = langfuse_trace.build(key, "sk-test", "http://127.0.0.1:9", exporter)
+    deps = agent_deps(model=ToolModel(messages=iter([AIMessage("")])))
+    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
+    app = build_app(graph, verify, web_origin="http://web.test", forget=print, callbacks=[tracer])
+    events = run(TestClient(app), body("t30", "DEMO0001 언제까지?"))
+    client = get_client(public_key=key)
+    client.flush()
+    client.shutdown()
+    spans = exporter.get_finished_spans()
+    assert spans and all("DEMO0001" not in span.to_json() for span in spans)
+    assert any("DEMO0001" in event.get("delta", "") for event in events)  # 화면 답에는 실제 번호
```

```bash
uv run pytest -q tests/graph/test_server.py tests/graph/test_eval_run.py -k "tracer or traced or loopback"
```

Expected: `4 failed`: `test_main_listens_on_loopback_unless_marvia_host_says_otherwise` 둘이 `AttributeError: <module 'marvia.server' ...> has no attribute 'tracer_callbacks'`, 서버 시험이 `TypeError: build_app() got an unexpected keyword argument 'callbacks'`, 평가 시험이 `TypeError: evaluate_item() got an unexpected keyword argument 'callbacks'`

- [ ] **Step 2: 코드**

```diff
--- a/scripts/run_eval.py
+++ b/scripts/run_eval.py
@@ -356,6 +356,7 @@ from marvia.rag.edges import build_edges  # noqa: E402
 from marvia.rag.graphdb import connect_graph, graph_meta, units_sha256  # noqa: E402
 from marvia.rag.index import read_units  # noqa: E402
 from marvia.rag.items import items_sha256  # noqa: E402
+from marvia.trace import tracer_callbacks  # noqa: E402
 
 # [왜] 평가는 늘 UNI-PASS 재생 데이터로 돈다. .env가 live여도 실제 API를 부르지 않는다 (계획 3b Task 7)
 os.environ["MARVIA_UNIPASS_MODE"] = "replay"
@@ -377,6 +378,7 @@ if mismatch:
     raise SystemExit(f"[멈춤] {mismatch}")
 for model in models:
     settings = Settings(chat_model=model)
+    tracing = tracer_callbacks(settings)  # [왜] 서버·CLI와 같은 트레이서. 키가 없으면 빈 목록(꺼짐)
     with (
         connect(settings.database_url) as conn,
         read_pool(settings.database_url) as pool,  # [왜] 검색·조문 조회는 풀에서 빌린다 (R-066)
@@ -419,13 +421,14 @@ for model in models:
                 "refers_expected": refers_expected,
                 "unipass_mode": settings.unipass_mode,
                 "rag_via": settings.rag_via,
+                "tracing": "on" if tracing else "off",
             }
             name = result_name(loop, model, args.tag)
             for item in items:
                 if spent >= args.max_cost:
                     print(f"상한 ${args.max_cost}에 닿아 {item.id}부터 돌리지 않았다")
                     break
-                row, raw = evaluate_item(deps, item, loop, data.as_of, prices)
+                row, raw = evaluate_item(deps, item, loop, data.as_of, prices, callbacks=tracing)
                 row["model"] = model
                 rows.append(row)
                 raws.append(raw)
--- a/scripts/try_agent.py
+++ b/scripts/try_agent.py
@@ -9,6 +9,7 @@
       MARVIA_LOOP=agent uv run python scripts/try_agent.py --image bl.png "이 화물 지금 어디야?"
         (사진은 이 컴퓨터에서 OCR로 읽고 번호 덩어리만 질문 앞에 붙인다. Docker 안에서 돌린다)
 대화 기록(암호화)과 장기 기억은 로컬 Postgres에 남는다(live_memory).
+MARVIA_LANGFUSE_* 셋이 있으면 번호를 가린 트레이스를 Langfuse로 보낸다(trace.tracer_callbacks, 계획 6b).
 하지 않는 일: 비용 계산(scripts/compare_loops.py).
 """
 
@@ -26,6 +27,7 @@ from marvia.graph.main import build_main_graph
 from marvia.graph.resume import approval_reply
 from marvia.identify.mask import unmask
 from marvia.identify.ocr import photo_clues, read_image
+from marvia.trace import tracer_callbacks
 from marvia.watch import watch_keys
 
 parser = argparse.ArgumentParser(description="에이전트를 한 차례 돌린다")
@@ -48,7 +50,10 @@ except ValueError:
     # [주의] 키 값은 출력하지 않는다
     print("MARVIA_DATA_KEY가 없거나 올바른 키가 아닙니다. .env를 확인한 뒤 다시 실행하세요.")
     sys.exit(1)
-config = {"configurable": {"thread_id": args.thread, "user_id": args.user}}
+config = {
+    "configurable": {"thread_id": args.thread, "user_id": args.user},
+    "callbacks": tracer_callbacks(settings),
+}
 # [왜] get_usage_metadata_callback: 이 블록 안의 LLM 호출(RAG 서브그래프 안 포함)의 토큰 수를 모델별로 더한다
 with (
     connect(settings.database_url),  # [왜] 표가 없으면 만든다(마이그레이션). 읽기는 아래 풀로 한다
--- a/src/marvia/eval/run.py
+++ b/src/marvia/eval/run.py
@@ -13,6 +13,7 @@ from __future__ import annotations
 import json
 import re
 import time
+from collections.abc import Sequence
 from dataclasses import replace
 from datetime import date
 from pathlib import Path
@@ -278,9 +279,19 @@ def ragas_contexts(values: dict, row: dict, top: int, seen: dict[str, str]) -> d
 
 
 def evaluate_item(
-    deps: AgentDeps, item: Item, loop: str, today: date, prices: dict, *, permission_mode: str = "ask"
+    deps: AgentDeps,
+    item: Item,
+    loop: str,
+    today: date,
+    prices: dict,
+    *,
+    permission_mode: str = "ask",
+    callbacks: Sequence[BaseCallbackHandler] = (),
 ) -> tuple[dict, dict]:
-    """문항 하나를 새 대화로 돌려 (줄, raw)를 돌려준다. 예외가 나도 줄을 남긴다."""
+    """문항 하나를 새 대화로 돌려 (줄, raw)를 돌려준다. 예외가 나도 줄을 남긴다.
+
+    callbacks는 트레이서(trace.tracer_callbacks)다. 비어 있으면 트레이스를 남기지 않는다.
+    """
     log: list[dict] = []
     seen: dict[str, str] = {}
     graph = build_main_graph(
@@ -297,7 +308,7 @@ def evaluate_item(
     usage = None
     try:
         with get_usage_metadata_callback() as usage:
-            values, pauses = drive(graph, item, f"eval-{loop}-{item.id}", [watch])
+            values, pauses = drive(graph, item, f"eval-{loop}-{item.id}", [watch, *callbacks])
         row |= observe(values, pauses, watch, loop, log)
         row["error"] = None
         draft = values.get("draft") or {}
--- a/src/marvia/server.py
+++ b/src/marvia/server.py
@@ -20,7 +20,7 @@ import queue
 import re
 import threading
 import traceback
-from collections.abc import AsyncIterator, Callable, Iterator
+from collections.abc import AsyncIterator, Callable, Iterator, Sequence
 from typing import Any
 
 import anyio
@@ -41,6 +41,7 @@ from ag_ui.core import (
 )
 from ag_ui.core import Interrupt as CardInterrupt
 from ag_ui.encoder import EventEncoder
+from langchain_core.callbacks import BaseCallbackHandler
 from langgraph.store.base import BaseStore
 from langgraph.types import Command
 from psycopg import sql
@@ -62,6 +63,7 @@ from marvia.graph.resume import approval_reply, remask_reply
 from marvia.graph.state import merge_cargos, merge_evidence
 from marvia.graph.tools import SERVER_SURFACE
 from marvia.tools.rules import load_rules
+from marvia.trace import tracer_callbacks
 from marvia.view import interrupt_card, screen_view
 from marvia.watch import forget_user
 
@@ -253,10 +255,20 @@ async def _sse(
         stop.set()
 
 
-def build_app(graph, verify: Verify, *, web_origin: str, forget: Callable[[str], None]) -> Starlette:
-    """화면 서버 앱. graph는 컴파일한 메인 그래프, verify는 auth의 토큰 확인 함수, forget은 계정 삭제."""
+def build_app(
+    graph,
+    verify: Verify,
+    *,
+    web_origin: str,
+    forget: Callable[[str], None],
+    callbacks: Sequence[BaseCallbackHandler] = (),
+) -> Starlette:
+    """화면 서버 앱. graph는 컴파일한 메인 그래프, verify는 auth의 토큰 확인 함수, forget은 계정 삭제.
+
+    callbacks는 트레이서(trace.tracer_callbacks)다. 꺼져 있으면 빈 목록이다.
+    """
     # [왜] 이 앱이 부르는 그래프는 user_id 없이 사용자 데이터에 닿으면 멈춘다 (tools.user_of, R-048)
-    graph = graph.with_config(configurable={"surface": SERVER_SURFACE})
+    graph = graph.with_config(configurable={"surface": SERVER_SURFACE}, callbacks=list(callbacks))
     running: set[str] = set()
     guard = threading.Lock()
     cfg = load_rules("server")["request"]
@@ -380,6 +392,7 @@ def main() -> None:
             verify,
             web_origin=settings.web_origin,
             forget=lambda user: forget_account(watch_conn, store, user, url),
+            callbacks=tracer_callbacks(settings),
         )
         # [주의] 기본은 127.0.0.1이다. 컨테이너 안에서만 MARVIA_HOST=0.0.0.0을 주고
         #        compose가 바깥 쪽을 127.0.0.1로 연다
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `809 passed`, 오류 0. 명령 B. Expected: 위 C4 줄과 같다.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/server.py scripts/try_agent.py src/marvia/eval/run.py scripts/run_eval.py \
  tests/graph/test_server.py tests/graph/test_eval_run.py
git commit -m "feat(server): 서버·CLI·평가가 같은 트레이서 콜백을 씀"
```

### Task 5: 문서

**Files:**
- Modify: `docs/specs/2026-10-28-marvia-v2-design.md`, `docs/deploy.md`, 이 계획 문서(결과 표)

- [ ] **Step 1: 설계와 배포 문서**: 아래 diff대로 고친다. 커밋한 날이 11-08이 아니면 날짜만 바꾸고, 크기 줄의 바이트는 Task 1 Step 5에서 잰 값으로 바꾼다.

```diff
--- a/docs/deploy.md
+++ b/docs/deploy.md
@@ -11,7 +11,7 @@ API는 Cloud Run(서울, `asia-northeast3`), 화면은 Vercel, DB는 Supabase, 
 | 확인 | 명령 | 결과 |
 |---|---|---|
 | amd64 이미지 빌드 | `docker buildx build --platform linux/amd64 --target runtime --load .` | 성공, 71초 |
-| amd64 이미지 크기 | `docker image inspect` | 1.18GB (상한 1.2GB, 여유 작음) |
+| amd64 이미지 크기 | `docker image ls`의 DISK USAGE(받은 층과 푼 층의 합. `docker run`으로 한 번 띄워 층을 푼 뒤 읽는다) | 1.18GB (상한 1.2GB, 여유 작음). 11-08 계획 6b(langfuse 5.0.4) 뒤 1,198,942,988바이트, 남은 여유 약 1.06MB |
 | arm64 이미지 크기 | `docker images` | 1.07GB |
 | 실행 사용자 | `docker run --rm <이미지> id -u` | `10001` |
 | 형태소 분석기 메모리 (1GB) | `docker run --rm --platform linux/amd64 --memory 1g --memory-swap 1g <이미지> python -c "from marvia.rag.keywords import keywords; print(keywords('수입 신고 시 관세율은 어떻게 정해지나요?')[:5])"` | 종료 코드 0, `['수입', '신고', '관세', '어떻', '정하']` (Cloud Run 배포 명령의 `--memory 1Gi`가 이 값) |
--- a/docs/specs/2026-10-28-marvia-v2-design.md
+++ b/docs/specs/2026-10-28-marvia-v2-design.md
@@ -310,12 +310,12 @@ UNI-PASS 같은 외부 조회 호출은 타임아웃, 재시도 2회, 실패하
 - GitHub Actions (11-06 구현): 키 없이 린트·형식·타입·시험을 돌리고, 저장소에 커밋한 파생 값 줄을 지금 지표 코드로 다시 채점해 바닥값 아래면 실패시킨다. 바닥값은 코드가 기준 실행에서 만들고(`run_eval.py floors`), 저장한 결과가 평가셋 문항을 모두 덮어야 통과한다. 모델 응답은 저장소에 두지 않으므로 응답 재생은 하지 않는다.
 - 간접 주입 시험 (11-06 구현): promptfoo가 Docker 안에서 다섯 통로(검색 결과 본문, 저장된 품목 카드, 공식 페이지 제목, 서류 사진 글, 사용자 글)에 같은 주입 글을 넣고, 같은 사례를 pytest가 가짜 모델로 키 없이 돈다. 차례가 실제로 돌지 않은 경우는 통과로 치지 않는다. 실제 모델 5/5 통과, 주입을 따르는 가짜 모델 5/5 실패 [실측 11-06].
 - 측정 뒤 바뀐 것 (11-07, 계획 4b): 위 평가 수치는 각 줄에 적은 측정 커밋의 코드와 지시문으로 잰 값이다. 그 뒤 에이전트 지시문(`prompts/agent.md`)에 규칙 한 줄(`unwatch_cargo`, `cc1aa92`)이 더해졌고 도구가 하나 늘었다. 이 변경 뒤로 평가셋은 다시 돌리지 않았으므로 수치는 새 지시문에서 잰 값이 아니다.
-- Langfuse v4: 노드·도구·LLM 호출마다 트레이스(OTel), 프롬프트는 레포 파일이 원본이고 Langfuse에 같은 글을 등록한다, 평가 점수를 트레이스에 붙인다. 아직 하지 않았다(키). 트레이스 가림 문은 닫았다: 콜백 값을 걸어 다니며 번호 덩어리를 가리는 `trace.scrub`과, 감시 변화·Send 두 갈래·화물 조회·직접 입력·조사 서브에이전트·답을 지나는 기록 콜백 시험이 있다 (11-07 R-010·R-022·R-039). 단서 둘이 남는다: Langfuse는 `mask(data=...)`로 부르고 `status_message`는 가리지 않으며, 번호가 둘 이상 겹쳐 되묻는 끼어들기(`ask`)의 값에는 실제 번호가 들어 있다. 그래서 연결할 때 오류 길을 따로 가리고 내보낸 span 속성(`status_message` 포함)을 읽는 시험을 먼저 넣는다(done 3.9에 넘김). 그 전에는 LangSmith 추적 환경 변수가 켜져 있으면 서버가 뜨지 않는다 (R-069).
+- Langfuse (11-08 연결, 계획 6b): 노드·도구·LLM 호출마다 트레이스(OTel, SDK 5.0.4)를 남긴다. 기본은 꺼짐이고 `MARVIA_LANGFUSE_PUBLIC_KEY`·`MARVIA_LANGFUSE_SECRET_KEY`·`MARVIA_LANGFUSE_HOST`가 모두 있을 때만 켜진다(하나라도 비면 SDK를 불러오지도 않는다). 서버·CLI(`scripts/try_agent.py`)·평가(`scripts/run_eval.py`, 결과 meta의 `tracing`)가 같은 콜백(`trace.tracer_callbacks`)을 쓴다. 내보내는 값은 네 겹으로 가린다: Langfuse SDK가 만든 span만 내보내기(다른 라이브러리의 OTel span은 내보내지 않는다), `mask=scrub`(input·output·metadata), `mask_otel_spans`(그 밖의 span 속성, 끼어들기 질문이 드는 `status_message` 포함), 오류를 가린 사본으로 넘기는 콜백(span 상태 설명). 감시 변화·Send 갈래·식별 끼어들기·직접 입력·조사 서브에이전트·답·도구와 모델 오류를 지나는 한 시나리오에서 내보낸 span 전체에 번호가 0개이고, 네 겹을 모두 빼면 10개가 모두 남고, 한 겹씩 빼면 그 겹이 맡은 번호가 남는 문 시험이 있다. 실제 Langfuse 서버로는 아직 보내 보지 않았다(키). 가림 때문에 사용자·thread id(UUID 모양)로는 트레이스를 찾을 수 없다. LangSmith 추적 환경 변수(R-069)나 접두어 없는 `LANGFUSE_*` 환경 변수가 있으면 서버가 뜨지 않는다. 프롬프트 등록과 평가 점수 붙이기는 15절로 미뤘다.
 
 ## 12. 신뢰 경계
 
 - 도구 응답, AIS 목적지 문자열, 문서·메시지, 사용자 입력은 데이터다. 그 안의 문장을 지시로 따르지 않는다.
-- 실제 번호는 LLM과 트레이스에 넘기지 않는다(가린 토큰만).
+- 실제 번호는 LLM과 트레이스에 넘기지 않는다. LLM에는 가린 토큰만 가고, 트레이스에는 번호 덩어리를 `[가림]`으로 바꾼 값만 간다(11-08, 계획 6b의 네 겹).
 - 되돌리기 어렵거나 기억에 남는 일은 승인 뒤에만 한다.
 - 저장한 기억, 색인 밖 공식 페이지 글, 서류 사진에서 읽은 글도 데이터다. 모델에는 데이터 태그 안에서만 간다. 사진 글은 번호 덩어리만 남긴다 (11-06).
 - 바깥으로 나가는 호스트는 규칙의 허용 목록(`official.allowed_hosts`, 지금은 `www.law.go.kr`)뿐이고 넘겨 주는 주소는 따라가지 않는다.
@@ -353,7 +353,7 @@ UNI-PASS 같은 외부 조회 호출은 타임아웃, 재시도 2회, 실패하
 
 ## 15. 2차로 미룬 것
 
-선박명·항차 식별(해수부 키가 새로 필요하고 배와 MRN까지만 준다), 컨테이너 번호로 UNI-PASS에서 화물 찾기(그런 서비스를 공식 문서로 확인한 뒤. 아는 화물 안에서 찾기는 11-07에 1차로 당김), 항공·특송, RAG C층(웹 검색과 검토 뒤 코퍼스 추가. 공식 사이트의 법령 이름 조회 `official_lookup`만 11-06에 1차로 당김, 키워드 검색은 법제처 Open API 등록이 필요), 동남아 국가별 규정, 고시 개정 자동 수집과 영향 알림, 푸시·카카오 알림, 보관료 계산, 온라인 평가, Neo4j 한 곳 하이브리드 검색 비교 실험, 평가셋 50건 이상.
+선박명·항차 식별(해수부 키가 새로 필요하고 배와 MRN까지만 준다), 컨테이너 번호로 UNI-PASS에서 화물 찾기(그런 서비스를 공식 문서로 확인한 뒤. 아는 화물 안에서 찾기는 11-07에 1차로 당김), 항공·특송, RAG C층(웹 검색과 검토 뒤 코퍼스 추가. 공식 사이트의 법령 이름 조회 `official_lookup`만 11-06에 1차로 당김, 키워드 검색은 법제처 Open API 등록이 필요), 동남아 국가별 규정, 고시 개정 자동 수집과 영향 알림, 푸시·카카오 알림, 보관료 계산, 온라인 평가, Langfuse 프롬프트 등록과 평가 점수 붙이기(11-08, 트레이스만 1차), Neo4j 한 곳 하이브리드 검색 비교 실험, 평가셋 50건 이상.
 
 ## 16. 확인이 필요한 것
 
@@ -386,3 +386,4 @@ UNI-PASS 같은 외부 조회 호출은 타임아웃, 재시도 2회, 실패하
 - 11-07: 계획 3b 구현 반영. 별표 읽기, 그래프 확장 자리, GraphRAG 구현 범위, 실제 UNI-PASS 클라이언트, MCP 구현 (5.2, 5.4, 5.5, 7.2, 9). 측정 결과(11절)는 충전 뒤 더한다
 - 11-07: 계획 4b. 원문·답 저장 안 함(8절), 읽기 연결 풀·표 준비 명령·계정 삭제와 감시 끄기(6.3·8절), AG-UI 직접 엔드포인트와 Starlette, 로그인·입력 검사·인스턴스 하나(3절·10절·12절), 승인 편집의 번호 거절과 한국어 이름(10절), 트레이스 가림 문과 남은 단서(11절), 측정 뒤 지시문 변경(11절), 로컬 compose와 배포 워크플로(13절)
 - 11-07: 계획 6a. 컨테이너 번호 식별(확인 숫자, 토큰 `[CNTR1]`, 아는 화물에서 찾기, 오타 질문) (4.1, 4.2, 15절)
+- 11-08: 계획 6b. Langfuse 트레이스 연결(기본 꺼짐, 네 겹 가림, `LANGFUSE_*` 시작 거절) (11절, 12절, 15절)
```

- [ ] **Step 2: 이 문서 끝에 "실행 결과" 표**: 태스크마다 커밋, 시험 수, 확인점에서 자른 것, C1~C6 판정(통과·못 넘음과 근거)을 적는다.

- [ ] **Step 3: done 체크리스트 증거 줄(저장소 밖 진행 기록)**: 3.9의 `[parked]`를 "연결함, 기본 꺼짐, 키 없음"으로 바꾸고 커밋 범위와 C1~C6 판정을 적는다. 실제 Langfuse 서버로 보내 보는 일은 직접 할 일 2로 남긴다.

- [ ] **Step 4: 커밋**

```bash
git add docs/specs/2026-10-28-marvia-v2-design.md docs/deploy.md docs/plans/2026-11-07-marvia-v2-plan-6b-langfuse.md
git commit -m "docs: 설계에 계획 6b 반영(Langfuse 트레이스 연결, 네 겹 가림)"
```

---
## 끝나면 되는 것

- 키가 없으면 지금과 똑같다: 콜백 없음, `langfuse` import 없음, 스레드·소켓 0. 시험·평가·서버가 그대로 돈다.
- `MARVIA_LANGFUSE_PUBLIC_KEY`·`MARVIA_LANGFUSE_SECRET_KEY`·`MARVIA_LANGFUSE_HOST`를 모두 넣으면 서버·CLI·평가가 같은 콜백 하나로 노드·도구·LLM 호출을 Langfuse로 보낸다. 끼어들기와 재개는 한 트레이스로 이어진다.
- 내보내는 span의 어느 칸에도 화물 번호가 없다. 번호 덩어리는 `[가림]`이다. 네 겹 중 하나라도 빼면 문 시험이 실패한다.
- 접두어 없는 `LANGFUSE_*` 환경 변수가 있으면 서버가 뜨지 않는다.
- amd64 이미지가 1.2GB 상한 아래다. 시험 809개가 키 없이 돈다.

## 설계와 대조

| 설계 | 이 계획 | 차이 |
|---|---|---|
| 11절 "Langfuse v4: 노드·도구·LLM 호출마다 트레이스(OTel)" | SDK 5.0.4, LangChain 콜백, 기본 꺼짐 | T5에서 날짜와 함께 고친다 |
| 11절 "프롬프트는 Langfuse에 같은 글을 등록한다, 평가 점수를 트레이스에 붙인다" | 하지 않는다 | 15절로 옮긴다(T5) |
| 11절 단서 둘(`status_message`, `ask` 끼어들기의 실제 번호) | ②가 `status_message`를, ③이 상태 설명을 가린다. 식별 끼어들기를 문 시험에 넣었다 | 없음 |
| 12절 "실제 번호는 LLM과 트레이스에 넘기지 않는다(가린 토큰만)" | 트레이스에는 토큰이 아니라 `[가림]`이 간다(콜백에는 가림 표가 없다) | T5에서 문장을 고친다 |
| 12절 바깥으로 나가는 호스트 허용 목록 | Langfuse 주소는 설정(`MARVIA_LANGFUSE_HOST`)이고 허용 목록(`official.allowed_hosts`)과 따로다 | 없음 (켜는 사람이 주소를 정한다) |
| 13절 배포 | compose·Cloud Run 설정은 바꾸지 않는다 | 직접 할 일 3 |

## 직접 할 일

1. `.env` 맨 끝(`.env.example`과 같은 자리)에 아래 묶음을 붙이고, 켤 때만 값을 채운다. 비워 두면 꺼짐이다.

```
# 트레이스(Langfuse). 셋이 모두 있어야 켜진다. 비우면 꺼진다(기본). 보내는 값은 모두 화물 번호를 가린 값이다
# hajeongun.dev 계정의 Langfuse 프로젝트 설정에서 키를 만든다. 접두어 없는 LANGFUSE_* 이름은 쓰지 않는다(서버가 뜨지 않는다)
MARVIA_LANGFUSE_PUBLIC_KEY=
MARVIA_LANGFUSE_SECRET_KEY=
# Langfuse 주소. 예: https://cloud.langfuse.com (EU), https://us.cloud.langfuse.com (US), 직접 띄운 서버 주소
MARVIA_LANGFUSE_HOST=
```

2. 실제 Langfuse로 한 번 보내 본다(모델 호출 한두 차례 비용): hajeongun.dev 계정으로 Langfuse 프로젝트를 만들고 키 셋을 `.env`에 넣은 뒤 `uv run python scripts/try_agent.py "DEMO0001 MOCK12345678TEST87654321 언제까지 수입신고 해야 해요?"`를 돌린다(선택지에서 권장안). Langfuse 화면에서 (a) 트레이스 하나에 노드·도구·모델 span이 보이는지, (b) 식별 끼어들기와 재개가 한 트레이스인지, (c) `DEMO0001`·`MOCK12345678`로 검색해 0건인지, (d) input·output이 JSON으로 읽히고 번호 자리가 `[가림]`인지 본다. 끝나면 키를 다시 비운다.
3. 배포에서 켤 때: Secret Manager에 키 둘을 비밀로 만들고, 배포 명령의 환경 변수에 `MARVIA_LANGFUSE_HOST`, 비밀 목록에 두 키를 더하고, 실행 계정에 읽기 권한을 준다(`docs/deploy.md`의 UNI-PASS 키와 같은 절차). compose `api`에도 세 칸을 더한다.
4. Langfuse 프로젝트의 지역(EU·US)과 데이터 보존 기간을 정한다. 가린 값만 가지만 질문 글(번호를 뺀 나머지)은 그대로 간다.

## 확인하지 못한 것

- 실제 Langfuse 서버로의 내보내기(OTLP HTTP, 인증, 압축, 묶음 크기)와 화면에 `[가림]`이 어떻게 보이는지 [미확인, 키 없음]. 직접 할 일 2.
- 비동기 길(`ainvoke`·`astream`)의 콜백. 서버는 작업 스레드에서 동기 `graph.stream`을 돈다.
- 동시에 도는 여러 차례가 콜백 하나를 함께 쓸 때 span 부모가 섞이지 않는지 [추정: run_id별 표].
- 문 시험이 지나지 않는 길: 승인 카드 편집 재개, 긴 대화 요약 미들웨어, 계획자 루프(`MARVIA_LOOP=planner`), 실제 MCP 검색. 같은 콜백과 같은 네 겹을 지난다 [추정]. ⓪이 MCP span을 막는 것은 같은 꼴의 span(문 시험 (5))과 tests/rag 실행(기본 거름 13개, ⓪ 0개)으로 보았다. 실제 서버 차례의 MCP 검색 길로는 보지 않았다.
- 이미지 여유가 약 1.06MB다. 다음 의존성 하나로 상한을 넘는다.
- SDK가 자기 오류를 `langfuse_logger.exception`으로 로그에 남길 때의 글(Langfuse로는 가지 않고 서버 로그에 남는다). 이 길로 번호가 나가는지는 보지 않았다.
- 셋 중 일부만 넣은 설정은 아무 말 없이 꺼진다. 시작 거절이나 경고는 없다.
- Langfuse 무료 한도와 평가 트레이스의 양.

## 실행 결과 (11-08)

하루 안에 끝나 확인점에서 자른 것은 없다. 유료 모델 호출, Langfuse 서버, 키는 쓰지 않았다($0). 시험 수는 커밋마다 `uv run pytest -q`를 저장소에서 돌린 값이다 [실측 11-08, 건너뜀 0].

| 태스크 | 커밋 | 시험 |
|---|---|---|
| T0 사전 등록 | e6120aa | 794 |
| T1 네 겹으로 가린 핸들러, langfuse 5.0.4 | e33c587 | 800 |
| T1 고침: 트레이스 메타데이터(thread_id)도 ② 겹이 가림 | 8048a6f | 800 |
| T2 키 셋이 모두 있을 때만 켬 | ddce4a6 | 804 |
| T3 접두어 없는 `LANGFUSE_*`면 서버가 뜨지 않음 | 3c1d9e7 | 807 |
| T4 서버·CLI·평가가 같은 콜백 | 52963f2 | 809 |

| # | 판정 | 근거 |
|---|---|---|
| C1 | 통과 | 키 셋 중 하나라도 비면 `[]`, 새 프로세스에서 `langfuse` 미적재·스레드 증가 0·연결 0(일부만 있는 네 경우 포함), 셋 다 있으면 같은 콜백 하나. `LANGFUSE_` 이름 세 가지 거절, 값은 거절 글에 나오지 않음 |
| C2 | 통과(넓힌 시나리오 8048a6f) | 내보낸 span 전체(`to_json`과 계측 범위)에 번호 0개, 가리지 않은 실행에는 11개 모두. 원래 시나리오로는 e33c587에서도 통과(위 "C2·C3 시나리오 넓힘") |
| C3 | 통과 | 겹을 하나씩 빼면 그 겹이 맡은 번호가 남는다(⓪ DEMO0008, ① 입력·출력, ② 끼어들기 질문과 thread_id, ③ 상태 설명) |
| C4 | 통과 | 명령 B: `langfuse` import는 `src/marvia/langfuse_trace.py` 하나, `tracer_callbacks(` 호출은 서버·CLI·평가. 서버 한 차례, 선택지 재개, 승인 재개, 오류 길이 같은 콜백을 지난다. R-072 시험은 그대로 통과 |
| C5 | 통과 | amd64 runtime 이미지 1,198,946,428바이트(상한 1,200,000,000), 이미지 안 `import langfuse, marvia.langfuse_trace` 성공 [실측 11-08, T1 커밋 상태]. T2~T4는 의존성을 더하지 않았다 |
| C6 | 통과 | 794 → 809, 건너뜀 0, `set_v2` sha 시험 통과, 커밋당 코드 파일 최대 6개(52963f2) |

남은 한계:
- 실제 Langfuse 서버로 보내기와 화면 표시는 보지 않았다(키 없음, 직접 할 일).
- 문 시험은 OTel `to_json`을 읽는다. 실제로 보내는 OTLP 꼴은 보지 않았다.
- 시나리오 밖 길(긴 대화 요약, 계획자 루프, 실제 MCP 검색)은 같은 콜백을 지나지만 시험하지 않았다.
- 이미지 여유가 약 1.05MB라 다음 의존성 하나로 상한을 넘는다. 그때는 langfuse를 선택 extra로 옮기거나 상한을 바꾸는 결정을 따로 적는다.
