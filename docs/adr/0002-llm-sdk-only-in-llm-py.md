# 0002. LLM SDK는 services/llm.py에서만 import한다

상태: 채택

## 맥락
판정, 선박 선택, 후속 질문, 채팅 에이전트, 서류 추출, 기억 뽑기, 대화 제목 등 LLM을 쓰는 곳이 여럿이다. 호출마다 재시도, 타임아웃, 토큰 집계, 트레이스, 프롬프트 가져오기가 필요하다.

## 결정
- openai SDK는 `backend/app/services/llm.py`에서만 import한다. 보조 파일(`llm_config`, `llm_types`, `llm_schemas`, `llm_support`)은 SDK를 import하지 않는다.
- 라우터, MCP 도구, 워커, 프론트는 LLM을 직접 부르지 않는다.
- llm.py의 함수마다 프롬프트 이름이 하나씩 정해져 있다 ([SDD 5.6절](../Marvia_SDD.md) 표).

## 결과
- 좋아진 것: 한 파일에 모인다. 호출 1회 + 재시도 1회(`llm_config.MAX_ATTEMPTS=2`), 호출당 타임아웃 60초(`llm.TIMEOUT_SEC`), 구조화 출력, 하루 토큰 집계(`services/account/quota.add()`), Langfuse 관측.

## 근거
- [CLAUDE.md](../../CLAUDE.md) "하지 말 것": "LLM SDK(openai 등)는 backend/app/services/llm.py에서만 import한다"
- [SDD](../Marvia_SDD.md) 1절 금지 항목, 5.6절
- 테스트: `backend/tests/unit/test_llm.py`, `backend/tests/unit/test_llm_tool_rounds.py`, `backend/tests/unit/test_trace.py`, `backend/tests/contract/test_prompts.py`
