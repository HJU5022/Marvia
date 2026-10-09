# Spec: 자연어 입력 하나로 조회 (검색 폼 대체, 입항 선박 검색)

사용자 지시: "내 화물" 화면의 검색 조건(B/L, 구분, 판매 예정일, 예시 메뉴)을 지우고 LLM 자연어로만 처리한다. "네덜란드에서 한국으로 들어오는 배 뭐야?" 같은 질문도 받는다.

## Why

- 칸을 채우는 폼은 B/L 하나 조회만 된다. 사용자는 말로 묻고 싶어 하고, 배 단위 질문("중국에서 오는 배")은 폼으로는 아예 못 한다
- docs/specs/memory.md(G4)의 채팅 입구와 방향이 같다. 이 Spec은 기억(메모장·화물 표) 없이 입구와 라우팅, 입항 선박 검색만 다룬다

## Goal

- 입력창 하나. 문장을 보내면 코드가 B/L을 가리고 LLM이 의도를 고른다. 실행은 코드가 한다
- 의도 4가지: 화물 조회(cargo), 지금 화물 후속 질문(follow_up), 부산 입항 예정 선박 검색(vessel_search), 그 밖(other: 짧은 안내)
- 선박 검색은 해수부 선박운항정보의 직전 기항지(previous_port) 기준이다. 출발지 데이터는 없다고 답에 밝힌다
- **Out of Scope**: 대화 기억, 여러 화물 비교, 웹 검색, 출발지(최초 적재항) 기준 검색, 답 문장 스트리밍 (처리 단계 소식은 docs/specs/chat-progress.md)

## What

**Happy Path**
1. 화면이 POST /api/chat {message, session_id, context(지금 보고 있는 화물: bl_no·bl_type·sale_due_date, 없으면 null)}
2. 코드: 문장 속 B/L 모양(영문·숫자 8~20자, 숫자 포함)을 [BL1]처럼 바꾼다. LLM은 가린 문장과 has_current_cargo만 본다 (CLAUDE.md B/L 비노출)
3. LLM(marvia-chat-route): intent, bl_ref, bl_type, sale_due_date, question, place, days, reply
4. 코드 실행
   - cargo: bl_ref를 원래 B/L로 되돌려 기존 /api/agent 흐름(run_agent). 구분을 말하지 않으면 HOUSE로 조회하고 답에 알린다
   - follow_up: context의 화물로 run_agent(follow_up_question=가린 문장)
   - vessel_search: 해수부 입항 예정(오늘부터 days일, 기본 7, 최대 14)을 받아 직전 기항지 목록을 만든다. LLM(marvia-port-match)이 place에 해당하는 항구를 이 목록 안에서만 고른다. 코드가 걸러 표로 돌려준다
   - other: reply를 그대로 (짧은 안내, 판정·숫자 없음)
5. 응답 ChatResponse: kind(cargo / vessels / message), reply, agent(AgentResponse), request(AgentRequest), vessels, place, ports

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | LLM 없음·실패 (키 없는 데모, 과부하) | 규칙 대신: 문장에 B/L이 있으면 cargo, 없으면 "B/L 번호를 넣어 주세요" |
| EC-02 | cargo인데 B/L 없음 | 지금 화물이 있으면 그 화물, 없으면 B/L을 물어본다 |
| EC-03 | follow_up인데 지금 화물 없음 | B/L을 먼저 알려 달라고 답한다 |
| EC-04 | 선박 검색에서 맞는 항구 없음 (예: 네덜란드) | 빈 표 + "직전 기항지 기준이라 유럽에서 출발한 배도 중국·싱가포르를 거쳐 오면 그 항구로 나온다" 안내 |
| EC-05 | 해수부 실패 | 503이 아니라 message로 실패를 알린다 |
| EC-06 | 문장 속 지시문 ("이전 지시 무시") | 데이터로만 넘긴다. 의도는 4개로 고정, 실행은 코드 |
| EC-07 | 문장 500자 초과 | 400 |

## How

- 프롬프트 2개(backend/app/prompts/marvia-chat-route.md, marvia-port-match.md), llm.route_chat / llm.match_ports. Skill 문서는 넣지 않는다
- services/chat/chat.py: 가리기, 라우팅, 실행, 해수부 결과 10분 캐시(같은 기간을 여러 번 묻는 경우)
- routers/chat.py: POST /api/chat. 로그인·정지 확인은 auth.current_user 그대로
- LLM 출력에서 코드가 덮어쓰는 것: bl_ref는 가린 목록에 있는 것만, ports는 주어진 목록 안의 것만, days는 1~14로 자른다
- 화면: TopBar 폼을 입력창 하나로 바꾸고 예시 문장 칩, 서류 사진 버튼은 남긴다(B/L을 문장에 넣어 준다). 결과는 kind별로 기존 카드 / 선박 표 / 안내 문장
- 테스트: backend/tests/integration/test_chat.py (가리기, 라우팅별 실행, 폴백, 덮어쓰기, 항구 필터)

**추가**: 입항 예정 목록은 공개 정보이고 데모 B/L 3건과 무관하므로, DATA_GO_KR_KEY가 있으면 REPLAY_MODE에서도 선박 검색만 실제 해수부를 부른다. 키가 없으면 녹화본. 답에는 사용자가 쓴 지역 이름(place_label)을 쓴다

## 추가: 선박 자세히 보기

선박 표에서 선명을 누르면 GET /api/vessels/detail?call_sign=&ship_name= 로 한 척을 자세히 본다. 새 데이터 소스 없이 기존 MCP 도구 넷을 묶는다(services/watch/vessel_detail.py).
- 해수부 get_port_schedule: 입항 예정·실적, 접안 시설, 관제 이벤트 (호출부호 우선)
- ShipFinder get_vessel_candidates → get_live_position: MMSI, 국적, 실시간 위치·속력·AIS 목적지·AIS ETA·마지막 수신
- searoute estimate_distance: 부산까지 남은 바닷길, 지금 속력이면 걸리는 시간(계산 도착)
- 위치 신선도는 rules.md position_stale_hours로 코드가 정한다. 판정은 하지 않는다
- 도구 하나가 실패해도 나머지를 보여 주고 errors에 출처별로 남긴다. ShipFinder 한도 때문에 같은 배는 10분 캐시

## 구현 상태

처음 설계(의도 4개 분류 후 코드 실행)는 두 번 넓어졌다. 아래가 지금 코드(`backend/app/services/chat/chat.py`, `routers/chat.py`)다.

- **채팅 에이전트**: 의도 4개에 안 맞는 실무 질문이 모두 고정 안내로 가고 앞 대화를 몰라 "이건"을 못 알아듣던 문제를 고치려고, 기본 경로가 에이전트로 바뀌었다. LLM(프롬프트 marvia-chat-agent)이 도구를 골라 부르고 코드가 실행한다. 도구는 `check_cargo`(화물 조회), `ask_cargo`(화면의 화물 후속 질문), `search_arrivals`(부산 입항 선박 검색), `set_watch`(지켜보기 켜고 끄기), `send_kakao`(지금 상태를 카카오톡으로), 읽기 전용 MCP 도구 4종, 이다. 처음에 있던 좁은 범위의 `web_search`는 없앴다 (docs/adr/0020). 등급·여유 일수는 여전히 판정 흐름(코드)이 정한다. 화면은 최근 대화(history)도 함께 보낸다
- **처음 설계의 4개 의도 분류는 대비 경로로 남았다**: 에이전트를 못 쓰면(키 없음, 도구를 거절하는 모델, `CHAT_AGENT=off`) `_classic`이 의도 고르기(`llm.route_chat`)와 실행을 맡는다. 그것도 안 되면 규칙(EC-01)이다
- **LLM에 가는 것**: B/L은 [BL1]로, MRN은 [MRN]으로, 컨테이너 번호는 [CNTR1]로 가린다. 컨테이너 번호가 로그인 사용자의 화물 표에 있으면 코드가 원본 B/L로 바꿔 조회한다. 주입 모양 문장(`guard`)은 LLM에 보내지 않는다
- **범위 밖 주제**: 항공·육상, 창고 수령일, 일정 변경, 날씨, 품목 요건은 LLM 없이 고정 문장과 공식 창구로 답한다 (`skills/referrals/rules.md`, docs/specs/referral-guide.md). 세액·관세율·통관 가능 여부는 관세사 안내 고정 문장(`BROKER_ONLY`)이다
- **응답**: `ChatResponse.kind`는 `cargo` / `vessels` / `message`이고, `map`(지도), `cargos`(B/L 2~3개 문장의 줄), `watch_offer`, `watch_set`이 더해졌다
- **대화 저장**: 로그인 사용자의 대화는 답을 만든 뒤 뒤에서 저장한다 (conversations 표, docs/ERD.md). 기억 쓰기와 지난 조회 한 줄은 docs/specs/memory.md
- **화면**: 입력창은 하나. 서류 사진 버튼과 예시 문장 칩이 있다 (`web/components/ChatBar.tsx`, `AskPanel.tsx`). 입력 한도는 500자
- 선박 자세히 보기 `GET /api/vessels/detail`은 그대로 있다 (`services/watch/vessel_detail.py`)
- 테스트: `backend/tests/integration/test_chat.py`, `test_chat_agent.py`, `test_chat_multi_bl.py`, `test_chat_watch.py`, `test_chat_kakao_now.py`, `test_chat_map.py` 등
