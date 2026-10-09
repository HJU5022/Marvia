# Architecture Decision Records

Marvia의 구조를 정한 결정을 한 건씩 기록한다. 번호는 읽는 순서이고 날짜순이 아니다. 날짜는 출처 문서나 커밋에 있는 것만 적었고, 이유가 문서에 없는 항목은 "근거 문서에 적혀 있지 않다"고 밝혔다.
각 파일의 절: 맥락 / 결정 / 대안 / 결과(좋아진 것, 대가) / 근거(파일, 절, 측정 결과 경로). 결정이 바뀌면 새 번호를 만들지 않고 상태 칸을 "대체됨"으로 바꾸고 이유를 적는다.
숫자는 원본 파일 경로와 함께 적었다. 기준 문서는 `docs/Marvia_SDD.md`, `docs/Marvia_PRD.md`, `EVAL_REPORT.md`다.

| 번호 | 제목 | 상태 | 관련 문서 |
|---|---|---|---|
| [0001](0001-verdict-by-code-table.md) | 등급은 코드 판정 표가 정하고 LLM은 회색 지대에서 올리기만 한다 | 채택 | SDD 4.1, 5.7 / EVAL_REPORT 4절 |
| [0002](0002-llm-sdk-only-in-llm-py.md) | LLM SDK는 services/llm.py에서만 import한다 | 채택 | SDD 5.6 / CLAUDE.md |
| [0003](0003-no-rag-whole-skill-docs.md) | RAG와 LangGraph를 쓰지 않고 Skill 문서를 통째로 넣는다 | 채택 | PRD 4, 6.4 / SDD 5.6 |
| [0004](0004-rules-frontmatter-thresholds.md) | 임계값과 목록은 rules.md 프론트매터에 둔다 | 채택 | SDD 3.6 |
| [0005](0005-bl-masking-not-to-llm.md) | B/L은 LLM에 넘기지 않고 트레이스에는 가려서 남긴다 | 채택 | SDD 3.5, 7 / specs/user-profile.md |
| [0006](0006-mcp-server-for-external-data.md) | 외부 데이터 도구는 MCP 서버로 노출하고 서비스도 /mcp로 부른다 | 채택 | SDD 3.4, 5.9 |
| [0007](0007-validation-retry-partial-fallback.md) | 검증 V1~V15, 3단계 재시도, 위반 지속 시 partial 폴백 | 채택 | SDD 5.7 / EVAL_REPORT 4-1, 5절 |
| [0008](0008-replay-mode-keyless.md) | REPLAY_MODE로 키 없이 데모와 평가를 재현한다 | 채택 | SDD 6.1, 6.6 / README |
| [0009](0009-deploy-railway-not-vercel.md) | 배포는 Railway, Vercel과 api용 Cloud Run은 쓰지 않는다 | 채택 | SDD 2.2, 6.4 / release_manifest.json |
| [0010](0010-deployed-server-real-mode.md) | 배포 서버는 재생 모드가 아니라 실제 모드로 돌린다 | 채택 | SDD 2.2 / release_manifest.json |
| [0011](0011-mof-seoul-relay.md) | 해수부 API는 서울 Cloud Run 릴레이를 거쳐 부른다 | 채택 | SDD 6.7 / relay/README.md |
| [0012](0012-service-model-gemini-flash-lite.md) | 서비스 모델을 gpt-4o-mini에서 gemini-3.5-flash-lite로 바꿨다 | 채택 (gpt-4o-mini 대체) | EVAL_REPORT 5절 |
| [0013](0013-prompts-in-langfuse-production-label.md) | 프롬프트는 Langfuse에서 가져오고 production 라벨로 되돌린다 | 채택 | SDD 5.6 / prompt_versions.md |
| [0014](0014-prompt-release-order.md) | 새 코드에 기대는 프롬프트는 코드 배포 뒤에 라벨을 옮긴다 | 채택 | CLAUDE.md / release_manifest.json |
| [0015](0015-same-name-vessel-needs-user-evidence.md) | 동명 선박은 사용자 근거 없이 LLM이 확정하지 않는다 | 채택 | SDD 5.5 / EVAL_REPORT 4절 3번 |
| [0016](0016-chat-agent-with-tools-and-guard.md) | 채팅 입구는 도구를 고르는 에이전트로 하되 코드 가드로 감싼다 | 채택 | SDD 4.5 / specs/chat-search.md |
| [0017](0017-memory-feature-decisions.md) | 화물 비서 기억은 화물 표와 메모장 두 개, 등급에는 쓰지 않는다 | 채택 | specs/memory.md |
| [0018](0018-daily-token-quota.md) | 남용 방어는 로그인과 1명당 하루 토큰 한도로 한다 | 채택 | specs/token-quota.md / SDD 5.20 |
| [0019](0019-watch-user-opt-in-limit.md) | 지켜보기는 사용자가 켠 화물만, 사용자당 최대 5건 | 채택 | specs/cargo-watch.md / SDD 5.10 |
| [0020](0020-remove-web-search-use-skill.md) | 채팅 에이전트의 웹 검색 도구를 없애고 수입 실무 기초는 Skill 문서로 둔다 | 채택 (웹 검색 도구 구조 대체) | 가이드 표 2·3 / prompt_versions.md chat-agent 16 / skills/import-basics |
