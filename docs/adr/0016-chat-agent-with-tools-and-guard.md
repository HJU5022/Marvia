# 0016. 채팅 입구는 도구를 고르는 에이전트로 하되 코드 가드로 감싼다

상태: 채택 · 날짜: 2026-10-05 (커밋 cfbff9c)

## 맥락
칸을 채우는 폼은 B/L 하나 조회만 된다. 사용자는 말로 묻고 싶어 하고, "중국에서 오는 배" 같은 배 단위 질문은 폼으로는 못 한다 (`docs/specs/chat-search.md` Why). 처음엔 LLM이 의도 하나를 고르고 코드가 실행하는 방식(`marvia-chat-route`)이었다.

## 결정
- `llm.chat_agent`가 도구를 골라 부른다. Marvia 도구 5종(check_cargo, ask_cargo, search_arrivals, set_watch, send_kakao)과 읽기 전용 MCP 도구 4종, 이다. 처음에는 Skill에 없는 실무 질문용 웹 검색 도구도 있었으나 없앴다 (0020). 도구 루프 상한은 `MAX_TOOL_ROUNDS=3`이다.
- 입력은 코드가 먼저 가린다(B/L은 `[BL1]`, 컨테이너는 `[CNTR1]`). 주입 모양이면 LLM 없이 고정 안내를 준다(guard).
- 답은 코드가 answer_kind별로 V7, V9, V10, V13, V14로 검사하고 걸리면 고정 안내로 바꾼다.
- 에이전트가 안 되면 `route_chat` 경로로 돌아간다. LLM이 아예 안 되면 B/L이 있으면 조회, 없으면 B/L을 묻는다.
- 판정은 에이전트가 하지 않는다. 화물 조회는 `run_agent`를 그대로 부르므로 판정 규칙이 같다.

## 대안
- route_chat 방식 유지(의도 4가지 중 하나 선택): 대비 경로로 남겼다.

## 결과
좋아진 것: 지시문 정리 전후 비교(chat-agent 13+2줄 -> 14, 162건 x 2회)에서 통과율 85.0% -> 87.6%, 호출당 입력 토큰 35,333 -> 26,963 (`evals/results/chat_agent_ab_20261007.md`).
대가: 두 버전 모두 사람 이름을 받으면 따라 쓰는 문항(17~25%)에서 약하다. 통과율 차이의 흔들림 폭은 재지 않았다 (`EVAL_REPORT.md` 4-2절).

## 근거
- `docs/Marvia_SDD.md` 4.5절, 5.6절, 7절
- `EVAL_REPORT.md` 4-2절, `docs/specs/chat-search.md`
