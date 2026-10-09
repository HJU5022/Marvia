# Spec: 자연어 입력 하나로 조회 (채팅 에이전트, 입항 선박 검색)

관련 ADR: [0016 채팅 에이전트와 가드](../adr/0016-chat-agent-with-tools-and-guard.md), [0020 웹 검색 제거](../adr/0020-remove-web-search-use-skill.md), [0005 B/L 가리기](../adr/0005-bl-masking-not-to-llm.md)

## 요약

- 화면의 입력창은 하나다. 사용자는 B/L 조회, 지금 화물에 대한 질문, "중국에서 오는 배 뭐야?" 같은 배 단위 질문을 모두 문장으로 보낸다.
- **기본 경로는 채팅 에이전트다.** LLM(프롬프트 `marvia-chat-agent`)이 도구 7개와 읽기 전용 MCP 도구 중에서 골라 부르고, 실행은 코드가 한다. 등급과 여유 일수는 지금처럼 판정 흐름(코드)이 정한다.
- **대비 경로는 의도 4가지 분류다.** 에이전트를 쓸 수 없으면 `_classic`이 의도를 하나 고르고(`marvia-chat-route`) 코드가 실행한다. 그것도 안 되면 규칙으로 답한다.
- 웹 검색 도구는 없다 ([ADR 0020](../adr/0020-remove-web-search-use-skill.md)).

코드: `backend/app/services/chat/chat.py`(처리), `backend/app/services/chat/tools.py`(도구 정의), `backend/app/routers/chat.py`(API).

## 왜

칸을 채우는 폼으로는 B/L 하나만 조회할 수 있고 배 단위 질문은 아예 못 한다. 의도 4가지 분류만으로는 거기 안 맞는 실무 질문이 모두 고정 안내로 가고, 앞 대화를 몰라 "이건"을 못 알아들었다. 그래서 도구를 고르는 에이전트를 기본으로 두었다. 결정의 맥락은 [ADR 0016](../adr/0016-chat-agent-with-tools-and-guard.md)에 있다.

## API

| 엔드포인트 | 하는 일 |
|---|---|
| `POST /api/chat` | 문장 하나를 처리하고 `ChatResponse`를 돌려준다 |
| `POST /api/chat/stream` | 같은 일을 하면서 처리 단계를 SSE로 보낸다 ([chat-progress.md](chat-progress.md)) |
| `GET /api/vessels/detail` | 선박 표의 한 척을 자세히 본다 (아래 "선박 자세히 보기") |

**요청 `ChatRequest`** (`routers/chat.py`)

| 칸 | 뜻 |
|---|---|
| `message` | 사용자 문장. 500자 상한 (`services/chat/limits.py` `MESSAGE_MAX`) |
| `session_id` | 세션 id |
| `context` | 지금 보고 있는 화물 (없으면 null) |
| `document` | 서류 사진에서 사용자가 확인한 출항일 (선택) |
| `history` | 최근 대화. 서버는 마지막 6줄만 LLM에 넘긴다 (`limits.py` `HISTORY_TURNS`) |
| `on_screen` | 화면에 떠 있는 배 (선택) |

**응답 `ChatResponse`** (`routers/chat.py`)

| 칸 | 뜻 |
|---|---|
| `kind` | `cargo` / `vessels` / `message` |
| `reply` | 답 문장 |
| `agent`, `request` | 화물 조회 결과(`AgentResponse`)와 그 요청 |
| `vessels`, `place`, `ports`, `days` | 입항 선박 검색 결과 |
| `map` | 지도 카드 |
| `cargos` | 문장에 B/L이 2~3개일 때 화물별 결과 |
| `watch_offer`, `watch_set`, `watch_vessel_set` | 지켜보기 제안, 화물 지켜보기 켜고 끄기, 배 한 척 감시 결과 |
| `evidence_items`, `citations` | 답 문장 속 근거 표시 |

## 처리 순서

`_route`가 아래 순서로 본다. 앞 단계에서 답이 정해지면 뒤로 가지 않는다.

1. **가리기 (코드)**: B/L은 `[BL1]`, MRN은 `[MRN]`, 컨테이너 번호는 `[CNTR1]`로 바꾼다 (`services/chat/ids.py`). 컨테이너 번호가 로그인 사용자의 화물 표에 있으면 코드가 원본 B/L로 바꿔 조회한다. 화물 표에 없어도 세관에 같은 번호의 B/L이 있으면 B/L로 조회한다 (`services/chat/chat.py` `_swap_containers`). 못 찾은 컨테이너 번호만 있고 B/L이 없으면 LLM 없이 코드 문장(`CONTAINER_NOT_FOUND`, 로그인 전이면 `CONTAINER_NEED_LOGIN`)으로 답한다. LLM은 원본 번호를 보지 않는다.
2. **세액·통관 가부 (코드)**: B/L이 없는 문장에 관세·세금·세율·"통관 될까" 같은 말이 있으면(`services/chat/patterns.py` `BROKER_TOPIC`) LLM 없이 관세사 고정 안내(`BROKER_ONLY`)로 답한다.
3. **주입 모양 문장 (코드)**: `services/judge/guard.py`가 잡으면 LLM에 보내지 않고 고정 답(`INJECTION_REPLY`)을 낸다.
4. **범위 밖 주제 (코드)**: B/L이 없는 문장이 항공·육상, 창고 수령일, 일정 변경, 날씨, 품목 요건이면 LLM 없이 고정 문장으로 답한다 ([referral-guide.md](referral-guide.md)).
5. **채팅 에이전트 (LLM이 도구를 고르고 코드가 실행)**: 아래 "도구" 표.
6. **대비 경로**: 에이전트가 첫 도구를 쓰기 전에 실패하면 `_classic`으로 간다 (아래 "대비 경로").

## 도구

에이전트가 받는 도구는 `AGENT_TOOLS` 7개와 MCP 읽기 전용 도구다 (`chat.py` `tools = AGENT_TOOLS + mcp_tools`).

| 도구 | 하는 일 | 자세히 |
|---|---|---|
| `check_cargo` | B/L 하나를 조회하고 판정한다. 한 문장에 한 번 | 판정 흐름 `routers/agent.py` |
| `ask_cargo` | 화면의 화물 결과로 후속 질문에 답한다 | |
| `search_arrivals` | 부산 입항 예정 선박을 직전 기항지로 거른다 | 아래 "입항 선박 검색" |
| `set_watch` | 화면의 화물 지켜보기를 켜고 끈다 | [cargo-watch.md](cargo-watch.md) |
| `watch_vessel` | 배 한 척을 감시 목록에 넣고 뺀다 | [cargo-watch.md](cargo-watch.md) |
| `send_kakao` | 화면의 화물의 지금 상태를 사용자 카카오톡으로 보낸다 | `routers/chat.py` `_kakao_hooks`, `services/watch/kakao.py` |
| `recall_memo` | 메모장에 저장한 거래처·메모를 읽는다 (읽기 전용) | [memory.md](memory.md) |
| MCP 도구 4개 | `get_vessel_candidates`, `get_live_position`, `get_port_schedule`, `estimate_distance` | `mcp_server/README.md` |

- 언제 어떤 도구를 쓰는지의 규칙은 프롬프트 `marvia-chat-agent`에 있다.
- 지켜보기·카카오톡 도구는 사용자가 분명히 요청했을 때만 코드가 실행하고, 아니면 코드가 거절 문장을 쓴다.
- 화면 화물의 배를 위치·거리 도구로 따로 찾으면 코드가 `ask_cargo`로 돌려보낸다. 그 배의 위치는 화물 조회 결과가 이미 갖고 있다.

## 입항 선박 검색

- 해수부 선박운항정보의 **직전 기항지**(previous_port) 기준이다. 출발지(최초 적재항) 데이터는 없다고 답에 밝힌다.
- 기간은 오늘부터 `days`일이다. 기본 7, 최대 14 (`chat.py` `DAYS_DEFAULT`, `DAYS_MAX`).
- 항구 고르기만 LLM(`marvia-port-match`)이 하고, 받은 직전 기항지 목록 안에서만 고른다. 거르기와 표 만들기는 코드가 한다.
- 지명이 부산·한국처럼 도착지 자체면 거르지 않고 전체를 보인다.
- 해수부 결과는 10분 캐시한다 (`CACHE_SEC`).
- 입항 예정 목록은 공개 정보라 `DATA_GO_KR_KEY`가 있으면 `REPLAY_MODE`에서도 실제 해수부를 부른다. 키가 없으면 녹화본을 읽는다.
- 답에는 사용자가 쓴 지역 이름(`place_label`)을 쓴다. 사용자 문장에 실제로 있는 글자일 때만 쓴다.

## LLM 출력에서 코드가 다시 보는 것

| 칸 | 코드 처리 |
|---|---|
| `bl_ref` | 가린 목록에 있는 번호표만 받는다 |
| `ports` | 주어진 직전 기항지 목록 안의 것만 받는다 |
| `days` | 1~14로 자른다 |
| `place` | 영문 지명 모양, 네 낱말 이하, 주입 모양이 아닐 때만 쓴다 |

## 대비 경로 (의도 4가지 분류)

에이전트를 쓸 수 없을 때(키 없음, 도구를 붙이면 거절하는 모델·제공사, `CHAT_AGENT=off`) `_classic`이 맡는다. `CHAT_AGENT`는 기본이 켜짐이다 (`chat.py` `agent_enabled`).

1. LLM(`marvia-chat-route`)이 가린 문장과 `has_current_cargo`만 보고 `intent`와 칸(`bl_ref`, `bl_type`, `sale_due_date`, `question`, `place`, `days`, `reply`)을 낸다.
2. 코드가 의도별로 실행한다.

| 의도 | 실행 |
|---|---|
| `cargo` | `bl_ref`를 원래 B/L로 되돌려 판정 흐름(`run_agent`)을 부른다. 구분을 말하지 않으면 HOUSE로 조회하고 답에 알린다 |
| `follow_up` | `context`의 화물로 판정 흐름의 후속 질문을 부른다 |
| `vessel_search` | 위 "입항 선박 검색"과 같다 |
| `other` | `reply`를 짧은 안내로 돌려준다. 판정과 숫자는 넣지 않는다 |

문장에 지금 화물과 다른 B/L이 있으면 LLM이 고른 의도와 상관없이 새 화물 조회로 바꾼다.

## 예외

| # | 상황 | 처리 |
|---|---|---|
| EC-01 | LLM 없음·실패 (키 없음, 과부하) | 규칙으로 답한다. 문장에 B/L이 있으면 조회, 없으면 B/L을 넣어 달라고 답한다 |
| EC-02 | 화물 조회인데 B/L 없음 | 지금 화물이 있으면 그 화물, 없으면 B/L을 물어본다 |
| EC-03 | 후속 질문인데 지금 화물 없음 | B/L을 먼저 알려 달라고 답한다 |
| EC-04 | 선박 검색에서 맞는 항구 없음 (예: 네덜란드) | 빈 표와 함께 "직전 기항지 기준이라 유럽에서 출발한 배도 중국·싱가포르를 거쳐 오면 그 항구로 나온다"고 안내한다 |
| EC-05 | 해수부 실패 | 503 대신 message로 실패를 알린다 |
| EC-06 | 문장 속 지시문 ("이전 지시 무시") | 주입 모양이면 LLM에 보내지 않는다. 그 밖의 문장도 데이터로만 넘기고 실행은 코드가 한다 |
| EC-07 | 문장 500자 초과 / 빈 문장 | 422 (요청 본문 검사, `routers/chat.py` `ChatRequest`) / 400 `BAD_MESSAGE` (`backend/tests/integration/test_chat.py`) |

## 대화 저장과 화면

- 로그인 사용자의 대화는 답을 만든 뒤 뒤에서 저장한다 (`conversations` 표, [ERD.md](../ERD.md)). 기억 쓰기와 지난 조회 한 줄은 [memory.md](memory.md)에 있다.
- 화면은 입력창 하나와 예시 문장, 서류 첨부 버튼을 둔다 (`web/components/ChatBar.tsx`). 첨부한 서류에서는 B/L과 MRN만 코드로 읽어 조회한다 ([document-extract.md](document-extract.md)).

## 선박 자세히 보기

선박 표에서 선명을 누르면 `GET /api/vessels/detail?call_sign=&ship_name=`로 한 척을 자세히 본다. 새 데이터 소스 없이 MCP 도구 4개를 묶는다 (`backend/app/services/watch/vessel_detail.py`).

| 출처 | 도구 | 보여 주는 것 |
|---|---|---|
| 해수부 | `get_port_schedule` | 입항 예정·실적, 접안 시설, 관제 이벤트 (호출부호 우선) |
| ShipFinder | `get_vessel_candidates` -> `get_live_position` | MMSI, 국적, 실시간 위치·속력, AIS 목적지·ETA, 마지막 수신 |
| searoute | `estimate_distance` | 부산까지 남은 바닷길, 지금 속력이면 걸리는 시간 |

- 위치가 오래됐는지는 `skills/ais-reliability/rules.md`의 `position_stale_hours`로 코드가 정한다. 판정은 하지 않는다.
- 도구 하나가 실패해도 나머지를 보여 주고 `errors`에 출처별로 남긴다.
- ShipFinder 호출 한도 때문에 같은 배는 10분 캐시한다.

## 테스트

`backend/tests/integration/`의 `test_chat*.py`. 대표 파일:

| 파일 | 확인하는 것 |
|---|---|
| `test_chat.py` | 가리기, 의도별 실행, 규칙 대비, 덮어쓰기, 항구 거르기 |
| `test_chat_agent.py` | 에이전트 도구 고르기와 실행 |
| `test_chat_guard_a3.py` | 세액 주제 고정 안내, B/L이 있는 문장은 가로채지 않음 |
