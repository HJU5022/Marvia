# Spec: 1명당 하루 LLM 토큰 한도

관련: [ADR 0018](../adr/0018-daily-token-quota.md) (이 방식을 고른 이유), [SDD 5.20](../Marvia_SDD.md)

## 현재 동작

- 한 사람이 하루(한국 시각 기준)에 쓸 수 있는 LLM 토큰(입력+출력)을 10만으로 막는다 (`.env.example DAILY_TOKENS_PER_USER=100000`)
- 한도를 넘긴 요청은 끝까지 답하고, 그 답이 화면에 나온 뒤 안내를 띄우고 입력을 막는다. 다음 요청부터는 서버가 429로 막는다
- 재생 모드(`REPLAY_MODE=true`), 한도 값이 비었거나 0일 때, 운영자는 막지 않는다

## 왜

- 비용이 넘칠 때 막는 정책이 필요하다. SDD 8절 실패 처리 표의 "비용 일일 상한(원화)"은 구현하지 않았고, 이 토큰 한도가 비용 방어를 대신한다 (SDD 3.8)
- 한도 값은 실사용 데이터 없이 정한 추정값이다. 가정은 하루 조회 10번과 후속 질문 10번이다

## 동작

| 항목 | 규칙 | 위치 |
|---|---|---|
| 사람 구분 | 로그인했으면 user_id, 아니면 session_id | `services/account/quota.py owner_key` |
| 쌓기 | `llm.chat`이 호출 성공마다 prompt_tokens + completion_tokens를 더한다. 사람은 `session_scope`가 정한다 | `services/account/quota.py add` |
| 저장 | DATABASE_URL이 있으면 `token_usage` 표(`016_token_usage.sql`, PRIMARY KEY (owner, day)), 없으면 프로세스 메모리. 하루의 경계는 한국 시각 자정. 탈퇴하면 그 사람의 줄을 지운다 | `quota.py forget_user` |
| 막기 | `/api/agent`, `/api/chat`, `/api/chat/stream`(스트림을 열기 전), `/api/document` 시작 때 확인한다. 한 요청 안에서는 한 번만 확인해서 처리 도중 넘어도 끝까지 답한다 | `routers/agent.py quota_guard` |
| 지켜보기 재판정 | 그 사용자의 한도를 확인하고 넘으면 건너뛴다 | `services/watch/watch.py` |
| 화면 | 요청을 마칠 때마다 `GET /api/usage`를 읽는다. 다 쓰면 입력창·서류 사진 버튼을 막고 안내를 띄운다. 남은 양이 10% 아래면 미리 알린다(`near_limit`) | `routers/history.py`, `web/components/ChatBar.tsx` |
| 운영자 | 막지 않는다. 사용량은 쌓되 확인에서 뺀다. 서명 확인한 로그인 이메일로 operators 표를 보고 5분 기억한다(`OPERATOR_CACHE_SEC`). `/api/usage`도 운영자에게는 한도 없음(limit null)으로 준다 | `quota.py is_exempt` |
| 한도 값 | 환경변수 `DAILY_TOKENS_PER_USER`. 비우거나 0이면 막지 않는다(키 없는 테스트 환경). 재생 모드(`REPLAY_MODE=true`)도 한도를 두지 않는다. 키 없이 데모를 여러 번 돌리면 `/api/agent` 한 번이 약 1만 토큰이라 기본 한도면 열 번 남짓에 429가 나기 때문이다 | `quota.py limit`, `.env.example` |

## 범위 밖

## 하지 않는 것
- 금액(원) 기준 상한. 모델마다 단가가 달라 토큰으로 센다. `DAILY_COST_CAP_KRW`는 `.env.example`에 칸만 있고 읽는 코드가 없다. 요청 하나의 토큰 상한은 `MAX_TOKENS_PER_REQUEST`가 따로 맡는다(`llm.chat`, SDD 5.6)
- 사람별 다른 한도, 오래된 사용량 줄 정리 (탈퇴 때 그 사람 줄만 지우고, 날짜가 지난 줄을 자동으로 지우는 cron은 없다)

## 완료 기준

`backend/tests/unit/test_quota.py`: 토큰이 쌓임, 로그인 사용자 기준, 한도 이상이면 429, 처리 도중 넘긴 요청은 끝까지 답함, 한도 비면 막지 않음, 운영자는 막지 않음, `/api/usage` 값
