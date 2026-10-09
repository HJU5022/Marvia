# 0020. 채팅 에이전트의 웹 검색 도구를 없애고 수입 실무 기초는 Skill 문서로 둔다

상태: 채택

## 맥락
채팅 에이전트에는 `web_search` 도구가 있었다. Skill 문서에 없는 실무 질문(B/L 번호 찾는 곳, 포워더 확인, A/N 같은 낱말 뜻)에 OpenRouter 웹 플러그인(engine exa)으로 결과 세 건의 본문을 가져와 프롬프트에 붙이고, 그 글에서 근거 조각을 찾아 답했다.

과정 가이드는 RAG를 쓰지 않도록 한다. 가이드 표 2(11~12쪽)는 "웹 검색 결과 본문을 긁어 프롬프트에 붙여 답변 생성"을 RAG의 한 모양으로 든다. 표 3의 허용 쪽(Skill 문서를 통째로 넣기, 도구로 실시간 데이터 가져오기)에는 이 방식이 없다. `web_search`는 표 2의 그 항목과 같은 일을 했다 ([0003](0003-no-rag-whole-skill-docs.md)).

## 결정
- 웹 검색 도구와 관련 설정, 답 종류 `web`, 진행 단계 `tool_web`을 모두 지웠다. 지금 `backend/app`에 `web_search`는 없다. 지운 코드: `llm.web_search`, `WEB_TOOL`, `web_search_enabled`와 환경변수 `WEB_SEARCH`, `WEB_HINT`, `WEB_RESULTS`, `WEB_TEXT_CHARS` (커밋 `0ac9675`).
- 수입 실무 기초는 고정 문서 `skills/import-basics/SKILL.md`로 옮겼다. 채팅 답(`CHAT_AGENT_SKILLS`)과 후속 질문(`FOLLOW_UP_SKILLS`)에만 통째로 넣고, 판정, 동명 선박 고르기, 채점 입력에는 넣지 않는다. 도구 없이 낸 실무 답은 이 문서 원문에서 근거 조각을 찾는 V14 검사를 받는다.
- 프롬프트 chat-agent 16: 도구 줄, 웹 검색 단계, `web` 답 종류를 뺐다. 회사 전화번호는 찾지 않고 포워더나 선사에 확인하라고 안내한다.

## 대안
- 웹 검색은 두고 링크만 보여 주기(본문은 프롬프트에 붙이지 않음): 가져온 링크의 내용이 맞는지 코드가 확인할 수 없고, "본문을 붙이는 것"과 경계가 모호해 택하지 않았다.
- 웹 검색을 유지하고 문서에 예외로 적기: 표 2에 걸리는 구조를 설명으로 덮는 일이라 택하지 않았다.

## 결과
- 좋아진 것: 가이드의 RAG 금지 기준에 걸리는 경로가 없다. 검색 호출 비용, 결과가 매번 달라지는 문제, 검색 글 속 주입 문장 위험이 사라졌다. 답 근거가 레포의 고정 문서라 평가를 다시 돌려도 같은 결과를 기대할 수 있다.
- 확인: chat-agent 16과 코드를 함께 배포한 뒤, 운영 채팅 "컨테이너 무료기간 언제부터 부과돼?"가 import-basics 내용으로 답했고 트레이스 prompt_version이 16이었다 ([release_manifest.json](../release_manifest.json) `deploy.verification`). 운영 확인은 이 1건이다. 로컬에서는 실제 LLM으로 예전 웹 검색 질문이 Skill로 답하는 것을 확인했다 ([prompt_versions.md](../prompt_versions.md) chat-agent 16 행).
- 대가: 문서에 없는 실무 질문(특히 특정 회사 연락처)은 답하지 못하고 "포워더나 선사에 확인해 달라"고 안내한다. `import-basics` 범위 밖 질문은 "자료에 없다"로 끝난다.

## 근거
- 과정 가이드 표 2, 표 3 (11~12쪽)
- Langfuse 집계에서 `web_search` 관측 56건 ([docs/evidence/langfuse_summary.md](../evidence/langfuse_summary.md), 집계 기간 2026-09-01 ~ 2026-10-08)
- [prompt_versions.md](../prompt_versions.md) chat-agent 16 행, [release_manifest.json](../release_manifest.json) `change_reason`, `deploy.verification`
- 지운 뒤 구조: [specs/chat-search.md](../specs/chat-search.md), [SDD 4.5절](../Marvia_SDD.md)
- 커밋 `0ac9675`(웹 검색 도구 제거, 지우기 전 설정은 그 부모 커밋의 `services/llm_config.py`), `abd8dbe`(import-basics 연결과 chat-agent 16)
