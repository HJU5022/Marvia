# 0003. RAG와 LangGraph를 쓰지 않고 Skill 문서를 통째로 프롬프트에 넣는다

상태: 채택

## 맥락
선박 신호 해석, 통관 단계 뜻, 판정 표 같은 도메인 지식이 필요하고, 위치나 입항 일정 같은 실시간 데이터도 필요하다.

## 결정
- 지식은 호출마다 필요한 `skills/` 문서를 시스템 프롬프트에 통째로 넣는다. 청킹, 벡터 검색은 만들지 않는다.
- 실시간 데이터는 MCP 도구로 가져온다 ([0006](0006-mcp-server-for-external-data.md)). 웹 검색 결과를 붙이는 도구도 두지 않는다 ([0020](0020-remove-web-search-use-skill.md)).
- langgraph는 설치도 import도 하지 않는다.

호출별로 넣는 Skill (`backend/app/services/llm.py`):

| 호출 | 상수 | Skill |
|---|---|---|
| 판정 | `JUDGE_SKILLS` | ais-reliability, customs-stages, cargo-verdict |
| 동명 선박 고르기 | `PICK_SKILLS` | ais-reliability |
| 후속 질문, 채팅 에이전트 | `FOLLOW_UP_SKILLS`, `CHAT_AGENT_SKILLS` | ais-reliability, customs-stages, port-busan, cargo-verdict, import-basics |
| 통관 해설 채점 (평가 때만) | `GRADE_SKILLS` | customs-stages |

`skills/referrals`는 어느 LLM 호출에도 넣지 않는다.

## 대안
- RAG(청킹 후 검색해 주입), LangGraph 오케스트레이션: 과정 가이드가 금지한다 ([PRD 4절](../Marvia_PRD.md) "쓰지 않는 것" 줄).

## 결과
- 좋아진 것: 검색 인덱스와 청킹 단계가 없다. 판정 입력은 judge 4에서 4,351 토큰, judge 5에서 4,115 토큰이었다 ([EVAL_REPORT 4절](../../EVAL_REPORT.md) 표 2번, `b_20260930_1219` -> `b_20260930_1230`).
- 대가: Skill 문서가 길어질수록 호출마다 토큰이 는다. Skill과 프롬프트가 겹치는 줄을 지운 judge 5는 통관 해설 점수가 19/21 -> 16/21로 떨어져 버렸다 (같은 표 2번, DISCARD).

## 근거
- [CLAUDE.md](../../CLAUDE.md) "하지 말 것": "langgraph를 설치하거나 import하지 않는다. 문서를 청킹해 검색하고 프롬프트에 붙이는 RAG를 만들지 않는다"
- [PRD](../Marvia_PRD.md) 4절 "쓰지 않는 것" 줄, 6.4절
- [SDD](../Marvia_SDD.md) 1절 금지 항목, 5.6절
