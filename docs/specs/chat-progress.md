# Spec: 답을 기다리는 동안 실제 처리 단계 보여 주기 (SSE)

사용자 결정: 화면 타이머로 꾸민 3단계 표시를 서버의 실제 단계 소식으로 바꾼다.

## Why

- 화물 조회는 통관 조회, 선박 식별, 위치 조회, LLM 판정과 검증을 거쳐 5~30초 걸린다 (EVAL p95 기록). 그동안 화면은 서버가 무엇을 하는지 모른다
- 기존 화면(작업 리스트 E3 "로딩 상태 3단계")은 0.35초, 0.7초 타이머로 단계를 넘긴다. 실제 진행과 무관한 "완료" 표시다
- 프로젝트 가이드 8-3 사용성 "즉각 피드백: 처리 중임을 사용자가 알 수 있는가 (로딩·진행률·스트리밍)", 4-1-1 "체감 지연 개선 (축 ③) → 특강 스트리밍 응답 처리"
- 특강 스트리밍 응답 처리: 스트리밍이 바꾸는 것은 총 시간이 아니라 기다리는 동안 무엇을 보는가. 단, 출력 계약으로 전체를 검증한 뒤에야 보여 줄 응답은 흘려보내지 않는다 (레벨 3)

## Goal

- 서버가 실제로 다음 단계에 들어갈 때 화면에 알린다. 화면은 받은 단계만 표시한다. 단계를 지어내거나 퍼센트를 만들지 않는다
- 최종 응답은 지금과 같은 ChatResponse 하나. 검증(V1~V10)을 통과한 뒤에만 나간다
- 기존 POST /api/chat, POST /api/agent, 평가 실행기, 판정 결과는 바뀌지 않는다
- **Out of Scope**: 판정 문장·후속 답 글자 단위 스트리밍(검증 전 문장이 나가면 안 된다), 퍼센트 진행률, 남은 시간 예측, 서류 사진(POST /api/document)·선박 자세히 보기 스트리밍, WebSocket

## What

**Happy Path**
1. 화면이 POST /api/chat/stream (본문은 /api/chat과 같다: message, session_id, context)
2. 로그인 확인(auth.current_user_id)은 응답을 열기 전에 끝난다. 실패하면 보통 401·403 응답
3. 서버가 처리하면서 단계마다 `event: progress` / `data: {"stage": "..."}` 를 보낸다
4. 끝나면 `event: result` / `data: <ChatResponse JSON>` 하나. 화면은 /api/chat 응답과 똑같이 처리한다
5. 화면은 다음 단계가 오면 앞 단계에 완료 표시를 하고, 지금 단계는 진행 중으로 보인다. 경과 시간(브라우저가 잰 값)을 같이 보인다

**단계 이름** (services/chat/progress.py STAGES, 화면 라벨은 web/lib/progress.ts)

| stage | 실제 지점 | 화면 라벨 |
|---|---|---|
| understand | services/chat/chat._route, 에이전트(또는 대비 경로 route_chat) LLM 직전 | 질문 이해 |
| customs | routers/agent._assess, UNI-PASS 조회 직전 | 통관 정보 조회 |
| identify | routers/agent._identify 직전 | 선박 식별 |
| position | ShipFinder 위치·해수부 일정·searoute 거리 조회 직전 | 위치·입항 일정 확인 |
| judge | LLM 판정과 검증 반복 직전 | 판정 정리와 검증 |
| answer | routers/agent._follow_up, 후속 답 LLM 직전 | 답변 작성과 검증 |
| schedule | services/chat/chat.search_vessels, 해수부 입항 예정 조회 직전 | 부산 입항 예정 조회 |
| ports | 지역에 맞는 항구 고르기(match_ports) 직전 | 지역 항구 찾기 |
| tool_candidates | 채팅 에이전트가 선박 후보 검색(get_vessel_candidates)을 고른 때 | 선박 후보 찾기 |
| tool_position | 에이전트가 실시간 위치(get_live_position)를 고른 때 | 선박 실시간 위치 조회 |
| tool_schedule | 에이전트가 부산 입항 기록(get_port_schedule)을 고른 때 | 부산 입항 기록 조회 |
| tool_distance | 에이전트가 남은 항로 거리(estimate_distance)를 고른 때 | 남은 항로 거리 계산 |
| memory | 기억 뽑기가 저장할 내용을 찾았을 때만. 답 만들기와 같이 돌아 다른 단계와 겹칠 수 있다 (실사용 76) | 메모 저장 중 |

경로마다 지나간 단계만 나온다. 예: 정상 조회 understand → customs → identify → position → judge, 되묻기 understand → customs → identify, 부산 외 understand → customs.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 화면 연결이 끊김 | 서버 처리는 끝까지 간다(/api/chat과 같다). 소식 전달 실패는 판정을 멈추지 않는다 |
| EC-02 | 처리 중 예외 | 응답이 이미 열려 500을 줄 수 없다. `event: error` {status: 500, detail: 고정 문구}. 예외 메시지는 보내지도 남기지도 않는다(B/L 섞임 방지, SDD 3.5) |
| EC-03 | 빈 문장 | `event: error` {status: 400}. 500자 초과는 본문 검사에서 422 |
| EC-04 | LLM 판정이 오래 걸림 | 15초마다 SSE 주석 줄(`: ping`)로 연결을 유지한다 |
| EC-05 | 새 통로가 없는 서버(스트림 통로가 없는 백엔드, 404·405) 또는 응답 전 연결 실패 | 화면이 기존 POST /api/chat으로 한 번 대신 보낸다. 단계 표시 없이 기다림만 보인다 |
| EC-06 | 소식을 받은 뒤 연결이 끊김 | 다시 보내지 않는다(유료 호출 중복). 오류 안내 후 사용자가 다시 묻는다 |
| EC-07 | 키 없는 프론트 데모(NEXT_PUBLIC_API_BASE 없음) | 서버가 없어 단계 소식도 없다. 기다림과 경과 시간만 보이고 단계를 지어내지 않는다 |

## How

- services/chat/progress.py: ContextVar에 듣는 함수를 두고 step(stage)로 알린다. 듣는 쪽이 없으면 아무것도 안 한다. 판정 코드에는 step 한 줄씩만 들어간다
- routers/chat.py POST /api/chat/stream: handle을 별도 스레드에서 돌리고(지금 요청 문맥을 복사해 요청 ID·LLM 사용량 로그가 이어지게) 단계를 큐로 받아 StreamingResponse(text/event-stream)로 보낸다. 헤더 Cache-Control: no-cache, X-Accel-Buffering: no
- 화면(web/lib/api.ts): EventSource는 POST·Authorization 헤더를 못 써서 fetch 응답 본문을 읽어 SSE를 직접 나눈다. 전체 시간 제한은 /api/chat과 같은 90초
- 배포: 화면(Railway marvia-web)이 API(Railway marvia-api)를 `NEXT_PUBLIC_API_BASE`로 바로 부른다. Vercel·Cloud Run은 쓰지 않는다 (처음 Spec에는 Cloud Run이라고 썼다). CORS는 같은 POST라 그대로
- 테스트: backend/tests/integration/test_chat_stream.py (듣는 쪽 없음, 이벤트 모양, 결과가 /api/chat과 같음, 오류 이벤트, 데모 3건 실제 경로의 단계 순서), web/scripts/verify.mjs (가짜 스트림으로 단계 표시·대체·오류, 실행법은 web/README.md)
- 15초마다 `: ping` 주석 줄은 `routers/chat.py PING_SEC`다

## AC (Given-When-Then)

**AC-01 · 정상 조회의 실제 단계**
- GIVEN: 키 없는 데모 B/L(N01)
- WHEN: 실제 판정 경로로 조회
- THEN: customs → identify → position → judge 순서로만 소식이 나오고 결과는 ok·fine

**AC-02 · 멈춘 곳까지만**
- GIVEN: 되묻기 데모(B01)
- WHEN: 조회
- THEN: customs → identify까지만 나오고 position·judge는 나오지 않는다

**AC-03 · 결과는 /api/chat과 같다**
- GIVEN: 같은 요청
- WHEN: /api/chat/stream과 /api/chat으로 각각 보냄
- THEN: stream의 result 데이터와 /api/chat 응답 JSON이 같다

**AC-04 · 화면은 받은 단계만**
- GIVEN: 가짜 스트림이 understand, customs를 보내고 멈춘 상태
- WHEN: 화면이 응답을 기다리는 동안
- THEN: 질문 이해는 완료, 통관 정보 조회는 진행 중, 그 밖의 단계는 보이지 않는다

**AC-05 · 옛 서버 대체**
- GIVEN: /api/chat/stream이 404
- WHEN: 질문을 보냄
- THEN: /api/chat으로 한 번 보내 같은 결과가 나온다
