# 0016. 채팅 입구는 도구를 고르는 에이전트로 하되 코드 가드로 감싼다

상태: 채택

## 맥락
칸을 채우는 폼은 B/L 하나 조회만 된다. 사용자는 말로 묻고 싶어 하고, "중국에서 오는 배" 같은 배 단위 질문은 폼으로 못 한다 ([specs/chat-search.md](../specs/chat-search.md)). 처음엔 LLM이 의도 하나를 고르고 코드가 실행했다(`marvia-chat-route`).

## 결정
- `llm.chat_agent`가 도구를 골라 부르고, 실행은 코드가 한다. 도구 루프 상한은 `MAX_TOOL_ROUNDS=3`이다 (`services/llm_config.py`).
- 에이전트가 받는 도구는 Marvia 도구 7개와 읽기 전용 MCP 도구 4개([0006](0006-mcp-server-for-external-data.md))다. Marvia 도구는 `services/chat/tools.py AGENT_TOOLS`에 있다.

| 도구 | 하는 일 |
|---|---|
| check_cargo | B/L 하나를 조회하고 판정한다 |
| ask_cargo | 화면에 있는 화물의 판정 결과로 질문에 답한다 |
| search_arrivals | 부산 입항 예정 선박을 출발지로 걸러 보여 준다 |
| set_watch | 화면의 화물 지켜보기를 켜고 끈다 |
| watch_vessel | 배 한 척 지켜보기를 켜고 끈다 (chat-agent 14에서 추가) |
| send_kakao | 화면의 화물 현재 상태를 본인 카카오톡으로 보낸다 |
| recall_memo | 사용자가 저장한 연락처와 메모를 읽는다. 연락처 질문에 사용자 메모로 답하려고 chat-agent 15에서 추가 |

- 웹 검색 도구는 없다. 처음에는 있었으나 지웠다 ([0020](0020-remove-web-search-use-skill.md)).
- 입력은 코드가 먼저 가린다(B/L은 `[BL1]`, 컨테이너는 `[CNTR1]`, [0005](0005-bl-masking-not-to-llm.md)). 주입 모양이면 LLM 없이 고정 안내를 준다(guard).
- 답은 코드가 답 종류(answer_kind)별로 V7, V9, V10, V13, V14로 검사하고, 걸리면 고정 안내로 바꾼다. 규칙 뜻은 [SDD 5.7절](../Marvia_SDD.md) 표에 있다.
- 에이전트를 쓸 수 없으면(키 없음, 도구를 거절하는 모델, `CHAT_AGENT=off`) 의도 고르기(`route_chat`) 경로로 간다. LLM이 아예 안 되면 B/L이 있으면 조회하고 없으면 B/L을 묻는다.
- 판정은 에이전트가 하지 않는다. 화물 조회는 `run_agent`를 그대로 부르므로 판정 규칙이 같다.

## 대안
- 의도 4가지 중 하나를 고르는 `route_chat` 방식 유지: 대비 경로로 남겼다.

## 결과
- 좋아진 것: 지시문 정리 전후 비교(chat-agent 13+2줄 -> 14, 162건 x 2회)에서 통과율 85.0% -> 87.6%, 호출당 입력 토큰 35,333 -> 26,963 ([evals/results/chat_agent_ab_20261007.md](../../evals/results/chat_agent_ab_20261007.md)).
- 대가: 두 버전 모두 사람 이름을 받으면 따라 쓰는 문항(17~25%)에 약하다. 통과율 차이의 흔들림 폭은 재지 않았다 ([EVAL_REPORT 4-2절](../../EVAL_REPORT.md)).

## 근거
- [SDD](../Marvia_SDD.md) 4.5절, 5.6절, 7절
- [EVAL_REPORT.md](../../EVAL_REPORT.md) 4-2절, [specs/chat-search.md](../specs/chat-search.md)
- [prompt_versions.md](../prompt_versions.md) chat-agent 14, 15 행
- 커밋 `cfbff9c`
