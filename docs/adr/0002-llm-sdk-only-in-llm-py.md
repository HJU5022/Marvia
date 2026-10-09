# 0002. LLM SDK는 services/llm.py에서만 import한다

상태: 채택

## 맥락
판정, 선박 선택, 후속 질문, 채팅 에이전트, 서류 추출, 기억 뽑기, 제목 등 LLM을 쓰는 곳이 여럿이다. 호출마다 재시도, 타임아웃, 토큰 집계, 트레이스, 프롬프트 가져오기가 필요하다.

## 결정
openai SDK는 `backend/app/services/llm.py`에서만 import한다. 라우터, MCP 도구, 워커, 프론트는 LLM을 직접 부르지 않는다. llm.py의 함수마다 프롬프트 이름이 하나씩 정해져 있다(SDD 5.6절 표).

## 대안
- 라우터나 서비스에서 SDK를 직접 부르기: `CLAUDE.md` "하지 말 것"이 금지한다. 비교 기록은 근거 문서에 없다.

## 결과
좋아진 것: 호출 1회 + 재시도 1회(`MAX_ATTEMPTS=2`), 호출당 타임아웃 60초, 구조화 출력, 하루 토큰 집계(`services/account/quota.add()`), Langfuse 관측이 한 파일에 모인다 (SDD 5.6절).
대가: 이 선택의 단점은 근거 문서에 적혀 있지 않다.

## 근거
- `CLAUDE.md` "하지 말 것" 2번째 항목
- `docs/Marvia_SDD.md` 1절 금지 항목(12행), 5.6절
- 완료 기준 테스트: `test_llm.py`, `test_llm_tool_rounds.py`, `test_prompts.py`, `test_trace.py` (SDD 5.6절)
