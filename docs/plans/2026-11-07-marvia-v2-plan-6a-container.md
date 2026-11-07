# Marvia v2 계획 6a: 컨테이너 번호 식별

> 진행 방법: 태스크를 T0부터 차례로 하고, 단계마다 체크박스(`- [ ]`)로 표시한다. 커밋 하나는 동작 하나다. 컨테이너 번호가 B/L로 UNI-PASS에 가는 길은 첫 구현 커밋에서 막는다.

**Goal:** 컨테이너 번호(ISO 6346)를 확인 숫자로 가려 자기 종류(`container`)와 토큰(`[CNTR1]`)으로 다룬다. UNI-PASS에는 보내지 않고, 이미 아는 화물(이 대화에서 조회한 화물, 감시 목록)의 컨테이너 번호와 맞춰 찾는다. 하나면 그 화물로 답하고, 여럿이면 선택지로 묻고, 없으면 B/L·화물관리번호를 묻는 정한 글을 낸다. 확인 숫자가 틀린 컨테이너 모양 번호는 조회 전에 한 번 묻는다 (done 6.1의 컨테이너 부분, 설계 4.1 ②).

**Architecture:** 번호 읽기(`identify/parse.py`)가 컨테이너를 자기 종류로 돌려주고, 가림(`identify/mask.py`)이 `[CNTR]` 이름표를 붙인다. 컨테이너를 화물로 바꾸는 일은 조회 서브그래프의 `collect` 한 곳에서 한다. 이 서브그래프를 식별(계획자·에이전트 두 루프 공통), 선택지 뒤 `lookup`, 에이전트 도구 `lookup_cargo` 세 길이 함께 쓰므로 세 길의 동작이 같다. 화물 하나를 찾으면 그 사실을 컨테이너 토큰에 달고, 여럿이면 식별 서브그래프의 `choose`가 선택지를 만든다.

```
글 ── parse.find_spans(붙여 쓴·하이픈·띄어 쓴 꼴) → read_token → kind_of: cargo_no | container(확인 숫자 맞음) | bl
   ── mask: [CNTR1] (READ_LABELS 밖: 감시 목록에 넣지 않음) ── view.KIND_NAMES: "컨테이너 번호"
식별 서브그래프: read(확인 숫자가 틀린 컨테이너 모양 → 정한 질문) → lookup → choose(후보 여럿 → 선택지) → END
조회 서브그래프: assign → Send("one")는 컨테이너가 아닌 번호만 → collect:
   컨테이너 = container_identity(known_cargo(이번 갈래 결과 + 이 대화의 cargos + 감시 목록 다시 조회))
unipass.lookup_cargo: 컨테이너 번호면 어느 모드에서도 HTTP 없이 ToolError(container_unknown)
```

**Tech Stack:** 새 의존성 없음. Python 3.12, LangGraph 1.2.18. 노드 함수가 `config: RunnableConfig`를 받는 방식은 지금 `graph/main.py`의 `news` 노드와 같고, 도구 안에서 부른 조회 서브그래프도 부모 실행 설정(`configurable.user_id`)을 받는다 [실측 11-07: Task 4a의 도구 길 시험이 user_id `u1`의 감시 번호로 찾았다].

**Spec:** `docs/specs/2026-10-28-marvia-v2-design.md` (4.1 단서 등급, 4.2 번호 읽기, 4.3 `CargoIdentity.candidates`, 6.3 선택지, 7.2 UNI-PASS 조회, 8 감시 표, 10 "이렇게 읽었어요", 12 신뢰 경계, 15 2차로 미룬 것). 범위 조사(11-07)의 사실과 결정을 따른다. 따르지 않은 곳은 "결정과 근거"에 이유를 적었다.

## 계획 나눔

| 계획 | 범위 | 상태 |
|---|---|---|
| 3a~4b | 답, 도구 루프, 기억·조사·감시, 평가, GraphRAG·MCP, 화면·배포 준비 | 완료 (11-02~11-07) |
| **6a (이 문서)** | 컨테이너 번호 식별 (done 6.1의 컨테이너 부분) | 11-07 시작, 11-09 끝 |
| 6.1의 나머지 | 선박명·항차 식별 | 2차 (설계 15절, 아래 결정) |

## 결정과 근거 (11-07)

| 결정 | 이유 | 틀렸을 때 비용 |
|---|---|---|
| 컨테이너 번호는 ISO 6346 모양(영문 3 + U·J·Z + 숫자 7)에 확인 숫자가 맞을 때만 자기 종류 `container`, 토큰 `[CNTR1]`이다 | 지금은 `DEMU1234560`이 `[BL1]`로 가려져 B/L로 조회되고 "없음"을 받는다 [실측 11-07]. 확인 숫자는 모양만 같은 무작위 11자의 약 9/10을 거른다 [추정]. 이름표 `CNTR`은 v1과 같다 | 확인 숫자까지 맞는 11자 B/L은 컨테이너로 읽혀 조회되지 않는다(다음 줄) |
| 컨테이너 번호는 어느 모드에서도 UNI-PASS에 보내지 않는다. `unipass.lookup_cargo` 첫 줄에서 HTTP 없이 정한 글(`container_unknown`)을 돌려준다 | 화물통관진행정보는 화물관리번호·마스터 B/L·하우스 B/L로만 찾는다 [문서 11-07 data.go.kr 15126268]. 컨테이너 번호로 화물을 찾는 서비스는 공식 문서로 확인하지 못했다. 제3자 README는 컨테이너내역(API020)이 화물관리번호로 컨테이너를 찾는 방향이라 적었다 [문서 11-07, 공식 아님]. 감시 재조회(`recheck`)도 이 함수를 지나므로 함께 막힌다 | 연계가이드에 컨테이너로 찾는 서비스가 있으면 실제 경로가 빠진다(직접 할 일 1). 확인 숫자까지 맞는 11자 B/L은 "B/L을 알려 주세요"를 받는다 [추정: 드묾] |
| 아는 화물 = 이 대화에서 조회한 화물 사실(`cargos`)과 그 사용자의 감시 목록(번호를 다시 조회해 사실을 얻는다). 하나면 그 화물, 여럿이면 선택지, 없으면 정한 글 | UNI-PASS로 찾을 수 없으니 이미 아는 화물에서만 찾는다. v1도 로그인 사용자의 화물 표에서 찾았다 | 재생 모드에서는 컨테이너 질문 한 번에 감시 화물 수만큼 차례로 다시 조회한다 [추정: 감시 목록은 짧다]. 상한은 두지 않았다. 실제 모드는 아래 11-07 정정 줄 |
| 11-07 정정(첫 구현 커밋 전): 실제 모드(`MARVIA_UNIPASS_MODE=live`)에서는 컨테이너를 찾을 때 감시 목록을 읽지 않고 다시 조회하지 않는다. `unipass.facts_carry_containers()`가 재생 모드일 때만 참이다 | 실제 응답(`parse_progress`)은 `containers`를 채우지 않으므로(아래 줄) 실제 모드에서 감시 화물을 다시 조회해도 맞출 수 없다. 상한 없는 재조회와 겹치면 컨테이너 질문 하나가 감시 화물 수만큼 실제 UNI-PASS를 부르고도 늘 `container_unknown`으로 끝난다. 컨테이너 맞추기는 실제 응답 칸을 확인하기 전까지 재생 데이터에서만 된다 | 연계가이드에서 `cntrNo`를 확인하면 이 함수와 `parse_progress`를 함께 바꿔야 한다(직접 할 일 1) |
| 찾는 곳은 조회 서브그래프의 `collect`(갈래 조회가 끝난 뒤)다. 갈래(`Send`)에는 컨테이너 번호를 보내지 않는다 | 이 서브그래프를 식별(두 루프 공통), 선택지 뒤 `lookup`, 에이전트 도구 `lookup_cargo` 세 길이 함께 쓴다. 갈래가 끝난 뒤라 같은 글에 함께 적은 B/L의 사실도 쓴다 | 없음 |
| 하나를 찾으면 화물 줄의 토큰은 컨테이너 토큰이고(`[CNTR1]: 반입신고 (부산) 2026-10-27`) 사실은 그 화물의 것이다 | 사용자가 준 단서로 답한다. 화면 화물 카드도 컨테이너 번호로 보인다. `calc_deadlines`는 사실만 본다 | 그 화물을 감시하려면 B/L·화물관리번호 토큰이 있어야 한다(`watch_cargo`는 `[CNTR]`을 받지 않는다) |
| 여럿이면 식별 길은 선택지(권장안 "n건 모두 조회", 그다음 한 건씩), 도구 길은 정한 글(`container_many`)이다. 선택지 글에는 토큰만 쓴다 | 하나를 짐작하면 다른 화물의 단계를 말한다. 권장안이 "모두"라 답이 없어도 짐작하지 않는다. 화면에는 `view.interrupt_card`가 실제 번호로 되돌려 보인다 | 후보가 많으면 카드가 길어진다 |
| 확인 숫자가 틀린 컨테이너 모양은 전처럼 B/L로 읽되, 조회 전에 정한 질문을 한다(권장안 "B/L 번호로 조회", 다음 "조회하지 않음", 기타 칸에 고친 번호) | 오타를 화물로 지어내지 않고 잡는다. 같은 모양의 실제 B/L은 한 번 더 묻고 전처럼 조회된다 | 그런 B/L에 질문이 한 번 는다 |
| "영문 4 + 숫자 7"은 넷째 글자가 U·J·Z일 때만 컨테이너 모양으로 본다 | 넷째 글자가 다르면 컨테이너일 수 없다. `MOCK1234567` 같은 B/L에 질문을 늘리지 않는다 | 넷째 글자를 잘못 쓴 컨테이너는 오타 질문 없이 B/L로 조회된다 |
| 띄어 쓴 컨테이너 번호(`DEMU 123456 0`)도 확인 숫자가 맞으면 한 덩어리로 읽고 가린다 | 서류와 컨테이너 문에 이렇게 적는다. 조각이 8자보다 짧아 지금은 가리지 않은 채 LLM과 트레이스에 간다 [실측 11-07]. 확인 숫자로 걸러 "영문 4자 숫자 7자리" 같은 다른 글은 잡지 않는다 | 확인 숫자가 틀린 띄어 쓴 꼴은 여전히 가리지 않는다 |
| ISO 6346 글자 값과 계산은 `parse.py` 코드에 둔다. 규칙 파일에는 정한 글 두 줄만 더한다 | 표준이 정한 계산이고 바꿀 값이 아니다. `parse.py`의 화물관리번호 모양, B/L 길이와 같은 자리다 | 없음 |
| 감시 목록 읽기는 `WatchDeps.numbers`(없으면 감시 목록을 보지 않는다)와 `graph/tools.watched(watch)`로 넘긴다 | `user_of`가 `graph/tools.py`에 있어 `graph/identify.py`가 가져오면 import가 돈다. 서버 길에서 user_id가 없으면 `MissingUser`로 멈추고(R-048), 감시 DB 오류면 빈 목록으로 이 대화의 화물에서만 찾는다(`news` 노드와 같다) | 없음 |
| 실제 응답(`parse_progress`)에서는 `containers`를 채우지 않는다 | v1 코드 주석은 연계가이드 v4.1의 API001에 `cntrNo`가 있다고 적었지만, 실제 응답 필드 구성을 따른 가공 응답(`tests/tools/fixtures/unipass/progress_ok.xml`)에는 그 칸이 없다. 확인 전에는 읽지 않는다 | 실제 모드에서는 컨테이너 질문이 늘 정한 글이다(직접 할 일 1) |
| 재생 fixture의 컨테이너 번호는 소유자 부호 `DEM`·`TES`·`NOP` + `U`의 가공값이고 확인 숫자를 맞춘다. 한 컨테이너에 화물 둘(`TESU0000013` → DEMO0002·DEMO0003)을 둔다 | 넷째 글자가 U·J·Z여야 해서 `DEMO` 꼴을 쓸 수 없다. 혼재(LCL) 컨테이너처럼 화물이 여럿인 경우를 시험한다 | 없음 |
| 평가셋은 바꾸지 않는다. 새 동작은 가짜 모델 시험으로만 본다 | `set_v2`는 sha256으로 동결했고 유료 실행을 할 수 없다. 새 문항은 새 동결 판과 유료 실행을 함께 할 때 넣는다 | 평가 숫자에 컨테이너가 보이지 않는다 |
| 선박명·항차는 이 계획 밖이다 | 배와 MRN까지만 주고 19자리 화물관리번호는 주지 않으며, 해수부 키가 새로 필요하다 [문서 11-07 v1 `backend/app/clients/mof.py`]. 설계 15절에 둔다 | 없음 |
| Playwright 흐름을 더하지 않는다 | 화면 코드(`web/`)가 바뀌지 않는다. 종류 이름은 서버가 보내고 `Panels.tsx`가 받은 글을 그대로 그리며, 선택지 카드도 지금 모양이다. 서버 허용 목록 시험이 이름을 본다. e2e를 돌려도 새로 지나는 화면 길이 없다 | 화면에 "컨테이너 번호"가 실제로 보이는지는 눈으로 보지 않았다 |

## Global Constraints

- 숫자·등급·기한은 코드(`src/marvia/tools`)가 계산한다. LLM이 낸 값은 쓰지 않는다. 확인 숫자도 코드가 센다.
- 실제 화물 번호와 컨테이너 번호는 LLM과 트레이스에 가지 않는다. 모델에게는 `[CNTR1]` 같은 토큰만 가고, 선택지 글에도 토큰만 쓴다(화면에 보낼 때 `view.py`가 되돌린다).
- 도구 응답, 사용자 글, 화면이 보낸 값은 데이터다. 그 안의 문장을 지시로 따르지 않는다.
- 시험은 키 없이 가짜 모델로 돈다. DB 시험은 실행마다 새 `marvia_test_*` 스키마에서, Neo4j 시험은 `MARVIA_NEO4J_TEST_URL`(시험용 Neo4j)에서만 돈다. 실제 UNI-PASS는 부르지 않는다(시험은 재생 모드로 고정된다).
- fixture 화물 번호는 DEMO·MOCK·TEST·NOPE 접두어, 컨테이너 번호는 소유자 부호 DEM·TES·NOP + U의 가공값이다. 표준 설명의 예시 번호 `CSQU3054383`은 확인 숫자 시험에만 쓴다.
- 환경 변수는 `MARVIA_` 접두어만. 루트 `.env`의 `DATABASE_URL`은 읽지 않는다. `.env` 값은 읽거나 찍지 않는다.
- 임계값·목록·정한 글은 `rules/*.yaml`에 둔다: 이 계획은 `rules/unipass.yaml messages`에 `container_unknown`·`container_many`를 더한다.
- 파일 안에서 em dash(U+2014)를 쓰지 않는다.
- 평가셋(`eval/set_v2.yaml`)과 화면 코드(`web/`)는 바꾸지 않는다. 그래서 계획 4b의 명령 B는 이 계획에 없다.
- 커밋 하나는 동작 하나, 코드 파일 15개 이하(잠금 파일·`docs/`·`graphify-out/`은 세지 않음). 커밋은 `v2`에만, `main`에는 올리지 않는다.
- 커밋마다 명령 A가 통과한다. 출력을 `tail`에 넘기므로 `set -o pipefail`로 종료 코드를 본다. 코드를 바꾼 커밋 뒤에는 `graphify update .`(커밋에 넣지 않는다).

명령 A (파이썬 검사, 저장소 뿌리에서):

```bash
set -o pipefail
uv run pytest -q 2>&1 | tail -2 && uv run ruff check . && uv run ruff format --check . && uv run pyright | tail -1
```

- 코드 블록 검증: v2 HEAD(`9d547f6`)를 내보낸 깨끗한 사본에 이 문서의 diff를 커밋 순서대로 넣고, 커밋마다 Docker(`ghcr.io/astral-sh/uv@sha256:e5b65587…`, compose의 Postgres, 시험용 Neo4j)에서 `MARVIA_REQUIRE_DB=1`, `MARVIA_REQUIRE_NEO4J=1`로 시험 전체를 돌렸다: 749 → 776 통과(건너뜀 0). 11-07 정정(C10)의 시험과 코드 몇 줄은 이 검증 뒤에 더해서 사본에서 돌리지 않았다. 구현 커밋 4a의 확인에서 처음 돈다, 마지막 상태의 `ruff check`·`ruff format --check`·`pyright` 오류 0 [실측 11-07]. 줄 길이만 고친 커밋 상태는 ruff만 다시 돌렸다. 각 커밋의 "먼저 실패" 시험은 그 커밋의 코드를 빼고 돌려 아래 Expected FAIL 줄을 얻었다. 아래 Expected의 수는 749에서 커밋마다 더한 시험 수다.

---
## 사전 등록: 검사 C1~C9 (구현 전에 고정)

이 절은 첫 구현 커밋 전에 이 문서와 함께 커밋하고, 결과를 본 뒤 기준을 고치지 않는다. 고칠 일이 생기면 이유와 시각을 따로 적고 원래 기준의 판정도 함께 적는다.

| # | 검사 | 통과 기준 | 시험·명령 | 지금 HEAD |
|---|---|---|---|---|
| C1 | 확인 숫자 | `check_digit("CSQU305438") == 3`(표준 설명의 예시), 가공 번호 `DEMU1234560`·`DEMU2345676`·`TESU0000013`·`NOPU1234560`은 컨테이너이고 `DEMU1234565`(숫자 틀림)·`DEMO1234560`(넷째 글자)은 아니다. 재생 fixture의 컨테이너 번호가 모두 확인 숫자를 넘는다 | `tests/identify/test_parse.py::test_container_check_digit_follows_iso_6346`, `tests/tools/test_unipass_replay.py::test_replay_facts_carry_valid_container_numbers` | 함수 없음 [실측 11-07: `ImportError`] |
| C2 | 자기 종류·토큰·화면 이름 | `컨테이너 DEMU1234560 어디쯤이에요` → `[CNTR1]`(종류 container). `DEMU1234560DEMU2345676` → 컨테이너 둘. `DEMU 123456 0`·`DEMU 123456-0` → 한 덩어리. `ABCU 1234567`(확인 숫자 틀림) → 덩어리 없음(전과 같다). 평가 B01 꼴 `MOCK12345678TEST87654321`은 전처럼 선택지. "이렇게 읽었어요"의 종류는 "컨테이너 번호". 토큰 정규식이 모든 이름표를 받는다 | `tests/identify/test_parse.py`, `tests/identify/test_mask.py`, `tests/graph/test_server.py::test_the_reading_list_names_a_container_number`, `tests/graph/test_identify.py::test_ambiguous_returns_question_and_stops` | `[BL1]`(B/L)로 가림, 띄어 쓴 꼴은 그대로 남음, 화면 이름표 표에서 `KeyError: 'CNTR'` [실측 11-07] |
| C3 | UNI-PASS에 보내지 않음 | 실제 모드에 키가 있어도 `lookup_cargo("DEMU1234560")`이 HTTP 클라이언트를 만들지 않고 `container_unknown`. 식별·조회 서브그래프가 조회 함수에 넘긴 번호에 컨테이너 번호 0개(같은 글의 B/L과 감시 목록 번호만). `watch_cargo`가 `[CNTR1]`을 감시 목록에 넣지 않는다 | `tests/tools/test_unipass.py::test_a_container_number_is_never_sent_to_unipass`, `tests/graph/test_identify.py`의 `spy` 시험 다섯, `tests/graph/test_agent.py::test_watch_cargo_refuses_a_container_token` | `Failed: 컨테이너 번호로 HTTP를 열었다`, 감시 도구는 `[CNTR1]: 모르는 토큰이에요` [실측 11-07] |
| C4 | 가림 | 붙여 쓴·하이픈·띄어 쓴 컨테이너 번호가 `trace.scrub`에서 `[가림]`. 도구 길 시험에서 모델이 받은 모든 입력에 `DEMU1234560`·`DEMO0001`이 0개 | `tests/graph/test_trace.py`의 컨테이너 시험 둘, `tests/graph/test_agent.py::test_lookup_cargo_tool_matches_a_container_token_without_showing_numbers` | 붙여 쓴 꼴은 이미 가린다(확인 시험이 HEAD에서 통과), 띄어 쓴 꼴은 그대로 [실측 11-07] |
| C5 | 하나·여럿·없음 | 지난 차례에 조회한 DEMO0001 → `DEMU1234560`이 `[CNTR1]` confirmed에 반입신고. 같은 글에 함께 적은 DEMO0001로도 찾는다. 감시 목록 DEMO0002·DEMO0003 → `TESU0000013`은 후보 둘(`container_many`)이고 식별은 선택지(권장안 "모두 조회", 질문·선택지 칸에 실제 번호 0개). 어디에도 없는 `NOPU1234560` → `rules/unipass.yaml`의 `container_unknown` 글, 조회 0번. 하나면 묻지 않는다 | `tests/graph/test_identify.py`의 컨테이너 시험 여섯 | B/L로 조회해 not_found [실측 11-07, 범위 조사] |
| C6 | 두 길이 같다 | 계획자·에이전트 길이 같은 deps로 같은 화물 줄(`DEMU1234560: 반입신고 (부산) 2026-10-27`)과 같은 선택지 카드(`[BL1] + [BL2]`, `[BL1]`, `[BL2]`)를 내고, 고른 화물만 답에 나온다. 감시 목록은 그 user_id로만 읽는다 | `tests/graph/test_agent.py`의 두 길 시험(루프 매개변수 둘씩) | `WatchDeps`에 `numbers`가 없다(`TypeError`) [실측 11-07] |
| C7 | 도구 길 | `ask_user` 직접 입력으로 들어온 `[CNTR1]`을 `lookup_cargo` 도구가 user `u1`의 감시 목록에서 찾아 `[CNTR1]: 반입신고 (부산) 2026-10-27` 한 줄을 돌려준다 | `tests/graph/test_agent.py::test_lookup_cargo_tool_matches_a_container_token_without_showing_numbers` | 컨테이너를 B/L로 조회한다 [실측 11-07, 범위 조사] |
| C8 | 오타 질문 | `DEMU1234565` → 조회 0번에 정한 질문(`[BL1]은 컨테이너 번호 모양인데 확인 숫자가 맞지 않아요.`로 시작). 선택 0 → B/L로 조회(재생 not_found), 선택 1 → 조회 없음, 직접 적은 `DEMU1234560` → 컨테이너 길 | `tests/graph/test_identify.py::test_a_container_shaped_number_with_a_wrong_check_digit_is_asked_before_any_lookup`, `tests/graph/test_main.py::test_a_mistyped_container_is_asked_then_read_as_the_user_says` | 묻지 않고 B/L로 조회 [실측 11-07: `KeyError: '__interrupt__'`] |
| C9 | 회귀·크기 | 시험 수가 749에서 줄지 않고(마지막 776), 건너뜀 0. `set_v2` sha 시험 통과(평가셋 그대로). 커밋마다 코드 파일 15개 이하 | 명령 A, `git show --stat` | 749 통과 [실측 11-07] |
| C10 (11-07 추가, 첫 구현 커밋 전) | 실제 모드의 컨테이너 | `MARVIA_UNIPASS_MODE=live`에서 감시 목록(DEMO0002·DEMO0003)이 있어도 `TESU0000013` 질문이 감시 목록을 읽지 않고(읽기 0번) 조회 0번에 `container_unknown`. C1~C9는 그대로 두고 더한 검사이며, 이 시험으로 마지막 시험 수는 777이다 | `tests/graph/test_identify.py::test_live_mode_reads_no_watch_list_for_a_container` | 컨테이너를 B/L로 실제 조회한다 [범위 조사 11-07] |

## 비용

이 계획에는 유료 모델 호출과 실제 UNI-PASS 호출이 없다($0). 시험은 가짜 모델과 재생 데이터로 돈다.

## 시간 상한, 확인점, 자를 순서

남은 날은 11-07~11-09다(약 1.5일). 11-09 저녁까지 끝나지 않으면 자를 순서대로 자르고 끝낸다.

| 태스크 | 닫는 것 | 어림 | 날짜 | 끝났다는 증거 |
|---|---|---|---|---|
| T0 사전 등록 | C1~C9 고정 | 0.2시간 | 11-07 | 이 문서 커밋 |
| T1a 종류·토큰·보내지 않기 | C1·C2·C3 일부 | 2시간 | 11-08 | 757 통과 |
| T1b 띄어 쓴 꼴 | C2·C4 일부 | 0.5시간 | 11-08 | 760 통과 |
| T2 재생 fixture | C1 일부 | 0.5시간 | 11-08 | 761 통과 |
| T3 감시 목록 읽기 | C6 바탕 | 0.5시간 | 11-08 | 762 통과 |
| **CP1 (11-08 낮 2시)** | T1~T3 끝났나. 아니면 자를 순서 1을 바로 자른다 | | | |
| T4a 아는 화물에서 찾기 | C3·C5·C6·C7 | 3시간 | 11-08 | 770 통과 (C10 포함) |
| T4b 여럿이면 선택지 | C5·C6 | 1시간 | 11-09 | 774 통과 |
| **CP2 (11-09 낮 12시)** | T4 끝났나. 아니면 자를 순서 2·3을 자른다 | | | |
| T5 오타 질문 | C8 | 1시간 | 11-09 | 777 통과 |
| T6 문서 | 설계 4.1·4.2·15절 | 0.5시간 | 11-09 | |
| 합 | | 약 9시간 | | |

자르는 순서 (먼저 자르는 것부터):
1. 띄어 쓴 컨테이너 번호(T1b) → 붙여 쓴·하이픈 꼴만. 띄어 쓴 꼴이 가려지지 않는 틈은 "확인하지 못한 것"에 남긴다
2. 오타 질문(T5) → 확인 숫자가 틀리면 전처럼 바로 B/L로 조회
3. 여럿이면 선택지(T4b) → 정한 글(`container_many`)로 B/L·화물관리번호를 묻는다(4a에 이미 있다)
4. 감시 목록에서 찾기(T3, 4a의 `watched`) → 이 대화의 화물에서만 찾기

자르지 않는 것: 컨테이너의 자기 종류와 토큰, 화면 이름, UNI-PASS에 보내지 않는 첫 줄, 없을 때의 정한 글, 두 루프가 같은 식별, 각 태스크의 시험.

## 파일 구조

| 파일 | 책임 | 태스크 |
|---|---|---|
| `src/marvia/identify/parse.py` | 확인 숫자, `container` 종류, 띄어 쓴 꼴, 오타 모양 | T1a, T1b, T5 |
| `src/marvia/identify/mask.py`, `src/marvia/view.py` | `[CNTR]` 토큰, 감시 이름표에서 뺌, 화면 이름 | T1a |
| `src/marvia/identify/models.py` | 종류 주석, `CargoFacts.containers`, 후보 주석 | T1a, T2, T4b |
| `src/marvia/tools/unipass.py`, `rules/unipass.yaml` | 컨테이너는 보내지 않음, 정한 글 둘 | T1a, T4a |
| `fixtures/unipass/DEMO000{1,2,3}.json` | 가공 컨테이너 번호 | T2 |
| `src/marvia/watch.py` | `list_watched`, `WatchDeps.numbers` | T3 |
| `src/marvia/graph/identify.py` | `known_cargo`, `container_identity`, `collect`, `choose`, 오타 질문 | T4a, T4b, T5 |
| `src/marvia/graph/tools.py`, `src/marvia/graph/main.py` | 주석, `watched`, 세 길 연결, 도구가 이 대화의 화물을 넘김 | T1a, T4a |
| `docs/specs/2026-10-28-marvia-v2-design.md` | 4.1, 4.2, 15절, 변경 기록 | T6 |
| `tests/identify/test_parse.py`, `test_mask.py`, `tests/tools/test_unipass.py`, `test_unipass_replay.py`, `tests/test_watch.py`, `tests/graph/test_identify.py`, `test_agent.py`, `test_main.py`, `test_server.py`, `test_trace.py` | 시험 | 모두 |

---
### Task 0: 사전 등록

- [ ] **Step 1: 이 문서를 첫 구현 커밋 전에 커밋한다.** 결과를 본 뒤 C1~C9의 기준을 고치지 않는다.

```bash
git add docs/plans/2026-11-07-marvia-v2-plan-6a-container.md
git commit -m "docs: 계획 6a 컨테이너 번호 식별과 사전 등록 검사 C1~C9"
```

### Task 1: 컨테이너 번호를 자기 종류로 읽기 (C1~C4)

**배울 것:** ISO 6346 컨테이너 번호는 소유자 부호(영문 3) + 장비 구분(U 화물 컨테이너, J 떼어 내는 부속 장비, Z 트레일러·섀시) + 일련번호(숫자 6) + 확인 숫자(1)다. 확인 숫자는 앞 10자의 값(숫자는 그대로, 글자는 A=10부터 차례로 매기되 11의 배수를 건너뛴 값)에 자리마다 1, 2, 4, ... 512를 곱해 더한 합을 11로 나눈 나머지이고, 10이면 0이다. 표준 설명의 예시 `CSQU3054383`은 합 6185, 나머지 3이다 [문서 11-07 python-stdnum `iso6346`, 같은 값을 계산으로 확인]. 토큰 이름표가 늘면 세 곳이 따라가야 한다: 토큰 정규식(`graph/tools.py`의 `TOKEN`, `LABELS`에서 만든다), 감시할 수 있는 이름표(`READ_LABELS`), 화면 이름(`view.KIND_NAMES`, 없으면 `screen_view`가 `KeyError`로 화면 보기 전체를 깬다).

#### 커밋 1a: feat(identify): 컨테이너 번호를 확인 숫자로 읽어 [CNTR] 토큰으로 가림

**Files:**
- Modify: `src/marvia/identify/parse.py`, `src/marvia/identify/mask.py`, `src/marvia/identify/models.py`(주석), `src/marvia/view.py`, `src/marvia/tools/unipass.py`, `src/marvia/graph/tools.py`(주석), `rules/unipass.yaml`
- Test: `tests/identify/test_parse.py`, `tests/identify/test_mask.py`, `tests/tools/test_unipass.py`, `tests/graph/test_trace.py`, `tests/graph/test_server.py`, `tests/graph/test_agent.py`

**Interfaces:**
- Produces: `parse.check_digit(code: str) -> int`, `parse.is_container(value: str) -> bool`, `Kind`에 `"container"`, `kind_of`가 확인 숫자가 맞는 컨테이너에 `"container"`, `mask._LABEL["container"] == "CNTR"`, `READ_LABELS == ("BL", "CARGO")`, `view.KIND_NAMES["CNTR"] == "컨테이너 번호"`, `unipass.lookup_cargo(컨테이너) -> ToolError(code="container_unknown")`(HTTP 없음), `rules/unipass.yaml messages.container_unknown`

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/identify/test_parse.py
+++ b/tests/identify/test_parse.py
@@ -1,4 +1,4 @@
-from marvia.identify.parse import read_numbers, read_token
+from marvia.identify.parse import check_digit, is_container, read_numbers, read_token
 
 
 def values(text: str) -> list[list[str]]:
@@ -36,3 +36,27 @@
 
 def test_date_is_not_a_number():
     assert values("입항 20261028 예정") == []
+
+
+def test_container_check_digit_follows_iso_6346():
+    # [왜] 표준 설명에 실린 예시 번호(CSQU3054383)로 남이 계산한 값과 맞춰 본다. 나머지는 가공 번호다
+    assert check_digit("CSQU305438") == 3
+    assert check_digit("DEMU123456") == 0  # 합 5532를 11로 나눈 나머지가 10이면 0
+    for good in ("CSQU3054383", "DEMU1234560", "DEMU2345676", "TESU0000013", "NOPU1234560"):
+        assert is_container(good), good
+    assert not is_container("DEMU1234565")  # 확인 숫자가 틀렸다
+    assert not is_container("DEMO1234560")  # 넷째 글자가 U·J·Z가 아니다
+
+
+def test_container_is_its_own_kind_and_a_wrong_check_digit_reads_as_before():
+    assert [(n.value, n.kind) for n in read_token("demu-123456-0").numbers] == [("DEMU1234560", "container")]
+    # [왜] 확인 숫자가 틀리면 전처럼 B/L로 읽는다. 오타인지는 식별 단계가 묻는다 (계획 6a)
+    assert [(n.value, n.kind) for n in read_token("DEMU1234565").numbers] == [("DEMU1234565", "bl")]
+
+
+def test_two_containers_of_one_owner_glued_together_split():
+    r = read_token("DEMU1234560DEMU2345676")
+    assert [(n.value, n.kind) for n in r.numbers] == [
+        ("DEMU1234560", "container"),
+        ("DEMU2345676", "container"),
+    ]
```
```diff
--- a/tests/identify/test_mask.py
+++ b/tests/identify/test_mask.py
@@ -1,4 +1,4 @@
-from marvia.identify.mask import mask_text, token_for, unmask
+from marvia.identify.mask import LABELS, READ_LABELS, mask_text, token_for, unmask
 
 
 def test_split_numbers_get_two_tokens():
@@ -43,3 +43,10 @@
 
     for kind in _LABEL:
         assert TOKEN.fullmatch(token_for({}, "X", kind))
+
+
+def test_a_container_gets_its_own_token_and_is_not_a_lookup_label():
+    masked, mask_map = mask_text("컨테이너 DEMU1234560 어디쯤이에요")
+    assert (masked, mask_map) == ("컨테이너 [CNTR1] 어디쯤이에요", {"[CNTR1]": "DEMU1234560"})
+    # [왜] READ_LABELS는 UNI-PASS로 바로 조회할 수 있는 번호의 이름표다. 감시 목록이 이것으로 거른다
+    assert "CNTR" in LABELS and "CNTR" not in READ_LABELS
```
```diff
--- a/tests/tools/test_unipass.py
+++ b/tests/tools/test_unipass.py
@@ -145,3 +145,16 @@
     raised, _ = _fetch(httpx.DecodingError(f"https://x/?crkyCn={KEY}&cargMtNo={CARGO_NO}"))
     assert isinstance(raised, ToolError) and raised.code == "bad_response"
     assert KEY not in repr(raised) and KEY not in raised.message
+
+
+def test_a_container_number_is_never_sent_to_unipass(monkeypatch):
+    # [왜] 화물통관진행정보는 화물관리번호·B/L로만 찾는다. 컨테이너 번호를 B/L 칸에 넣지 않는다 (계획 6a)
+    monkeypatch.setenv("MARVIA_UNIPASS_MODE", "live")
+    monkeypatch.setenv("MARVIA_UNIPASS_KEY", KEY)
+    real = unipass.Settings
+    monkeypatch.setattr(unipass, "Settings", lambda: real(_env_file=None))  # [왜] .env를 읽지 않는다
+    monkeypatch.setattr(unipass.httpx, "Client", lambda *a, **k: pytest.fail("컨테이너 번호로 HTTP를 열었다"))
+    error = lookup_cargo("DEMU1234560")
+    assert error == ToolError(
+        code="container_unknown", message=unipass.CFG["messages"]["container_unknown"], retryable=False
+    )
```
```diff
--- a/tests/graph/test_trace.py
+++ b/tests/graph/test_trace.py
@@ -146,3 +146,8 @@
     cleaned = scrub({"DEMO0001": "a", "DEMO0002": "b"})
     assert sorted(cleaned.values()) == ["a", "b"] and len(cleaned) == 2
     assert all("DEMO" not in key for key in cleaned)
+
+
+def test_scrub_hides_container_numbers_whole():
+    # [왜] 컨테이너 번호(11자)도 8자 이상 영문·숫자 덩어리라 같은 규칙에 걸린다 (계획 6a에서 확인)
+    assert scrub("컨테이너 DEMU1234560, DEMU-123456-0") == f"컨테이너 {MASK}, {MASK}"
```
```diff
--- a/tests/graph/test_server.py
+++ b/tests/graph/test_server.py
@@ -241,6 +241,14 @@
     assert [e["source_url"] for e in screen_view(values)["evidence"]] == [urls[0], None, None, None]
 
 
+def test_the_reading_list_names_a_container_number():
+    # [왜] 이름표 → 화면 이름 표에 없는 토큰은 KeyError로 화면 보기 전체를 깨뜨린다 (계획 6a)
+    from marvia.view import screen_view
+
+    reading = screen_view({"mask_map": {"[CNTR1]": "DEMU1234560"}})["reading"]
+    assert reading == [{"token": "[CNTR1]", "number": "DEMU1234560", "kind": "컨테이너 번호"}]
+
+
 def test_an_approval_card_carries_the_korean_label_and_the_choices_from_the_rules():
     # [왜] 화면이 규칙 목록을 따로 들고 있으면 규칙이 바뀔 때 어긋난다. 카드가 한국어 이름과 고를 값을 싣는다
     from marvia.tools.rules import load_rules
```
```diff
--- a/tests/graph/test_agent.py
+++ b/tests/graph/test_agent.py
@@ -1326,6 +1326,18 @@
     assert "감시할 수 없는 번호" in text
 
 
+def test_watch_cargo_refuses_a_container_token(agent_deps):
+    # [왜] 컨테이너 번호는 UNI-PASS로 다시 조회할 수 없다. 감시는 B/L·화물관리번호로만 한다 (계획 6a)
+    watch = FakeWatch()
+    ask = say(("watch_cargo", {"token": "[CNTR1]"}))
+    graph = agent_graph(agent_deps, ask, say(), permission_mode="auto", watch=watch.deps())
+    graph.invoke({"text": "DEMU1234560 지켜봐 줘"}, cfg("w5c"))
+    graph.invoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg("w5c"))
+    assert watch.added == []
+    text = [m.content for m in graph.get_state(cfg("w5c")).values["messages"] if m.type == "tool"][0]
+    assert "감시할 수 없는 번호" in text
+
+
 DONE = [
     # (도구 호출, 화면 답의 줄, 작성자가 받는 줄)
     (("watch_cargo", {"token": "[BL1]"}), "DEMO0001 감시 목록에 넣음", "[BL1] 감시 목록에 넣음"),
```

```bash
uv run pytest -q tests/identify tests/tools/test_unipass.py tests/graph/test_trace.py tests/graph/test_server.py tests/graph/test_agent.py -k container
```

Expected: FAIL. `tests/identify/test_parse.py` 모음 오류 `ImportError: cannot import name 'check_digit' from 'marvia.identify.parse'`. 그 파일을 빼면 4 failed: `test_mask`(`컨테이너 [BL1] 어디쯤이에요`), `test_unipass`(`Failed: 컨테이너 번호로 HTTP를 열었다`), `test_server`(`KeyError: 'CNTR'`), `test_agent`(`'[CNTR1]: 모르는 토큰이에요'`). `test_trace`의 확인 시험은 지금도 통과한다(붙여 쓴 꼴은 이미 가린다).

- [ ] **Step 2: 코드**

```diff
--- a/src/marvia/identify/parse.py
+++ b/src/marvia/identify/parse.py
@@ -4,15 +4,21 @@
 from __future__ import annotations
 
 import re
+import string
 from dataclasses import dataclass, field
 from typing import Literal
 
-Kind = Literal["cargo_no", "bl"]
+Kind = Literal["cargo_no", "bl", "container"]
 
 # 영문·숫자로 시작하고 끝나며 하이픈을 품을 수 있는 8자 이상 덩어리를 번호 후보로 본다
 _SPAN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{6,}[A-Za-z0-9]")
 # 화물관리번호 19자리 = MRN 11 + MSN 4 + HSN 4 (v1 customs.py:13). 뒤 8자리는 숫자로 본다
 _CARGO_NO = re.compile(r"[0-9A-Z]{11}[0-9]{8}")
+# 컨테이너 번호 (ISO 6346) = 소유자 부호 영문 3 + 장비 구분 U·J·Z + 일련번호 6 + 확인 숫자 1
+_CONTAINER = re.compile(r"[A-Z]{3}[UJZ][0-9]{7}")
+# ISO 6346 글자 값: A=10부터 차례로 매기되 11의 배수(11, 22, 33)는 건너뛴다 (A=10, B=12, ..., Z=38)
+# [왜] 표준이 정한 계산이라 rules/*.yaml에 두지 않는다 (_CARGO_NO, B/L 길이와 같다)
+_LETTER_VALUE = dict(zip(string.ascii_uppercase, (v for v in range(10, 39) if v % 11), strict=True))
 # 번호처럼 보여도 번호가 아닌 것: 날짜(YYYYMMDD), 휴대폰 번호
 _NOT_NUMBER = re.compile(r"20\d{6}|01[016789]\d{7,8}")
 # B/L 한 건의 길이 범위 (v1 patterns.py와 같은 8~20자)
@@ -45,9 +51,24 @@
     return raw.replace("-", "").upper()
 
 
+def check_digit(code: str) -> int:
+    """ISO 6346 확인 숫자: 앞 10자의 값에 자리마다 1, 2, 4, ... 512를 곱한 합을 11로 나눈 나머지(10이면 0)."""
+    total = sum((_LETTER_VALUE[ch] if ch.isalpha() else int(ch)) * 2**i for i, ch in enumerate(code[:10]))
+    return total % 11 % 10
+
+
+def is_container(value: str) -> bool:
+    """컨테이너 번호 모양이고 확인 숫자가 맞는가."""
+    return bool(_CONTAINER.fullmatch(value)) and check_digit(value) == int(value[-1])
+
+
 def kind_of(value: str) -> Kind:
-    """19자리 화물관리번호 형식이면 cargo_no, 아니면 bl."""
-    return "cargo_no" if _CARGO_NO.fullmatch(value) else "bl"
+    """19자리 화물관리번호 형식이면 cargo_no, 확인 숫자가 맞는 컨테이너 번호면 container, 아니면 bl."""
+    if _CARGO_NO.fullmatch(value):
+        return "cargo_no"
+    # [왜] 확인 숫자가 틀리면 컨테이너로 보지 않는다(오타일 수도, 같은 모양 B/L일 수도 있다).
+    #      식별 단계가 한 번 묻는다
+    return "container" if is_container(value) else "bl"
 
 
 def _prefix_split(token: str) -> list[str] | None:
@@ -64,7 +85,7 @@
 
 
 def read_token(raw: str) -> TokenRead:
-    """덩어리 하나를 읽는다. 순서: 화물관리번호 → 접두어 반복 나누기 → 한 건 → 애매함."""
+    """덩어리 하나를 읽는다. 순서: 화물관리번호 → 접두어 반복 나누기 → 한 건(컨테이너 또는 B/L) → 애매함."""
     token = normalize(raw)
     if _CARGO_NO.fullmatch(token):
         return TokenRead(raw, [ReadNumber(token, "cargo_no")])
@@ -72,7 +93,7 @@
     if parts:
         return TokenRead(raw, [ReadNumber(p, kind_of(p)) for p in parts])
     if _MIN_LEN <= len(token) <= _MAX_LEN:
-        return TokenRead(raw, [ReadNumber(token, "bl")])
+        return TokenRead(raw, [ReadNumber(token, kind_of(token))])
     # 너무 길고 나눌 근거가 없다: 반으로 나누는 안을 권장안으로, 통째로 읽는 안을 둘째로 둔다
     alternatives = [[token]]
     half = len(token) // 2
```
```diff
--- a/src/marvia/identify/mask.py
+++ b/src/marvia/identify/mask.py
@@ -1,15 +1,16 @@
-"""LLM에 넘기기 전에 화물 번호를 [BL1]·[CARGO1]·[NUM1] 토큰으로 가린다.
+"""LLM에 넘기기 전에 화물 번호를 [BL1]·[CARGO1]·[CNTR1]·[NUM1] 토큰으로 가린다.
 실제 값은 mask_map에만 두고, 화면에 보낼 때 unmask로 되돌린다 (설계 4.2, 12)."""
 
 from __future__ import annotations
 
 from marvia.identify.parse import Kind, normalize, read_numbers
 
-_LABEL: dict[str, str] = {"bl": "BL", "cargo_no": "CARGO", "unread": "NUM"}
+_LABEL: dict[str, str] = {"bl": "BL", "cargo_no": "CARGO", "container": "CNTR", "unread": "NUM"}
 # [왜] 토큰 이름표 목록. 토큰 모양을 정규식으로 찾는 쪽(graph/tools.py)이 같은 목록을 쓴다
 LABELS = tuple(_LABEL.values())
-# [왜] 읽은 번호(B/L·화물관리번호)의 이름표. 읽지 못한 덩어리(NUM)는 조회할 수 없어 뺀다
-READ_LABELS = tuple(label for kind, label in _LABEL.items() if kind != "unread")
+# [왜] UNI-PASS로 바로 조회할 수 있는 번호(B/L·화물관리번호)의 이름표. 읽지 못한 덩어리(NUM)와
+#      컨테이너(CNTR)는 뺀다. UNI-PASS 화물통관진행정보는 컨테이너 번호로 찾지 못한다 (계획 6a)
+READ_LABELS = (_LABEL["bl"], _LABEL["cargo_no"])
 
 
 def token_for(mask_map: dict[str, str], value: str, kind: Kind | str) -> str:
```
```diff
--- a/src/marvia/identify/models.py
+++ b/src/marvia/identify/models.py
@@ -39,7 +39,7 @@
     """식별 서브그래프의 결과 한 건. LLM은 token만 본다."""
 
     token: str  # LLM이 보는 가린 이름 (예: [BL1])
-    kind: Kind  # cargo_no(화물관리번호) 또는 bl
+    kind: Kind  # cargo_no(화물관리번호), bl, container(컨테이너 번호)
     cargo_no: str | None = None
     bl_no: str | None = None
     # [왜] UNI-PASS는 B/L 조회에 연도가 필요하다. 지난해 B/L을 올해로 찾으면 "없음"이 나온다
```
```diff
--- a/src/marvia/view.py
+++ b/src/marvia/view.py
@@ -16,7 +16,7 @@
 from marvia.tools.rules import load_rules
 
 # 토큰 이름표 → 화면에 보일 이름 ("이렇게 읽었어요")
-KIND_NAMES = {"BL": "B/L", "CARGO": "화물관리번호", "NUM": "읽지 못한 덩어리"}
+KIND_NAMES = {"BL": "B/L", "CARGO": "화물관리번호", "CNTR": "컨테이너 번호", "NUM": "읽지 못한 덩어리"}
 
 
 def _unmask_all(value: Any, mask_map: dict[str, str]) -> Any:
```
```diff
--- a/src/marvia/tools/unipass.py
+++ b/src/marvia/tools/unipass.py
@@ -150,7 +150,12 @@
 
 
 def lookup_cargo(number: str) -> CargoFacts | ToolError:
-    """번호 하나를 조회한다. 기본은 재생 데이터, MARVIA_UNIPASS_MODE=live에 키가 있을 때만 실제 API."""
+    """번호 하나를 조회한다. 기본은 재생 데이터, MARVIA_UNIPASS_MODE=live에 키가 있을 때만 실제 API.
+    컨테이너 번호는 어느 모드에서도 조회하지 않고 정한 글(container_unknown)을 돌려준다."""
+    if kind_of(number) == "container":
+        # [주의] 이 서비스는 화물관리번호·마스터 B/L·하우스 B/L로만 찾는다(data.go.kr 15126268).
+        #        컨테이너 번호를 B/L 칸에 넣어 보내지 않는다. 컨테이너는 이미 아는 화물에서 찾는다 (계획 6a)
+        return _error("container_unknown")
     settings = Settings()
     if settings.unipass_mode != "live":
         return unipass_replay.lookup_cargo(number)
```
```diff
--- a/src/marvia/graph/tools.py
+++ b/src/marvia/graph/tools.py
@@ -38,7 +38,7 @@
 from marvia.tools.rules import load_rules
 from marvia.watch import WatchDeps
 
-# 가린 토큰 모양: [BL1], [CARGO2], [NUM3]. [왜] 이름표는 identify.mask의 것을 그대로 쓴다
+# 가린 토큰 모양: [BL1], [CARGO2], [CNTR1], [NUM3]. [왜] 이름표는 identify.mask의 것을 그대로 쓴다
 TOKEN = re.compile(r"\[(?:" + "|".join(LABELS) + r")\d+\]")
 
 
@@ -501,7 +501,8 @@
         if number is None:
             return _reply(runtime, f"{token}: 모르는 토큰이에요")
         if not token.startswith(tuple(f"[{label}" for label in READ_LABELS)):
-            # [왜] 읽지 못한 덩어리([NUMn])는 조회가 될 수 없어 감시 목록에 넣으면 영원히 다시 조회만 한다
+            # [왜] 읽지 못한 덩어리([NUMn])와 컨테이너([CNTRn])는 UNI-PASS로 조회할 수 없어 감시 목록에 넣으면
+            #      영원히 다시 조회만 한다
             return _reply(runtime, f"{token}: 조회할 수 없어서 감시할 수 없는 번호예요")
         cargo = next((c for c in runtime.state.get("cargos", []) if c["token"] == token and c["facts"]), None)
         # [주의] 실제 번호는 서버의 감시 표에만 들어간다. 모델에게 주는 글과 인자는 토큰뿐이다 (설계 12절)
```
```diff
--- a/rules/unipass.yaml
+++ b/rules/unipass.yaml
@@ -15,4 +15,5 @@
   not_found: UNI-PASS에 없는 번호예요. 번호와 B/L 연도를 확인해 주세요
   ambiguous: 이 B/L에 화물이 여럿이에요. 화물관리번호로 조회해 주세요
   no_key: UNI-PASS 키가 없어 실제 조회를 하지 않았어요
+  container_unknown: UNI-PASS는 컨테이너 번호로 화물을 찾지 못해요. B/L 번호나 화물관리번호를 알려 주세요
 retryable: [timeout, unavailable] # 다시 시도하면 나아질 수 있는 오류
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `757 passed`, 오류 0.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/identify/parse.py src/marvia/identify/mask.py src/marvia/identify/models.py src/marvia/view.py \
  src/marvia/tools/unipass.py src/marvia/graph/tools.py rules/unipass.yaml tests/identify/test_parse.py \
  tests/identify/test_mask.py tests/tools/test_unipass.py tests/graph/test_trace.py tests/graph/test_server.py \
  tests/graph/test_agent.py
git commit -m "feat(identify): 컨테이너 번호를 확인 숫자로 읽어 [CNTR] 토큰으로 가리고 UNI-PASS에 보내지 않음"
```

#### 커밋 1b: feat(identify): 띄어 쓴 컨테이너 번호도 한 덩어리로 가림

**Files:**
- Modify: `src/marvia/identify/parse.py`
- Test: `tests/identify/test_parse.py`, `tests/identify/test_mask.py`, `tests/graph/test_trace.py`

**Interfaces:**
- Produces: `normalize`가 빈칸도 뺀다. `find_spans`가 띄어 쓴 컨테이너 번호(확인 숫자가 맞을 때만)를 한 덩어리로 돌려주고 그 조각은 따로 잡지 않는다. `mask_text`와 `trace.scrub_text`는 같은 `find_spans`를 쓰므로 함께 바뀐다

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/identify/test_parse.py
+++ b/tests/identify/test_parse.py
@@ -60,3 +60,9 @@
         ("DEMU1234560", "container"),
         ("DEMU2345676", "container"),
     ]
+
+
+def test_a_spaced_container_is_one_number_only_when_its_check_digit_holds():
+    assert values("컨테이너 DEMU 123456 0, TESU 0000013") == [["DEMU1234560"], ["TESU0000013"]]
+    assert values("DEMU 123456-0 도착") == [["DEMU1234560"]]  # 조각 123456-0이 따로 잡히지 않는다
+    assert values("ABCU 1234567 같은 글") == []  # 확인 숫자가 틀리면 번호로 보지 않는다(전과 같다)
```
```diff
--- a/tests/identify/test_mask.py
+++ b/tests/identify/test_mask.py
@@ -50,3 +50,8 @@
     assert (masked, mask_map) == ("컨테이너 [CNTR1] 어디쯤이에요", {"[CNTR1]": "DEMU1234560"})
     # [왜] READ_LABELS는 UNI-PASS로 바로 조회할 수 있는 번호의 이름표다. 감시 목록이 이것으로 거른다
     assert "CNTR" in LABELS and "CNTR" not in READ_LABELS
+
+
+def test_a_spaced_container_is_masked_whole():
+    masked, mask_map = mask_text("DEMU 123456 0 어디쯤?")
+    assert (masked, mask_map) == ("[CNTR1] 어디쯤?", {"[CNTR1]": "DEMU1234560"})
```
```diff
--- a/tests/graph/test_trace.py
+++ b/tests/graph/test_trace.py
@@ -151,3 +151,7 @@
 def test_scrub_hides_container_numbers_whole():
     # [왜] 컨테이너 번호(11자)도 8자 이상 영문·숫자 덩어리라 같은 규칙에 걸린다 (계획 6a에서 확인)
     assert scrub("컨테이너 DEMU1234560, DEMU-123456-0") == f"컨테이너 {MASK}, {MASK}"
+
+
+def test_scrub_hides_a_spaced_container_number():
+    assert scrub("DEMU 123456 0 도착") == f"{MASK} 도착"
```

```bash
uv run pytest -q tests/identify tests/graph/test_trace.py -k spaced
```

Expected: 3 failed: `assert [] == [['DEMU1234560'], ['TESU0000013']]`, `('DEMU 123456 0 어디쯤?', {})`, `'DEMU 123456 0 도착' == '[가림] 도착'`

- [ ] **Step 2: 코드**

```diff
--- a/src/marvia/identify/parse.py
+++ b/src/marvia/identify/parse.py
@@ -19,6 +19,9 @@
 # ISO 6346 글자 값: A=10부터 차례로 매기되 11의 배수(11, 22, 33)는 건너뛴다 (A=10, B=12, ..., Z=38)
 # [왜] 표준이 정한 계산이라 rules/*.yaml에 두지 않는다 (_CARGO_NO, B/L 길이와 같다)
 _LETTER_VALUE = dict(zip(string.ascii_uppercase, (v for v in range(10, 39) if v % 11), strict=True))
+# 띄어 쓴 컨테이너 번호 (DEMU 123456 0, DEMU 1234560). [왜] 서류·컨테이너 문에 이렇게 적는다. 나뉜 조각은
+#      8자보다 짧아 _SPAN이 못 찾고, 못 찾으면 가리지 않은 채 LLM에 간다
+_SPACED_CONTAINER = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{3}[UJZujz][ -]?[0-9]{6}[ -]?[0-9](?![A-Za-z0-9])")
 # 번호처럼 보여도 번호가 아닌 것: 날짜(YYYYMMDD), 휴대폰 번호
 _NOT_NUMBER = re.compile(r"20\d{6}|01[016789]\d{7,8}")
 # B/L 한 건의 길이 범위 (v1 patterns.py와 같은 8~20자)
@@ -47,8 +50,8 @@
 
 
 def normalize(raw: str) -> str:
-    """하이픈을 빼고 대문자로 바꾼다."""
-    return raw.replace("-", "").upper()
+    """하이픈·빈칸을 빼고 대문자로 바꾼다."""
+    return raw.replace("-", "").replace(" ", "").upper()
 
 
 def check_digit(code: str) -> int:
@@ -103,13 +106,22 @@
 
 
 def find_spans(text: str) -> list[Span]:
-    """글에서 번호 후보 덩어리의 위치를 찾는다. 숫자가 없거나 날짜·전화번호면 뺀다."""
-    spans = []
+    """글에서 번호 후보 덩어리의 위치를 찾는다. 숫자가 없거나 날짜·전화번호면 뺀다.
+    띄어 쓴 컨테이너 번호는 확인 숫자가 맞을 때만 한 덩어리로 본다."""
+    # [왜] 확인 숫자로 거른다. "영문 4자 숫자 7자리"처럼 띄어 쓴 다른 글을 번호로 잡지 않는다
+    spans = [
+        Span(m.start(), m.end(), m.group())
+        for m in _SPACED_CONTAINER.finditer(text)
+        if " " in m.group() and is_container(normalize(m.group()))
+    ]
+    taken = list(spans)
     for m in _SPAN.finditer(text):
         raw = m.group()
+        if any(s.start < m.end() and m.start() < s.end for s in taken):
+            continue  # 띄어 쓴 컨테이너 번호의 조각이다
         if any(ch.isdigit() for ch in raw) and not _NOT_NUMBER.fullmatch(normalize(raw)):
             spans.append(Span(m.start(), m.end(), raw))
-    return spans
+    return sorted(spans, key=lambda s: s.start)
 
 
 def read_numbers(text: str) -> list[tuple[Span, TokenRead]]:
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `760 passed`, 오류 0.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/identify/parse.py tests/identify/test_parse.py tests/identify/test_mask.py tests/graph/test_trace.py
git commit -m "feat(identify): 띄어 쓴 컨테이너 번호도 확인 숫자가 맞으면 한 덩어리로 가림"
```

### Task 2: 재생 화물 사실에 컨테이너 번호 (C1)

**배울 것:** 재생 fixture는 실제 응답의 모양만 흉내 낸 가공값이다. 한 컨테이너에 여러 하우스 B/L이 실리는 혼재(LCL)가 있어 컨테이너 하나가 화물 여럿을 가리킬 수 있다. 그래서 `TESU0000013`을 DEMO0002·DEMO0003에 함께 둔다. 실제 응답(`parse_progress`)은 칸을 확인하기 전까지 `containers`를 채우지 않는다(결정과 근거).

#### 커밋 2: feat(identify): 재생 화물 사실에 컨테이너 번호 칸

**Files:**
- Modify: `src/marvia/identify/models.py`, `fixtures/unipass/DEMO0001.json`, `fixtures/unipass/DEMO0002.json`, `fixtures/unipass/DEMO0003.json`
- Test: `tests/tools/test_unipass_replay.py`

**Interfaces:**
- Produces: `CargoFacts.containers: list[str] = []`. 재생 데이터: DEMO0001 → `DEMU1234560`, DEMO0002 → `DEMU2345676`·`TESU0000013`, DEMO0003 → `TESU0000013`, MOCK·TEST 화물은 없음

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/tools/test_unipass_replay.py
+++ b/tests/tools/test_unipass_replay.py
@@ -1,5 +1,8 @@
+import json
+
 from marvia.identify.models import CargoFacts, ToolError
-from marvia.tools.unipass_replay import lookup_cargo
+from marvia.identify.parse import is_container
+from marvia.tools.unipass_replay import FIXTURES, lookup_cargo
 
 
 def test_found():
@@ -18,3 +21,14 @@
     err = lookup_cargo("NOPE00000")
     assert isinstance(err, ToolError)
     assert "NOPE00000" not in err.message
+
+
+def test_replay_facts_carry_valid_container_numbers():
+    # [왜] 컨테이너 번호로 아는 화물을 찾는 시험의 바탕이다. 한 컨테이너에 화물 둘(DEMO0002·DEMO0003)도 있다
+    facts = lookup_cargo("DEMO0002")
+    assert isinstance(facts, CargoFacts) and facts.containers == ["DEMU2345676", "TESU0000013"]
+    other = lookup_cargo("MOCK12345678")
+    assert isinstance(other, CargoFacts) and other.containers == []  # 컨테이너를 모르는 화물
+    for path in FIXTURES.glob("*.json"):
+        for number in json.loads(path.read_text(encoding="utf-8")).get("containers", []):
+            assert is_container(number), (path.name, number)  # 가공값도 확인 숫자가 맞아야 한다
```

```bash
uv run pytest -q tests/tools/test_unipass_replay.py
```

Expected: 1 failed `AttributeError: 'CargoFacts' object has no attribute 'containers'`

- [ ] **Step 2: 코드와 fixture**

```diff
--- a/src/marvia/identify/models.py
+++ b/src/marvia/identify/models.py
@@ -22,6 +22,9 @@
     vessel_name: str | None = None
     port: str | None = None
     mrn: str | None = None  # 적하목록 관리번호 11자리. 배를 특정하는 데 쓴다
+    # 이 화물을 실은 컨테이너 번호들. 컨테이너 번호로 아는 화물을 찾는 데만 쓴다 (계획 6a).
+    # [주의] LLM에 넘기지 않는다. 실제 응답(parse_progress)에서는 아직 채우지 않는다(그 칸을 확인하지 못했다)
+    containers: list[str] = Field(default_factory=list)
     # [왜] 근거 카드에 "어디서, 언제 가져온 값인지"를 항상 보여 주기 위해 출처와 조회 시각을 붙인다
     source: str = "unipass_replay"
     fetched_at: datetime
```
```diff
--- a/fixtures/unipass/DEMO0001.json
+++ b/fixtures/unipass/DEMO0001.json
@@ -1 +1 @@
-{"stage": "반입신고", "stage_at": "2026-10-27T09:00:00+09:00", "vessel_name": "TEST VESSEL ONE", "port": "부산", "mrn": "26DEMO0001I"}
+{"stage": "반입신고", "stage_at": "2026-10-27T09:00:00+09:00", "vessel_name": "TEST VESSEL ONE", "port": "부산", "mrn": "26DEMO0001I", "containers": ["DEMU1234560"]}
```
```diff
--- a/fixtures/unipass/DEMO0002.json
+++ b/fixtures/unipass/DEMO0002.json
@@ -1 +1 @@
-{"stage": "수입신고", "stage_at": "2026-10-27T15:30:00+09:00", "vessel_name": "TEST VESSEL ONE", "port": "부산", "mrn": "26DEMO0001I"}
+{"stage": "수입신고", "stage_at": "2026-10-27T15:30:00+09:00", "vessel_name": "TEST VESSEL ONE", "port": "부산", "mrn": "26DEMO0001I", "containers": ["DEMU2345676", "TESU0000013"]}
```
```diff
--- a/fixtures/unipass/DEMO0003.json
+++ b/fixtures/unipass/DEMO0003.json
@@ -1 +1 @@
-{"stage": "수입신고수리", "stage_at": "2026-11-02T10:00:00+09:00", "vessel_name": "TEST VESSEL ONE", "port": "부산", "mrn": "26DEMO0001I"}
+{"stage": "수입신고수리", "stage_at": "2026-11-02T10:00:00+09:00", "vessel_name": "TEST VESSEL ONE", "port": "부산", "mrn": "26DEMO0001I", "containers": ["TESU0000013"]}
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `761 passed`, 오류 0. 평가 시험(`tests/eval/test_dataset.py::test_v2_identify_gold_comes_from_the_replay_fixtures`)은 단계만 보므로 그대로 통과한다.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/identify/models.py fixtures/unipass/DEMO0001.json fixtures/unipass/DEMO0002.json \
  fixtures/unipass/DEMO0003.json tests/tools/test_unipass_replay.py
git commit -m "feat(identify): 재생 화물 사실에 가공 컨테이너 번호 칸을 둠"
```

### Task 3: 감시 목록 번호 읽기 (C6 바탕)

**배울 것:** 감시 표의 번호는 Fernet 암호문이라 줄마다 풀어 읽는다. 다른 키로 넣은 줄은 `InvalidToken`이라 건너뛴다(`take_news`와 같다). 읽기 트랜잭션은 `commit`으로 닫고 오류면 `rollback` 뒤 다시 던진다(R-066과 같은 이유). `WatchDeps.numbers`는 없어도 되는 칸이라 지금의 가짜 감시들은 그대로다.

#### 커밋 3: feat(watch): 사용자의 감시 번호를 읽는 list_watched

**Files:**
- Modify: `src/marvia/watch.py`
- Test: `tests/test_watch.py`

**Interfaces:**
- Produces: `marvia.watch.list_watched(conn, keys, user) -> list[str]`(넣은 순서), `WatchDeps.numbers: Callable[[str], list[str]] | None = None`, `live_watch`가 `numbers`를 채운다

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/test_watch.py
+++ b/tests/test_watch.py
@@ -14,6 +14,7 @@
     add_watch,
     derive_key,
     forget_user,
+    list_watched,
     number_hash,
     recheck,
     remove_watch,
@@ -157,6 +158,16 @@
     assert remove_watch(db, keys, "u1", "DEMO0001") == 0  # 이미 지웠다
 
 
+def test_list_watched_gives_that_users_numbers_in_order(db, keys):
+    # [왜] 컨테이너 번호로 아는 화물을 찾을 때 감시 목록도 본다 (계획 6a). 남의 감시는 보이지 않는다
+    add_watch(db, keys, "u1", "DEMO0002", "수입신고")
+    add_watch(db, keys, "u1", "DEMO0003", "수입신고수리")
+    add_watch(db, keys, "u2", "DEMO0001", "반입신고")
+    add_watch(db, make_keys(), "u1", "DEMO0001", "반입신고")  # 다른 키로 넣은 줄은 풀지 못해 건너뛴다
+    assert list_watched(db, keys, "u1") == ["DEMO0002", "DEMO0003"]
+    assert list_watched(db, keys, "nobody") == []
+
+
 def test_watch_keys_repr_hides_hash_key():
     secret = Fernet.generate_key().decode()
     assert repr(derive_key(secret, HASH_INFO)) not in repr(
```

```bash
uv run pytest -q tests/test_watch.py -k list_watched
```

Expected: FAIL `ImportError: cannot import name 'list_watched' from 'marvia.watch'`

- [ ] **Step 2: 코드**

```diff
--- a/src/marvia/watch.py
+++ b/src/marvia/watch.py
@@ -68,6 +68,8 @@
     ack: Callable[[str, list[int]], None]  # (사용자, 변화 id들) → 답에 보인 변화를 본 것으로 표시
     # (사용자, 실제 번호) → 그 화물을 감시 목록에서 지우고 지운 수. 없으면 unwatch_cargo 도구도 없다 (R-033)
     remove: Callable[[str, str], int] | None = None
+    # 사용자 → 감시 목록의 실제 번호들. 컨테이너 번호로 아는 화물을 찾을 때 쓴다 (계획 6a)
+    numbers: Callable[[str], list[str]] | None = None
 
 
 def add_watch(conn: psycopg.Connection, keys: WatchKeys, user: str, number: str, stage: str) -> None:
@@ -157,6 +159,26 @@
         raise
 
 
+def list_watched(conn: psycopg.Connection, keys: WatchKeys, user: str) -> list[str]:
+    """사용자의 감시 목록에 든 실제 번호를 넣은 순서대로 돌려준다."""
+    try:
+        rows = conn.execute(
+            "SELECT number_enc FROM watches WHERE user_id = %s ORDER BY id", (user,)
+        ).fetchall()
+        conn.commit()  # 읽기 트랜잭션을 닫는다
+    except psycopg.Error:
+        # [왜] 실패한 트랜잭션이 남으면 같은 연결의 다음 질의가 모두 죽는다. 되돌린 뒤 다시 던진다
+        conn.rollback()
+        raise
+    numbers = []
+    for (enc,) in rows:
+        try:
+            numbers.append(keys.fernet.decrypt(enc.encode()).decode())
+        except InvalidToken:
+            continue  # [왜] 키를 바꾼 뒤 남은 줄은 번호를 알 수 없다 (take_news와 같다)
+    return numbers
+
+
 def remove_watch(conn: psycopg.Connection, keys: WatchKeys, user: str, number: str) -> int:
     """사용자의 감시 목록에서 화물 하나를 지운다. 그 변화 기록도 함께 지워진다. 지운 줄 수를 돌려준다."""
     try:
@@ -196,4 +218,5 @@
         news=lambda user: take_news(conn, keys, user),
         ack=lambda user, ids: ack_news(conn, user, ids),
         remove=lambda user, number: remove_watch(conn, keys, user, number),
+        numbers=lambda user: list_watched(conn, keys, user),
     )
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `762 passed`, 오류 0.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/watch.py tests/test_watch.py
git commit -m "feat(watch): 사용자의 감시 번호를 넣은 순서대로 읽는 list_watched"
```

### Task 4: 아는 화물에서 컨테이너 찾기 (C3, C5~C7)

**배울 것:** 조회 서브그래프(`build_lookup_graph`)는 식별 서브그래프 안, 선택지 뒤 메인 그래프의 `lookup`, 에이전트 도구 `lookup_cargo` 세 곳에서 쓴다. 그래서 컨테이너를 화물로 바꾸는 일을 그 안의 `collect`에 두면 세 길과 두 루프가 같은 코드를 지난다. LangGraph는 노드 함수에 `config` 인자가 있으면 실행 설정을 넘기고, 도구 안에서 `invoke`한 서브그래프도 부모의 `configurable`을 받는다 [실측 11-07, 커밋 4a의 도구 길 시험]. `collect`가 읽는 공책의 `cargos`는 이번 결과로 바뀌기 전 값(지난 차례의 화물)이다. 묻는 일은 식별 서브그래프가 `question`에 담아 끝내고 메인 그래프의 `ask`가 한다(설계 6.3). `ask`는 고른 번호를 `numbers`에 더하므로, 선택지를 만들 때 컨테이너 번호를 `numbers`에서 빼야 같은 후보가 다시 나오지 않는다.

#### 커밋 4a: feat(graph): 컨테이너 번호를 이 대화와 감시 목록의 화물에서 찾음

**Files:**
- Modify: `src/marvia/graph/identify.py`, `src/marvia/graph/tools.py`, `src/marvia/graph/main.py`, `rules/unipass.yaml`
- Test: `tests/graph/test_identify.py`, `tests/graph/test_agent.py`

**Interfaces:**
- Consumes: `kind_of`의 `"container"`(T1), `CargoFacts.containers`(T2), `WatchDeps.numbers`(T3)
- Produces: `identify.Watched = Callable[[RunnableConfig], list[str]]`, `identify.known_cargo(cargos, watched) -> list[dict]`, `identify.container_identity(container, mask_map, known) -> dict`(CargoIdentity dict: 하나면 confirmed와 facts, 여럿이면 candidate와 `candidates`·`container_many`, 없으면 unknown과 `container_unknown`), `build_lookup_graph(watched=None)`, `build_identify_graph(watched=None)`, `tools.watched(watch) -> Watched | None`, `rules/unipass.yaml messages.container_many`

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_identify.py
+++ b/tests/graph/test_identify.py
@@ -49,3 +49,80 @@
     out = run("DEMO0001DEMO0002 어디야?")
     assert [c["facts"] is not None for c in out["cargos"]] == [True, False]
     assert out["cargos"][1]["error"] == {"code": "lookup_failed", "message": "OSError", "retryable": True}
+
+
+def spy(monkeypatch) -> list[str]:
+    """식별이 조회 함수(lookup_cargo)에 넘긴 번호를 모은다."""
+    from marvia.graph import identify
+
+    seen: list[str] = []
+    real = identify.lookup_cargo
+
+    def lookup(number):
+        seen.append(number)
+        return real(number)
+
+    monkeypatch.setattr(identify, "lookup_cargo", lookup)
+    return seen
+
+
+def test_a_container_is_found_among_cargo_this_conversation_already_looked_up(monkeypatch):
+    # [왜] UNI-PASS는 컨테이너 번호로 찾지 못한다. 지난 차례에 조회한 화물의 사실에서 찾는다 (계획 6a)
+    first = run("DEMO0001 어디야?")
+    seen = spy(monkeypatch)
+    out = build_identify_graph().invoke(
+        {
+            "text": "컨테이너 DEMU1234560 어디쯤이에요?",
+            "mask_map": first["mask_map"],
+            "cargos": first["cargos"],
+        }
+    )
+    assert out["masked_text"] == "컨테이너 [CNTR1] 어디쯤이에요?"
+    cargo = out["cargos"][0]
+    assert (cargo["token"], cargo["kind"], cargo["bl_no"], cargo["confidence"]) == (
+        "[CNTR1]",
+        "container",
+        "DEMO0001",
+        "confirmed",
+    )
+    assert cargo["facts"]["stage"] == "반입신고"
+    assert seen == []  # 컨테이너 번호로는 아무것도 조회하지 않았다
+
+
+def test_a_bl_in_the_same_message_carries_the_container(monkeypatch):
+    seen = spy(monkeypatch)
+    out = run("DEMO0001 컨테이너 DEMU1234560 둘 다 봐 줘")
+    assert [(c["token"], c["facts"]["stage"]) for c in out["cargos"]] == [
+        ("[BL1]", "반입신고"),
+        ("[CNTR1]", "반입신고"),
+    ]
+    assert seen == ["DEMO0001"]
+
+
+def test_a_container_on_two_watched_cargos_is_left_as_candidates(monkeypatch):
+    # [왜] 한 컨테이너에 여러 화물(LCL)이 실릴 수 있다. 하나를 골라 답하지 않는다
+    seen = spy(monkeypatch)
+    out = build_identify_graph(lambda config: ["DEMO0002", "DEMO0003"]).invoke(
+        {"text": "TESU0000013 어디야?"}
+    )
+    cargo = out["cargos"][0]
+    assert (cargo["token"], cargo["confidence"], cargo["candidates"]) == (
+        "[CNTR1]",
+        "candidate",
+        ["DEMO0002", "DEMO0003"],
+    )
+    assert cargo["error"]["code"] == "container_many" and cargo["facts"] is None
+    assert seen == ["DEMO0002", "DEMO0003"]  # 감시 목록 화물만 다시 조회했다
+
+
+def test_an_unknown_container_gets_the_fixed_line_without_any_lookup(monkeypatch):
+    from marvia.tools.rules import load_rules
+
+    seen = spy(monkeypatch)
+    out = build_identify_graph(lambda config: []).invoke({"text": "NOPU1234560 어디야?"})
+    assert out["cargos"][0]["error"] == {
+        "code": "container_unknown",
+        "message": load_rules("unipass")["messages"]["container_unknown"],
+        "retryable": False,
+    }
+    assert seen == []
```
```diff
--- a/tests/graph/test_agent.py
+++ b/tests/graph/test_agent.py
@@ -1062,6 +1062,47 @@
     assert "DEMO0001" not in all_text(values)
 
 
+# --- 컨테이너 번호 (계획 6a) ---
+
+
+def watching(numbers_of):
+    """감시 목록 번호만 주는 가짜 감시. numbers_of: 사용자 → 그 사용자의 감시 번호들."""
+    from marvia.watch import WatchDeps
+
+    return WatchDeps(
+        add=lambda *row: None, news=lambda user: [], ack=lambda user, ids: None, numbers=numbers_of
+    )
+
+
+@pytest.mark.parametrize("loop", ["planner", "agent"])
+def test_both_loops_find_a_container_among_the_users_watched_cargo_alike(agent_deps, loop):
+    users: list[str] = []
+    watch = watching(lambda user: users.append(user) or ["DEMO0001"])
+    graph = build_main_graph(agent_deps(model=model(say()), watch=watch), InMemorySaver(), loop=loop)
+    config = {"configurable": {"thread_id": f"cn-{loop}", "user_id": "u1"}}
+    out = graph.invoke({"text": "컨테이너 DEMU1234560 어디쯤이에요?"}, config)
+    assert "DEMU1234560: 반입신고 (부산) 2026-10-27" in out["answer"]  # 코드가 쓴 화물 줄
+    assert users == ["u1"]  # 그 사용자의 감시 목록만 봤다
+    cargo = graph.get_state(config).values["cargos"][0]
+    assert (cargo["token"], cargo["kind"], cargo["bl_no"]) == ("[CNTR1]", "container", "DEMO0001")
+
+
+def test_lookup_cargo_tool_matches_a_container_token_without_showing_numbers(agent_deps):
+    inputs = Inputs()
+    watch = watching(lambda user: ["DEMO0001"] if user == "u1" else [])
+    ask = say(("ask_user", {"question": "컨테이너 번호를 알려 주세요", "options": TWO}))
+    look = say(("lookup_cargo", {"tokens": ["[CNTR1]"]}))
+    graph = agent_graph(agent_deps, ask, look, say(), watch=watch)
+    config = {"configurable": {"thread_id": "cn-tool", "user_id": "u1"}, "callbacks": [inputs]}
+    graph.invoke({"text": "제 화물 어디쯤이에요?"}, config)
+    # [왜] 직접 쓴 답의 번호는 가리기만 한다. 그래서 컨테이너 토큰을 도구가 처음 찾는다
+    out = graph.invoke(Command(resume={"custom": "DEMU1234560"}), config)
+    tool_text = [m.content for m in graph.get_state(config).values["messages"] if m.type == "tool"][-1]
+    assert tool_text == "[CNTR1]: 반입신고 (부산) 2026-10-27"
+    assert "DEMU1234560: 반입신고" in out["answer"]
+    assert not any("DEMU1234560" in call or "DEMO0001" in call for call in inputs.calls)
+
+
 # --- 색인 밖 공식 출처 조회 (계획 3d) ---
 
 # 국가법령정보센터 법령 정보 페이지에서 fetch.law_info·title이 읽는 부분만 흉내 낸 가짜 페이지
```

```bash
uv run pytest -q tests/graph/test_identify.py tests/graph/test_agent.py -k "container or loops_find"
```

Expected: 7 failed, 1 passed(1a의 감시 시험). 식별 시험은 `build_identify_graph() takes 0 positional arguments but 1 was given` 또는 화물 줄이 `container_unknown`, 두 길 시험과 도구 시험은 `'[CNTR1]: 조회하지 못했어요 (UNI-PASS는 컨테이너 번호로 화물을 찾지 못해요. B/L 번호나 화물관리번호를 알려 주세요, container_unknown)' == '[CNTR1]: 반입신고 (부산) 2026-10-27'` 꼴로 실패한다.

- [ ] **Step 2: 코드**

```diff
--- a/src/marvia/graph/identify.py
+++ b/src/marvia/graph/identify.py
@@ -3,13 +3,16 @@
 하지 않는 일: 사용자에게 직접 묻기. 애매하면 question에 담아 끝내고, 묻는 일은 메인 그래프만 한다 (설계 6.3).
 순서도: START → read → (애매하면 END, 아니면 lookup) → END
 조회(lookup)는 따로 컴파일한 서브그래프다: assign → 번호마다 Send("one") → collect (설계 4.3, 계획 3d)
+컨테이너 번호는 UNI-PASS로 조회하지 않고 collect가 아는 화물(이 대화, 감시 목록)에서 찾는다 (계획 6a)
 """
 
 from __future__ import annotations
 
 import operator
+from collections.abc import Callable
 from typing import Annotated, TypedDict
 
+from langchain_core.runnables import RunnableConfig
 from langgraph.graph import END, START, StateGraph
 from langgraph.types import Send
 
@@ -17,8 +20,12 @@
 from marvia.identify.mask import mask_text, token_for
 from marvia.identify.models import CargoFacts, CargoIdentity, ToolError
 from marvia.identify.parse import kind_of, read_numbers
+from marvia.tools.rules import load_rules
 from marvia.tools.unipass import lookup_cargo
 
+# 실행 설정 → 그 사용자의 감시 목록 번호 (graph/tools.py의 watched가 만든다). 컨테이너를 찾을 때만 부른다
+Watched = Callable[[RunnableConfig], list[str]]
+
 
 def read(state: IdentifyState) -> dict:
     """번호를 읽고 가린다. 애매한 덩어리가 있으면 선택지 질문을 만든다."""
@@ -74,6 +81,54 @@
     return identity.model_dump(mode="json")
 
 
+def known_cargo(cargos: list[dict], watched: list[str]) -> list[dict]:
+    """컨테이너 번호를 맞춰 볼 화물 사실: 이미 조회한 화물(cargos)과 감시 목록 번호(다시 조회)."""
+    known = [cargo["facts"] for cargo in cargos if cargo.get("facts")]
+    have = {facts["number"] for facts in known}
+    for number in watched:
+        if number in have:
+            continue
+        try:
+            result = lookup_cargo(number)
+        except (OSError, ValueError):
+            continue  # [왜] 감시 화물 하나의 조회 오류로 찾기 전체를 멈추지 않는다 (identify_number와 같다)
+        if isinstance(result, CargoFacts):
+            known.append(result.model_dump(mode="json"))
+            have.add(number)
+    return known
+
+
+def container_identity(container: str, mask_map: dict[str, str], known: list[dict]) -> dict:
+    """컨테이너 번호를 아는 화물 사실에서 찾는다. 하나면 그 화물, 여럿이면 후보, 없으면 정한 글로 남긴다."""
+    found = {facts["number"]: facts for facts in known if container in facts.get("containers", [])}
+    token = token_for(mask_map, container, "container")
+    if len(found) == 1:
+        facts = next(iter(found.values()))
+        number = facts["number"]
+        # [왜] 토큰은 사용자가 준 단서(컨테이너)의 것이다. 답의 화물 줄도 그 번호로 보인다
+        identity = CargoIdentity(
+            token=token,
+            kind="container",
+            cargo_no=number if kind_of(number) == "cargo_no" else None,
+            bl_no=number if kind_of(number) == "bl" else None,
+            mrn=facts.get("mrn"),
+            vessel=facts.get("vessel_name"),
+            confidence="confirmed",
+            facts=CargoFacts.model_validate(facts),
+        )
+    else:
+        # [주의] 후보 중 하나를 골라 답하지 않는다. 틀리면 다른 화물의 단계를 말한다
+        code = "container_many" if found else "container_unknown"
+        identity = CargoIdentity(
+            token=token,
+            kind="container",
+            confidence="candidate" if found else "unknown",
+            candidates=sorted(found),
+            error=ToolError(code=code, message=load_rules("unipass")["messages"][code], retryable=False),
+        )
+    return identity.model_dump(mode="json")
+
+
 class LookupState(IdentifyState, total=False):
     """조회 서브그래프의 공책: 식별 칸에 갈래 결과 칸을 더한다. found는 서브그래프 밖으로 내보내지 않는다."""
 
@@ -100,12 +155,14 @@
 
 
 def fan_out(state: IdentifyState) -> list[Send] | str:
-    """번호마다 갈래(Send) 하나를 보낸다. 번호가 없으면 바로 모으기로 간다."""
-    numbers = state.get("numbers", [])
-    if not numbers:
-        return "collect"
+    """번호마다 갈래(Send) 하나를 보낸다. 컨테이너 번호는 collect가 찾는다. 보낼 것이 없으면 바로 collect."""
     mask_map = state.get("mask_map", {})
-    return [Send("one", {"idx": i, "number": n, "mask_map": mask_map}) for i, n in enumerate(numbers)]
+    sends = [
+        Send("one", {"idx": i, "number": n, "mask_map": mask_map})
+        for i, n in enumerate(state.get("numbers", []))
+        if kind_of(n) != "container"
+    ]
+    return sends or "collect"
 
 
 def one(state: LookupTask) -> dict:
@@ -115,14 +172,26 @@
     return {"found": [{"idx": state["idx"], "cargo": cargo}]}
 
 
-def collect(state: LookupState) -> dict:
-    """갈래 결과를 처음 번호 순서대로 화물 칸에 둔다."""
-    # [왜] 갈래가 끝나는 순서는 정해져 있지 않다. 순서 번호로 정렬한다 (강의 13강)
-    return {"cargos": [found["cargo"] for found in sorted(state.get("found", []), key=lambda f: f["idx"])]}
-
+def build_lookup_graph(watched: Watched | None = None):
+    """조회 서브그래프: 번호마다 Send로 나눠 함께 조회하고 처음 순서대로 모은다 (설계 4.3).
+    watched가 있으면 컨테이너 번호를 감시 목록의 화물에서도 찾는다 (계획 6a)."""
+
+    def collect(state: LookupState, config: RunnableConfig) -> dict:
+        """갈래 결과를 처음 번호 순서대로 화물 칸에 둔다. 컨테이너 번호는 아는 화물 사실에서 찾는다."""
+        found = {f["idx"]: f["cargo"] for f in state.get("found", [])}
+        numbers = state.get("numbers", [])
+        containers = {i: n for i, n in enumerate(numbers) if kind_of(n) == "container"}
+        if containers:
+            # [왜] 갈래 조회가 끝난 뒤에 찾는다. 같은 글에 함께 적은 B/L의 사실도 쓸 수 있다.
+            #      state의 cargos는 아직 이번 결과로 바뀌기 전 값(지난 차례·대화의 화물)이다
+            cargos = list(found.values()) + state.get("cargos", [])
+            known = known_cargo(cargos, watched(config) if watched else [])
+            mask_map = dict(state.get("mask_map", {}))
+            for i, number in containers.items():
+                found[i] = container_identity(number, mask_map, known)
+        # [왜] 갈래가 끝나는 순서는 정해져 있지 않다. 순서 번호로 정렬한다 (강의 13강)
+        return {"cargos": [found[i] for i in sorted(found)]}
 
-def build_lookup_graph():
-    """조회 서브그래프: 번호마다 Send로 나눠 함께 조회하고 처음 순서대로 모은다 (설계 4.3)."""
     # [왜] 들고 나는 모양은 식별 공책으로 둔다. 갈래 결과 칸(found)은 부모에 돌려주지 않는다
     graph = StateGraph(LookupState, input_schema=IdentifyState, output_schema=IdentifyState)
     graph.add_node("assign", assign)
@@ -141,11 +210,11 @@
     return END if state.get("question") else "lookup"
 
 
-def build_identify_graph():
-    """식별 순서도를 조립해 실행 기계로 만든다."""
+def build_identify_graph(watched: Watched | None = None):
+    """식별 순서도를 조립해 실행 기계로 만든다. watched는 조회 서브그래프에 넘긴다 (계획 6a)."""
     graph = StateGraph(IdentifyState)  # 공책 모양을 알려 준다
     graph.add_node("read", read)  # 작업자 등록
-    graph.add_node("lookup", build_lookup_graph())  # [왜] 컴파일한 그래프도 노드 하나로 넣는다
+    graph.add_node("lookup", build_lookup_graph(watched))  # [왜] 컴파일한 그래프도 노드 하나로 넣는다
     graph.add_edge(START, "read")  # 화살표: 시작하면 read
     # 갈림길: read가 끝나면 _after_read가 고른 곳으로 간다. 셋째 인자는 갈 수 있는 곳 목록(그림 그리기용)
     graph.add_conditional_edges("read", _after_read, ["lookup", END])
```
```diff
--- a/src/marvia/graph/tools.py
+++ b/src/marvia/graph/tools.py
@@ -26,7 +26,7 @@
 
 from marvia.graph.agent import build_researcher
 from marvia.graph.answer import cargo_lines
-from marvia.graph.identify import build_lookup_graph
+from marvia.graph.identify import Watched, build_lookup_graph
 from marvia.identify.mask import LABELS, READ_LABELS, mask_text
 from marvia.identify.parse import read_numbers
 from marvia.llm import LLMFailed
@@ -70,6 +70,23 @@
     return "local"
 
 
+def watched(watch: WatchDeps | None) -> Watched | None:
+    """컨테이너 찾기용 감시 목록 읽기: 실행 설정 → 그 사용자의 감시 번호 (계획 6a). 읽을 수 없으면 None."""
+    if watch is None or watch.numbers is None:
+        return None
+    numbers = watch.numbers
+
+    def read(config: RunnableConfig) -> list[str]:
+        user = user_of(config)  # [주의] 서버 길에서 user_id가 없으면 MissingUser로 멈춘다 (R-048)
+        try:
+            return numbers(user)
+        except psycopg.Error:
+            # [왜] 감시 목록은 덤이다. DB 오류면 이 대화의 화물에서만 찾는다 (news 노드와 같다)
+            return []
+
+    return read
+
+
 def _reply(runtime: ToolRuntime, text: str, **update) -> Command:
     """모델에게 돌려줄 결과 글(ToolMessage)과 공책에 쓸 칸을 함께 돌려준다."""
     # [왜] 도구가 공책 칸을 바꾸려면 Command(update=...)를 돌려준다. ToolMessage의 tool_call_id가
@@ -136,7 +153,8 @@
     # [왜] 에이전트 길의 RAG는 고쳐 쓰기를 agent.yaml 값으로 줄여 만든다(main.py). 최악도 같은 값으로 센다
     worst_search = worst_search_calls(load_rules("agent")["loop"]["rag_rewrites"])
     max_searches = load_rules("agent")["loop"]["max_searches"]
-    lookup_graph = build_lookup_graph()  # [왜] 식별과 같은 조회 서브그래프: 번호마다 Send 갈래로 조회한다
+    # [왜] 식별과 같은 조회 서브그래프: 번호마다 Send 갈래로 조회하고 컨테이너는 아는 화물에서 찾는다
+    lookup_graph = build_lookup_graph(watched(watch))
 
     @tool
     def search_law(query: str, runtime: ToolRuntime) -> Command:
@@ -238,7 +256,8 @@
     @tool
     def lookup_cargo(tokens: list[str], runtime: ToolRuntime) -> Command:
         """Look up the customs status of cargo tokens such as [BL1] (for example a number the user gave in
-        an answer). Returns one line per cargo.
+        an answer). A container token such as [CNTR1] is matched only against cargo already known in this
+        conversation or on the user's watch list. Returns one line per cargo.
         """
         mask_map = dict(runtime.state.get("mask_map", {}))
         known = [token for token in tokens if token in mask_map]
@@ -247,7 +266,13 @@
         need = [token for token in known if token not in have]
         # [주의] 실제 번호는 여기서만 꺼낸다. 결과 줄(cargo_lines)은 토큰으로 쓴다
         numbers = [mask_map[token] for token in need]
-        fresh = lookup_graph.invoke({"numbers": numbers, "mask_map": mask_map})["cargos"] if need else []
+        # [왜] 이 대화의 화물(cargos)도 넘긴다. 컨테이너 토큰은 그 사실에서 찾는다 (계획 6a)
+        known_cargos = runtime.state.get("cargos", [])
+        fresh = (
+            lookup_graph.invoke({"numbers": numbers, "mask_map": mask_map, "cargos": known_cargos})["cargos"]
+            if need
+            else []
+        )
         found = have | {cargo["token"]: cargo for cargo in fresh}
         cargos = [found[token] for token in known]
         lines = cargo_lines(cargos) + [
```
```diff
--- a/src/marvia/graph/main.py
+++ b/src/marvia/graph/main.py
@@ -44,6 +44,7 @@
     make_tools,
     search_calls,
     user_of,
+    watched,
     worst_search_calls,
 )
 from marvia.graph.verify import verify
@@ -469,9 +470,11 @@
     graph = StateGraph(MarviaState)
     graph.add_node("start", start)
     # [왜] 컴파일한 서브그래프도 노드 하나처럼 넣을 수 있다. 공책 칸 이름이 같아서 그대로 주고받는다
-    graph.add_node("identify", build_identify_graph())
+    # [왜] 두 길(계획자·에이전트)이 같은 식별을 쓴다. 컨테이너 번호는 감시 목록에서도 찾는다 (계획 6a)
+    graph.add_node("identify", build_identify_graph(watched(deps.watch)))
     graph.add_node("ask", ask)
-    graph.add_node("lookup", build_lookup_graph())  # 식별 서브그래프와 같은 조회 서브그래프를 다시 쓴다
+    # 식별 서브그래프와 같은 조회 서브그래프를 다시 쓴다
+    graph.add_node("lookup", build_lookup_graph(watched(deps.watch)))
     graph.add_node("write", write)
     graph.add_node("verify", check)
     graph.add_node("respond", shown(respond))
```
```diff
--- a/rules/unipass.yaml
+++ b/rules/unipass.yaml
@@ -16,4 +16,5 @@
   ambiguous: 이 B/L에 화물이 여럿이에요. 화물관리번호로 조회해 주세요
   no_key: UNI-PASS 키가 없어 실제 조회를 하지 않았어요
   container_unknown: UNI-PASS는 컨테이너 번호로 화물을 찾지 못해요. B/L 번호나 화물관리번호를 알려 주세요
+  container_many: 이 컨테이너에 실린 화물이 여럿이에요. B/L 번호나 화물관리번호를 알려 주세요
 retryable: [timeout, unavailable] # 다시 시도하면 나아질 수 있는 오류
```

- [ ] **Step 2b (11-07 정정, C10): 실제 모드에서는 감시 목록을 읽지 않는다.** 위 시험 끝에 아래 시험을 더하고 먼저 실패를 본 뒤(Expected FAIL: `assert asked == [] and seen == []`, 정정 전 코드는 감시 목록을 읽고 둘을 조회한다), 아래 코드를 넣는다. 시험의 가짜 조회는 실제 함수를 부르지 않는다(실제 모드라 HTTP가 열릴 수 있다). 시험 파일에 `RunnableConfig` import가 없으면 `from langchain_core.runnables import RunnableConfig`를 더한다.

```python
def test_live_mode_reads_no_watch_list_for_a_container(monkeypatch):
    # [왜] 실제 응답에는 컨테이너 칸이 없다. 감시 화물을 다시 조회해도 맞출 수 없다 (계획 6a 정정)
    from marvia.graph import identify
    from marvia.identify.models import ToolError
    from marvia.tools.rules import load_rules

    monkeypatch.setenv("MARVIA_UNIPASS_MODE", "live")
    seen: list[str] = []
    asked: list[RunnableConfig] = []

    def lookup(number: str) -> ToolError:
        seen.append(number)  # [주의] 실제 함수를 부르지 않는다
        return ToolError(code="not_found", message="", retryable=False)

    def watched(config: RunnableConfig) -> list[str]:
        asked.append(config)
        return ["DEMO0002", "DEMO0003"]

    monkeypatch.setattr(identify, "lookup_cargo", lookup)
    out = build_identify_graph(watched).invoke({"text": "TESU0000013 어디야?"})
    assert out["cargos"][0]["error"]["message"] == load_rules("unipass")["messages"]["container_unknown"]
    assert asked == [] and seen == []
```

`src/marvia/tools/unipass.py`에 더한다:

```python
def facts_carry_containers() -> bool:
    """화물 사실에 컨테이너 번호가 실릴 수 있는가. 지금은 재생 모드만 그렇다 (계획 6a 정정)."""
    # shortcut: 실제 응답(parse_progress)은 컨테이너 칸을 읽지 않는다. 연계가이드에서 API001의 cntrNo를 확인하면 바꾼다
    return Settings().unipass_mode != "live"
```

`src/marvia/graph/identify.py`의 `collect`에서 `known = known_cargo(cargos, watched(config) if watched else [])`를 바꾸고, import를 `from marvia.tools.unipass import facts_carry_containers, lookup_cargo`로 한다:

```python
            # [왜] 실제 모드의 사실에는 컨테이너가 없다. 감시 화물을 다시 조회해도 맞출 수 없으니 읽지 않는다
            watch_numbers = watched(config) if watched and facts_carry_containers() else []
            known = known_cargo(cargos, watch_numbers)
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `770 passed`, 오류 0 (정정 시험 하나 포함).

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/graph/identify.py src/marvia/graph/tools.py src/marvia/graph/main.py rules/unipass.yaml \
  tests/graph/test_identify.py tests/graph/test_agent.py
git commit -m "feat(graph): 컨테이너 번호를 이 대화와 감시 목록의 화물에서 찾고 없으면 정한 글"
```

#### 커밋 4b: feat(graph): 컨테이너에 실린 아는 화물이 여럿이면 선택지로 물음

**Files:**
- Modify: `src/marvia/graph/identify.py`, `src/marvia/identify/models.py`(주석)
- Test: `tests/graph/test_identify.py`, `tests/graph/test_agent.py`

**Interfaces:**
- Produces: 식별 서브그래프 `read → lookup → choose → END`. `choose`는 후보가 있는 첫 화물로 `question`(kind choice, 선택지 "n건 모두 조회" + 한 건씩, `recommended` 0, `alternatives`는 실제 번호 목록)을 만들고 그 컨테이너를 `numbers`에서 뺀다. 후보 토큰은 `mask_map`에 더한다

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_identify.py
+++ b/tests/graph/test_identify.py
@@ -126,3 +126,22 @@
         "retryable": False,
     }
     assert seen == []
+
+
+def test_several_watched_cargos_on_one_container_give_a_choice_with_all_first():
+    out = build_identify_graph(lambda config: ["DEMO0002", "DEMO0003"]).invoke(
+        {"text": "TESU0000013 어디야?"}
+    )
+    question = out["question"]
+    assert [o["label"] for o in question["options"]] == ["[BL1] + [BL2]", "[BL1]", "[BL2]"]
+    assert question["recommended"] == 0
+    assert question["alternatives"] == [["DEMO0002", "DEMO0003"], ["DEMO0002"], ["DEMO0003"]]
+    # [왜] 화면에 보낼 칸(질문, 선택지)에는 토큰만 있다. 실제 번호는 alternatives에만 있다
+    shown = str({key: question[key] for key in ("question", "options")})
+    assert "TESU0000013" not in shown and "DEMO0002" not in shown
+    assert out["numbers"] == []  # 고른 화물만 다시 조회한다
+
+
+def test_a_single_match_asks_nothing():
+    out = build_identify_graph(lambda config: ["DEMO0001"]).invoke({"text": "DEMU1234560 어디야?"})
+    assert out["question"] is None and out["numbers"] == ["DEMU1234560"]
```
```diff
--- a/tests/graph/test_agent.py
+++ b/tests/graph/test_agent.py
@@ -1087,6 +1087,21 @@
     assert (cargo["token"], cargo["kind"], cargo["bl_no"]) == ("[CNTR1]", "container", "DEMO0001")
 
 
+@pytest.mark.parametrize("loop", ["planner", "agent"])
+def test_both_loops_ask_which_cargo_when_a_container_carries_several(agent_deps, loop):
+    watch = watching(lambda user: ["DEMO0002", "DEMO0003"])
+    graph = build_main_graph(agent_deps(model=model(say()), watch=watch), InMemorySaver(), loop=loop)
+    out = graph.invoke({"text": "TESU0000013 어디야?"}, cfg(f"cm-{loop}"))
+    card = out["__interrupt__"][0].value
+    assert card["kind"] == "choice" and [o["label"] for o in card["options"]] == [
+        "[BL1] + [BL2]",
+        "[BL1]",
+        "[BL2]",
+    ]
+    out = graph.invoke(Command(resume={"selected": 1}), cfg(f"cm-{loop}"))
+    assert "DEMO0002: 수입신고 (부산)" in out["answer"] and "DEMO0003" not in out["answer"]
+
+
 def test_lookup_cargo_tool_matches_a_container_token_without_showing_numbers(agent_deps):
     inputs = Inputs()
     watch = watching(lambda user: ["DEMO0001"] if user == "u1" else [])
```

```bash
uv run pytest -q tests/graph/test_identify.py tests/graph/test_agent.py -k "all_first or single_match or carries_several"
```

Expected: 3 failed(`TypeError: 'NoneType' object is not subscriptable`, `KeyError: '__interrupt__'` 둘), 1 passed(`test_a_single_match_asks_nothing`은 지키는 시험이라 지금도 통과한다)

- [ ] **Step 2: 코드**

```diff
--- a/src/marvia/graph/identify.py
+++ b/src/marvia/graph/identify.py
@@ -1,7 +1,7 @@
 """식별 서브그래프: 단서 글 → 번호 읽기·가림 → 조회 → 화물별 결과 (설계 4절).
 
 하지 않는 일: 사용자에게 직접 묻기. 애매하면 question에 담아 끝내고, 묻는 일은 메인 그래프만 한다 (설계 6.3).
-순서도: START → read → (애매하면 END, 아니면 lookup) → END
+순서도: START → read → (애매하면 END, 아니면 lookup) → choose → END
 조회(lookup)는 따로 컴파일한 서브그래프다: assign → 번호마다 Send("one") → collect (설계 4.3, 계획 3d)
 컨테이너 번호는 UNI-PASS로 조회하지 않고 collect가 아는 화물(이 대화, 감시 목록)에서 찾는다 (계획 6a)
 """
@@ -205,6 +205,28 @@
     return graph.compile()
 
 
+def choose(state: IdentifyState) -> dict:
+    """컨테이너에 실린 아는 화물이 여럿이면 어느 화물을 볼지 묻는 선택지를 만든다 (설계 4.1 ②, 6.3)."""
+    many = next((c for c in state.get("cargos", []) if c.get("candidates")), None)
+    if many is None:
+        return {}
+    mask_map = dict(state.get("mask_map", {}))
+    # [왜] 선택지 글에는 토큰만 쓴다. 화면에 보낼 때 view.interrupt_card가 실제 번호로 되돌린다
+    tokens = [token_for(mask_map, number, kind_of(number)) for number in many["candidates"]]
+    question = {
+        "kind": "choice",
+        "question": f"컨테이너 {many['token']}에 실린 화물이 여럿이에요. 어느 화물을 볼까요?",
+        "options": [{"label": " + ".join(tokens), "description": f"{len(tokens)}건 모두 조회"}]
+        + [{"label": token, "description": "이 화물만 조회"} for token in tokens],
+        "recommended": 0,  # [왜] 하나를 짐작하지 않고 모두 보이는 안을 권장한다
+        "alternatives": [many["candidates"]] + [[number] for number in many["candidates"]],
+    }
+    # [왜] 고른 화물을 메인 그래프의 lookup이 조회한다. 컨테이너는 조회할 번호에서 뺀다(두면 후보가 또 나온다)
+    container = mask_map[many["token"]]
+    numbers = [number for number in state.get("numbers", []) if number != container]
+    return {"question": question, "mask_map": mask_map, "numbers": numbers}
+
+
 def _after_read(state: IdentifyState) -> str:
     """갈림길: 물을 것이 있으면 끝내고, 없으면 조회로 간다."""
     return END if state.get("question") else "lookup"
@@ -218,6 +240,8 @@
     graph.add_edge(START, "read")  # 화살표: 시작하면 read
     # 갈림길: read가 끝나면 _after_read가 고른 곳으로 간다. 셋째 인자는 갈 수 있는 곳 목록(그림 그리기용)
     graph.add_conditional_edges("read", _after_read, ["lookup", END])
-    graph.add_edge("lookup", END)
+    graph.add_node("choose", choose)
+    graph.add_edge("lookup", "choose")
+    graph.add_edge("choose", END)
     # [왜] compile은 순서도가 올바른지(끊긴 화살표 등) 검사하고 .invoke()로 돌릴 수 있는 객체를 만든다
     return graph.compile()
```
```diff
--- a/src/marvia/identify/models.py
+++ b/src/marvia/identify/models.py
@@ -51,6 +51,7 @@
     vessel: str | None = None
     source: Literal["text", "photo", "message"] = "text"  # 어떤 단서에서 번호를 얻었나
     confidence: Literal["confirmed", "candidate", "unknown"]  # 확정 / 후보 / 확인 못 함
-    candidates: list[str] = Field(default_factory=list)  # 확정 못 했을 때의 후보 (2차)
+    # 확정 못 했을 때의 후보 실제 번호. 지금은 컨테이너에 실린 아는 화물이 여럿일 때만 채운다 (계획 6a)
+    candidates: list[str] = Field(default_factory=list)
     facts: CargoFacts | None = None  # 조회에 성공하면 채운다
     error: ToolError | None = None  # 조회에 실패하면 채운다
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `774 passed`, 오류 0.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/graph/identify.py src/marvia/identify/models.py tests/graph/test_identify.py tests/graph/test_agent.py
git commit -m "feat(graph): 컨테이너에 실린 아는 화물이 여럿이면 모두 보기를 권장안으로 물음"
```

### Task 5: 확인 숫자가 틀린 컨테이너 모양 번호는 조회 전에 묻기 (C8)

**배울 것:** 확인 숫자가 틀린 컨테이너 모양은 오타일 수도, 같은 모양의 B/L일 수도 있다. 종류는 전처럼 `bl`로 두고(`[BL1]`), 식별의 `read`가 조회할 번호에서 빼고 정한 질문을 만든다. 메인 그래프의 `ask`는 고른 선택지의 `alternatives`를 `numbers`에 더하므로 "B/L 번호로 조회"는 `[[번호]]`, "조회하지 않음"은 `[[]]`이고, 기타 칸에 적은 글은 같은 번호 읽기 규칙으로 읽힌다(고친 컨테이너 번호면 컨테이너 길로 간다). 같은 글에 애매한 덩어리가 함께 있으면 계획 1부터처럼 한 번에 하나만 묻는다.

#### 커밋 5: feat(identify): 확인 숫자가 틀린 컨테이너 모양 번호는 조회 전에 물음

**Files:**
- Modify: `src/marvia/identify/parse.py`, `src/marvia/graph/identify.py`
- Test: `tests/identify/test_parse.py`, `tests/graph/test_identify.py`, `tests/graph/test_main.py`

**Interfaces:**
- Produces: `parse.container_typo(value: str) -> bool`, `read`가 그 번호를 `numbers`에 넣지 않고 `question`(선택지 `[BLn]` "B/L 번호로 조회", "조회하지 않음", `recommended` 0)을 만든다

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/identify/test_parse.py
+++ b/tests/identify/test_parse.py
@@ -1,4 +1,4 @@
-from marvia.identify.parse import check_digit, is_container, read_numbers, read_token
+from marvia.identify.parse import check_digit, container_typo, is_container, read_numbers, read_token
 
 
 def values(text: str) -> list[list[str]]:
@@ -66,3 +66,9 @@
     assert values("컨테이너 DEMU 123456 0, TESU 0000013") == [["DEMU1234560"], ["TESU0000013"]]
     assert values("DEMU 123456-0 도착") == [["DEMU1234560"]]  # 조각 123456-0이 따로 잡히지 않는다
     assert values("ABCU 1234567 같은 글") == []  # 확인 숫자가 틀리면 번호로 보지 않는다(전과 같다)
+
+
+def test_container_typo_is_the_container_shape_with_a_wrong_check_digit():
+    assert container_typo("DEMU1234565")
+    assert not container_typo("DEMU1234560")  # 맞는 컨테이너 번호
+    assert not container_typo("MOCK1234567")  # 넷째 글자가 U·J·Z가 아니면 컨테이너 모양이 아니다
```
```diff
--- a/tests/graph/test_identify.py
+++ b/tests/graph/test_identify.py
@@ -145,3 +145,13 @@
 def test_a_single_match_asks_nothing():
     out = build_identify_graph(lambda config: ["DEMO0001"]).invoke({"text": "DEMU1234560 어디야?"})
     assert out["question"] is None and out["numbers"] == ["DEMU1234560"]
+
+
+def test_a_container_shaped_number_with_a_wrong_check_digit_is_asked_before_any_lookup(monkeypatch):
+    seen = spy(monkeypatch)
+    out = run("DEMU1234565 어디야?")
+    question = out["question"]
+    assert question["question"].startswith("[BL1]은 컨테이너 번호 모양인데 확인 숫자가 맞지 않아요")
+    assert question["alternatives"] == [["DEMU1234565"], []]
+    assert out["masked_text"] == "[BL1] 어디야?" and out["numbers"] == []
+    assert seen == []
```
```diff
--- a/tests/graph/test_main.py
+++ b/tests/graph/test_main.py
@@ -91,6 +91,22 @@
     assert "TEST87654321" not in out["answer"]
 
 
+def test_a_mistyped_container_is_asked_then_read_as_the_user_says(agent_deps):
+    graph = build_main_graph(agent_deps(), InMemorySaver())
+    out = graph.invoke({"text": "DEMU1234565 어디야?"}, cfg("ty1"))
+    assert [o["label"] for o in out["__interrupt__"][0].value["options"]] == ["[BL1]", "조회하지 않음"]
+    out = graph.invoke(Command(resume={"selected": 0}), cfg("ty1"))
+    assert (
+        "DEMU1234565: 조회하지 못했어요 (재생 데이터에 없는 번호입니다, not_found)" in out["answer"]
+    )  # B/L로
+    graph.invoke({"text": "DEMU1234565 어디야?"}, cfg("ty2"))
+    out = graph.invoke(Command(resume={"selected": 1}), cfg("ty2"))
+    assert "DEMU1234565:" not in out["answer"]  # 조회하지 않았다
+    graph.invoke({"text": "DEMU1234565 어디야?"}, cfg("ty3"))
+    out = graph.invoke(Command(resume={"custom": "DEMU1234560"}), cfg("ty3"))  # 고친 번호를 직접 적었다
+    assert "DEMU1234560: 조회하지 못했어요 (UNI-PASS는 컨테이너 번호로 화물을 찾지 못해요." in out["answer"]
+
+
 def test_no_number_guides_user(agent_deps):
     asked = Draft(
         answer="화물을 찾으려면 번호가 필요해요.",
```

```bash
uv run pytest -q tests/identify/test_parse.py tests/graph/test_identify.py tests/graph/test_main.py -k "typo or wrong_check_digit or mistyped"
```

Expected: FAIL. `tests/identify/test_parse.py` 모음 오류 `ImportError: cannot import name 'container_typo' from 'marvia.identify.parse'`. 그 파일을 빼면 2 failed(`TypeError: 'NoneType' object is not subscriptable`, `KeyError: '__interrupt__'`)

- [ ] **Step 2: 코드**

```diff
--- a/src/marvia/identify/parse.py
+++ b/src/marvia/identify/parse.py
@@ -65,6 +65,11 @@
     return bool(_CONTAINER.fullmatch(value)) and check_digit(value) == int(value[-1])
 
 
+def container_typo(value: str) -> bool:
+    """컨테이너 번호 모양인데 확인 숫자가 틀렸나 (오타이거나 같은 모양의 B/L)."""
+    return bool(_CONTAINER.fullmatch(value)) and not is_container(value)
+
+
 def kind_of(value: str) -> Kind:
     """19자리 화물관리번호 형식이면 cargo_no, 확인 숫자가 맞는 컨테이너 번호면 container, 아니면 bl."""
     if _CARGO_NO.fullmatch(value):
```
```diff
--- a/src/marvia/graph/identify.py
+++ b/src/marvia/graph/identify.py
@@ -19,7 +19,7 @@
 from marvia.graph.state import IdentifyState
 from marvia.identify.mask import mask_text, token_for
 from marvia.identify.models import CargoFacts, CargoIdentity, ToolError
-from marvia.identify.parse import kind_of, read_numbers
+from marvia.identify.parse import container_typo, kind_of, read_numbers
 from marvia.tools.rules import load_rules
 from marvia.tools.unipass import lookup_cargo
 
@@ -28,7 +28,7 @@
 
 
 def read(state: IdentifyState) -> dict:
-    """번호를 읽고 가린다. 애매한 덩어리가 있으면 선택지 질문을 만든다."""
+    """번호를 읽고 가린다. 애매한 덩어리나 확인 숫자가 틀린 컨테이너 모양 번호가 있으면 선택지를 만든다."""
     text = state.get("text", "")
     # [왜] 같은 대화(thread)의 앞 차례 표를 이어 쓴다. 차례가 바뀌어도 같은 번호는 같은 토큰이고,
     #      모델이 기록에서 본 [BL1]을 이번 차례에도 조회할 수 있다 (계획 3d)
@@ -50,7 +50,24 @@
                 "alternatives": read_result.alternatives,  # 고른 번호로 실제 번호를 꺼내는 데 쓴다
             }
         else:
-            numbers += [n.value for n in read_result.numbers]
+            for number in read_result.numbers:
+                if not container_typo(number.value):
+                    numbers.append(number.value)
+                    continue
+                # [왜] 오타면 조회하기 전에 묻는다. 같은 모양의 B/L일 수도 있어 B/L 조회를 권장안으로 둔다
+                #      (계획 6a). 화면 글에는 토큰만 쓴다
+                token = token_for(mask_map, number.value, number.kind)
+                question = {
+                    "kind": "choice",
+                    "question": f"{token}은 컨테이너 번호 모양인데 확인 숫자가 맞지 않아요. "
+                    "번호를 확인해 주세요",
+                    "options": [
+                        {"label": token, "description": "B/L 번호로 조회"},
+                        {"label": "조회하지 않음", "description": "고친 번호를 직접 적어 주세요"},
+                    ],
+                    "recommended": 0,
+                    "alternatives": [[number.value], []],
+                }
     # [왜] 바꾼 칸만 돌려준다. LangGraph가 공책의 그 칸들만 덮어쓰고 나머지 칸(text 등)은 그대로 둔다
     return {"masked_text": masked, "mask_map": mask_map, "numbers": numbers, "question": question}
 
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `777 passed`, 오류 0.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/identify/parse.py src/marvia/graph/identify.py tests/identify/test_parse.py \
  tests/graph/test_identify.py tests/graph/test_main.py
git commit -m "feat(identify): 확인 숫자가 틀린 컨테이너 모양 번호는 조회 전에 정한 질문으로 물음"
```

### Task 6: 문서

**Files:**
- Modify: `docs/specs/2026-10-28-marvia-v2-design.md`, 이 계획 문서(결과 표)

- [ ] **Step 1: 설계 문서에 날짜 줄**: 아래 diff대로 4.1·4.2·15절과 변경 기록을 고친다. 커밋한 날이 11-08이 아니면 날짜만 바꾼다.

```diff
--- a/docs/specs/2026-10-28-marvia-v2-design.md
+++ b/docs/specs/2026-10-28-marvia-v2-design.md
@@ -81,17 +81,19 @@
 |---|---|---|---|
 | ① 자동 식별 | 화물관리번호, B/L | UNI-PASS로 조회해 확정 | 1차 |
 | ① 자동 식별 | 서류 사진, 포워더 메시지 | 글에서 번호를 뽑아 위로 넘김 | 1차 |
-| ② 후보 제시 | 선박명·항차, 컨테이너 번호 | 후보를 찾아 좁히고 여럿이면 선택지 | 2차 |
+| ② 후보 제시 | 컨테이너 번호 | 이미 아는 화물(이 대화에서 조회한 화물, 감시 목록)의 컨테이너 번호와 맞춰 하나면 그 화물, 여럿이면 선택지, 없으면 B/L·화물관리번호를 묻는 정한 글. UNI-PASS로는 찾지 않는다 (11-08, 계획 6a) | 1차 |
+| ② 후보 제시 | 선박명·항차 | 후보를 찾아 좁히고 여럿이면 선택지 | 2차 |
 | ③ 안내 | 번호 없음(품목·출발지·예정일) | 필요한 번호와 이유를 설명하고 포워더에게 보낼 문장을 써 줌. 번호를 받아 오면 ①로 | 1차 |
 
 ### 4.2 번호 읽기 (코드가 먼저)
 
 - 화물관리번호: 19자리 = MRN 11 + MSN 4 + HSN 4. 앞 11자리 MRN이 해수부 선박운항정보의 `mrNum`과 같아 배를 특정한다(v1 `backend/app/services/judge/customs.py:13`, 실제 B/L로 확인).
 - B/L: 영문 접두어 + 숫자. 같은 접두어가 반복되면 그 자리에서 나눈다(`HASL0001HASL0002` → 2건).
+- 컨테이너 번호 (11-08, 계획 6a): ISO 6346 모양(소유자 부호 영문 3 + U·J·Z + 숫자 6 + 확인 숫자)에 확인 숫자가 맞을 때만 컨테이너로 읽는다. 띄어 쓴 꼴(`DEMU 123456 0`)도 한 덩어리다. 확인 숫자가 틀린 같은 모양은 전처럼 B/L로 읽되 조회 전에 "확인 숫자가 맞지 않아요"로 묻는다(권장안은 B/L 조회). 화물통관진행정보는 화물관리번호·B/L로만 찾으므로(data.go.kr 15126268) 컨테이너 번호는 어느 모드에서도 UNI-PASS에 보내지 않는다.
 - 정리: 공백·하이픈 제거, 대문자화, OCR 혼동 후보(O/0, I/1)는 원본과 함께 후보로 남긴다.
 - 나누는 방법이 하나뿐이고 형식 검사를 통과하면 진행하고 "두 건(…)으로 읽었어요"와 "다르게 읽기"를 보여 준다. 여럿이거나 실패하면 선택지 interrupt.
 - 서류 사진: OCR(v1 rapidocr 방식 참고) 후 같은 규칙. 메시지: 정규식이 먼저, 정규식이 못 잡은 칸만 LLM 구조화 추출.
-- 번호 가림: LLM에 넘기기 전에 실제 번호를 `[BL1]`, `[CARGO1]` 같은 토큰으로 바꾼다. 실제 값은 state의 `masked_map`에만 둔다.
+- 번호 가림: LLM에 넘기기 전에 실제 번호를 `[BL1]`, `[CARGO1]`, `[CNTR1]` 같은 토큰으로 바꾼다. 실제 값은 state의 `masked_map`에만 둔다.
 
 ### 4.3 출력 형식 `CargoIdentity`
 
@@ -351,7 +353,7 @@
 
 ## 15. 2차로 미룬 것
 
-선박명·컨테이너 번호 식별, 항공·특송, RAG C층(웹 검색과 검토 뒤 코퍼스 추가. 공식 사이트의 법령 이름 조회 `official_lookup`만 11-06에 1차로 당김, 키워드 검색은 법제처 Open API 등록이 필요), 동남아 국가별 규정, 고시 개정 자동 수집과 영향 알림, 푸시·카카오 알림, 보관료 계산, 온라인 평가, Neo4j 한 곳 하이브리드 검색 비교 실험, 평가셋 50건 이상.
+선박명·항차 식별(해수부 키가 새로 필요하고 배와 MRN까지만 준다), 컨테이너 번호로 UNI-PASS에서 화물 찾기(그런 서비스를 공식 문서로 확인한 뒤. 아는 화물 안에서 찾기는 11-08에 1차로 당김), 항공·특송, RAG C층(웹 검색과 검토 뒤 코퍼스 추가. 공식 사이트의 법령 이름 조회 `official_lookup`만 11-06에 1차로 당김, 키워드 검색은 법제처 Open API 등록이 필요), 동남아 국가별 규정, 고시 개정 자동 수집과 영향 알림, 푸시·카카오 알림, 보관료 계산, 온라인 평가, Neo4j 한 곳 하이브리드 검색 비교 실험, 평가셋 50건 이상.
 
 ## 16. 확인이 필요한 것
 
@@ -383,3 +385,4 @@
 - 11-06: 저장 기억·공식 페이지·사진 글은 데이터, 바깥 호스트 허용 목록, 키 비출력 (12절)
 - 11-07: 계획 3b 구현 반영. 별표 읽기, 그래프 확장 자리, GraphRAG 구현 범위, 실제 UNI-PASS 클라이언트, MCP 구현 (5.2, 5.4, 5.5, 7.2, 9). 측정 결과(11절)는 충전 뒤 더한다
 - 11-07: 계획 4b. 원문·답 저장 안 함(8절), 읽기 연결 풀·표 준비 명령·계정 삭제와 감시 끄기(6.3·8절), AG-UI 직접 엔드포인트와 Starlette, 로그인·입력 검사·인스턴스 하나(3절·10절·12절), 승인 편집의 번호 거절과 한국어 이름(10절), 트레이스 가림 문과 남은 단서(11절), 측정 뒤 지시문 변경(11절), 로컬 compose와 배포 워크플로(13절)
+- 11-08: 계획 6a. 컨테이너 번호 식별(확인 숫자, 토큰 `[CNTR1]`, 아는 화물에서 찾기, 오타 질문) (4.1, 4.2, 15절)
```

- [ ] **Step 2: 이 문서 끝에 "실행 결과" 표**: 태스크마다 커밋, 시험 수, 확인점에서 자른 것, C1~C9 판정(통과·못 넘음과 근거)을 적는다.

- [ ] **Step 3: done 체크리스트 증거 줄(저장소 밖 진행 기록)**: 6.1은 컨테이너 부분만 닫고(커밋 범위, C1~C9), 선박명·항차는 2차로 남긴 이유를 적는다.

- [ ] **Step 4: 커밋**

```bash
git add docs/specs/2026-10-28-marvia-v2-design.md docs/plans/2026-11-07-marvia-v2-plan-6a-container.md
git commit -m "docs: 설계에 계획 6a 반영(컨테이너 번호 식별, 아는 화물에서 찾기)"
```

---
## 끝나면 되는 것

- `컨테이너 DEMU1234560 어디쯤이에요?`에 모델은 `[CNTR1]`만 보고, 답의 화물 줄은 그 컨테이너를 실은 아는 화물의 단계(`DEMU1234560: 반입신고 (부산) 2026-10-27`)다.
- 컨테이너 하나에 아는 화물이 여럿이면 선택지 카드가 뜨고(권장안 "모두"), 아무 데도 없으면 B/L·화물관리번호를 묻는 정한 글이 화물 줄에 나온다.
- 컨테이너 번호는 어느 모드에서도 UNI-PASS로 가지 않는다.
- 확인 숫자가 틀린 컨테이너 모양 번호는 조회 전에 한 번 묻는다.
- 계획자·에이전트 두 루프가 같은 결과를 낸다. 에이전트 도구도 같은 화물 줄을 내되, 여럿이면 카드 대신 정한 글(`container_many`)이다. 시험 785개가 키 없이 돈다(실행 결과).

## 설계와 대조

| 설계 | 이 계획 | 차이 |
|---|---|---|
| 4.1 ② 컨테이너 번호 "후보를 찾아 좁히고 여럿이면 선택지", 2차 | 아는 화물 안에서 찾기를 1차로 당김. UNI-PASS로 찾기는 서비스를 확인한 뒤 | T6에서 날짜와 함께 고친다 |
| 4.2 번호 가림 `[BL1]`, `[CARGO1]` | `[CNTR1]`을 더함, 띄어 쓴 꼴 | T6 |
| 4.3 `candidates` "확정 못 했을 때의 후보" | 컨테이너 후보에 쓴다 | 없음 |
| 6.3 선택지 질문 | 컨테이너 후보와 오타 질문도 같은 카드 | 없음 |
| 7.2 UNI-PASS 조회 | 컨테이너 번호는 보내지 않는다 | 없음 |
| 10절 "이렇게 읽었어요" | 종류 "컨테이너 번호" | 없음 |
| 12절 실제 번호는 LLM과 트레이스에 가지 않는다 | 컨테이너도 토큰, 띄어 쓴 꼴까지 가림 | 없음 |
| 15절 "선박명·컨테이너 번호 식별" 2차 | 선박명·항차는 그대로 2차 | T6 |

## 직접 할 일

1. UNI-PASS에 로그인해 "MYC_OpenAPI 연계가이드"를 내려받고 (a) 화물통관진행정보(API001) 응답에 컨테이너 번호 칸(`cntrNo`)이 있는지, (b) 컨테이너 번호를 입력으로 받는 서비스(컨테이너내역, 입항보고내역 등)가 있는지 본다. (a)가 있으면 `parse_progress`가 `containers`를 채우는 작은 계획을, (b)가 있으면 서비스 신청(서비스마다 키)과 실제 경로를 더하는 계획을 쓴다.
2. 실제 화물 하나로 컨테이너 번호 질문을 한 번 돌려 본다(실제 번호와 실제 UNI-PASS 호출이라 직접 하고, 응답은 저장소에 넣지 않는다).
3. 선박명·항차(설계 15절)는 해수부 키를 새로 받을 때 정한다.

## 확인하지 못한 것

- 실제 API001 응답에 컨테이너 번호 칸이 오는지 [미확인]. 그래서 실제 모드에서는 화물 사실에 컨테이너가 없고 컨테이너 질문은 늘 정한 글이다.
- 컨테이너 번호로 화물을 찾는 UNI-PASS 서비스가 있는지 [미확인]. 공식 페이지는 화물관리번호·MBL·HBL만 적었고 연계가이드는 로그인 뒤 내려받는다.
- ISO 모양에 확인 숫자까지 맞는 실제 B/L이 얼마나 있는지 [추정: 드묾]. 있으면 그 B/L은 조회되지 않고 정한 글을 받는다.
- 감시 목록이 길 때 컨테이너 질문 한 번의 조회 수 [추정: 재생 모드에서 이 대화에서 가린 B/L·화물관리번호와 감시 화물 수만큼, 차례로 파일을 읽는다]. 실제 모드는 0번이다(C10).
- 컨테이너 맞추기는 실제 응답 칸(`cntrNo`)을 확인하기 전까지 재생 데이터에서만 된다. 실제 모드에서는 컨테이너 질문이 늘 정한 글이다.
- 확인 숫자가 틀린 띄어 쓴 꼴(`DEMU 123456 5`)은 전처럼 가리지 않고 LLM에 간다 [실측 11-07: `ABCU 1234567` 시험과 같은 갈래].
- 소유자 부호가 다른 컨테이너 둘을 붙여 쓴 꼴(`DEMU1234560TESU0000013`, 22자)은 전처럼 반으로 나누는 선택지를 거친 뒤 컨테이너 길로 간다 [추정, 시험 없음].
- 같은 글에 애매한 덩어리가 둘이거나, 애매한 덩어리와 여럿인 컨테이너가 함께 있으면 한 번에 하나만 묻는다(계획 1부터의 한계). 오타 번호는 여럿이어도 한 질문으로 묻고, 다른 질문이 있으면 권장안대로 B/L로 조회한다(40353f4).
- 공백 두 칸·탭·NBSP로 띄어 쓴 컨테이너 번호는 가리지 않고 트레이스에서도 지우지 않는다 [실측 11-07]. 띄어 쓴 꼴은 공백 한 칸과 하이픈만 받는다.
- 에이전트 길에서는 모델이 사용자가 카드에서 고른 답을 보지 못한다. "조회하지 않음"을 고른 번호를 모델이 `lookup_cargo`로 조회할 수 있고, 컨테이너 카드에서 화물을 고른 뒤 컨테이너 토큰을 조회하면 `container_many` 줄이 더 붙는다 [구조는 시험으로 확인, 실제 모델이 그렇게 하는 빈도는 측정하지 않음]. 번호는 드러나지 않는다. 고치려면 측정한 에이전트 지시문을 바꿔야 해서 다음 유료 측정 때 함께 정한다.
- 번호를 겹치지 않게 거르지 않는다. 같은 번호를 두 번 적거나, B/L과 그 B/L이 실린 여럿 컨테이너를 함께 적고 "모두"를 고르면 같은 화물 줄이 두 번 나온다(원인은 6a 전부터 있었다).
- 컨테이너 카드가 떠 있는 동안 화물 카드에는 `container_many` 글이 함께 보인다. 화면은 눈으로 보지 않았다.
- 화면은 눈으로 보지 않았다. 서버 허용 목록 시험만 있다(Playwright를 더하지 않은 이유는 결정과 근거).
- 실제 모델로 컨테이너 질문 한 차례(충전 전).

## 실행 결과 (11-07)

하루(11-07)에 끝나 확인점에서 자른 것은 없다. 유료 모델 호출과 실제 UNI-PASS 호출은 없었다($0). 시험 수는 커밋마다 `uv run pytest -q`를 저장소에서 돌린 값이다 [실측 11-07, 건너뜀 0].

| 태스크 | 커밋 | 시험 |
|---|---|---|
| T0 사전 등록, C10 정정 | 5358894, 30396b0 | 749 |
| T1a 종류·토큰·보내지 않기 | 05471cd | 757 |
| T1b 띄어 쓴 꼴 | f53795a | 760 |
| T1 고침: 띄어 쓴 컨테이너에 하이픈으로 붙은 번호도 가림 | a750a66 | 762 |
| T2 재생 fixture | fcab521 | 763 |
| T3 감시 목록 읽기 | 2ecad71 | 764 |
| T4a 아는 화물에서 찾기, C10 | 68eb48f | 772 |
| T4b 여럿이면 선택지 | 962756d | 776 |
| T5 오타 질문 | a05552f | 779 |
| T5 고침: 오타 번호가 여럿이거나 다른 질문과 겹쳐도 말없이 빠지지 않음 | 40353f4 | 782 |
| T6 설계 문서 | 4ff43e6 | 782 |
| 마무리 고침: 컨테이너를 이 대화의 앞 차례 화물에서도 찾음(재생 모드만) | 4a94217 | 785 |

계획보다 시험이 많은 것은 고침 세 커밋이 시험을 더했기 때문이다(2, 3, 3개).

| # | 판정 | 근거 |
|---|---|---|
| C1 | 통과 | `check_digit("CSQU305438") == 3`과 가공 번호 시험, fixture 시험. 따로 만든 ISO 6346 표와 무작위 번호 2만 개로 맞춰 어긋남 0 [실측 11-07] |
| C2 | 통과 | `[CNTR1]` 가림, 붙여 쓴 둘, 띄어 쓴·하이픈 꼴 한 덩어리, `ABCU 1234567` 그대로, B01 꼴 선택지 그대로, "이렇게 읽었어요"의 "컨테이너 번호" |
| C3 | 통과 | 실제 모드에 키가 있어도 HTTP를 열지 않음, 식별·조회 서브그래프 `spy` 시험, `watch_cargo`가 `[CNTR1]`을 받지 않음 |
| C4 | 통과 | `trace.scrub` 시험 넷(붙여 쓴·띄어 쓴·하이픈으로 붙은 번호 포함), 도구 길 모델 입력에 실제 번호 0개. 공백 두 칸·탭·NBSP 꼴은 가리지 않는다(확인하지 못한 것) |
| C5 | 통과 | 하나·같은 글의 B/L·여럿(권장안 "모두")·없음(조회 0번) 시험 |
| C6 | 통과 | 두 루프 시험이 같은 화물 줄과 선택지 카드를 냄. 4a94217에서 앞 차례 화물 시험을 두 루프로 더함 |
| C7 | 통과 | 도구 길 `[CNTR1]: 반입신고 (부산) 2026-10-27` |
| C8 | 통과 | 조회 0번에 정한 질문, 선택 0·1·직접 입력 세 길 |
| C9 | 통과 | 749 → 785, 건너뜀 0, `set_v2` sha 시험 통과, 커밋당 코드 파일 최대 13개(05471cd) |
| C10 | 통과 | 실제 모드에서 감시 목록 읽기 0번·조회 0번, 이 대화의 번호도 다시 조회하지 않음(4a94217 시험) |

### 마무리 고침 (11-07, 전체 검토 뒤)

| 찾은 것 | 처리 |
|---|---|
| "이 대화에서 조회한 화물"이 실제로는 바로 앞 차례 조회 결과뿐이었다. 번호 없는 차례를 한 번 거치면 그 뒤 컨테이너 질문이 `container_unknown`이었다(두 루프) | 4a94217: 이 대화에서 가린 B/L·화물관리번호도 다시 조회해 맞춘다. 재생 모드에서만 하고 실제 모드는 0번(C10) |
| 에이전트 길에서 모델이 카드 답을 보지 못한다 | 한계로 적음(확인하지 못한 것, 설계 4.2). 지시문 변경은 다음 유료 측정 때 |
| 설계 4.2의 "말없이 빠지는 번호는 없다"가 애매한 덩어리 둘의 경우까지 말했다 | 설계 문장을 오타 번호에 한정하고 계획 1의 한계를 함께 적음 |
