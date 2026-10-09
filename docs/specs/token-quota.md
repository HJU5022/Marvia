# Spec: 1명당 하루 LLM 토큰 한도

## 무엇을
한 사람이 하루(한국 시각 기준)에 쓸 수 있는 LLM 토큰(입력+출력)을 10만으로 막는다.
한도를 넘긴 요청은 끝까지 답하고, 그 답이 화면에 나온 뒤 안내를 띄우고 입력을 막는다. 다음 요청부터는 서버가 429로 막는다.

## 왜
가이드 원칙 2(실패 경로)의 "비용 초과: 요청당 상한, 초과 시 차단 정책"과 SDD 8절 "비용 상한 초과"에 대응한다.
실사용 데이터가 없어 한도는 추정값이다. 근거: 평가 실측 호출당 토큰(판정 입력 약 4천, 출력 최대 약 300)과
"하루 조회 10번 + 후속 질문 10번 ≈ 10만 토큰" 가정 (사용자 결정).

## 어떻게
- 사람 구분: 로그인했으면 user_id, 아니면 session_id (`services/account/quota.py owner_key`)
- 쌓기: `llm.chat`이 호출 성공마다 prompt_tokens + completion_tokens를 더한다. 사람은 `session_scope`가 정한다
- 저장: DATABASE_URL이 있으면 `token_usage` 표(016_token_usage 마이그레이션, PRIMARY KEY (owner, day)), 없으면 프로세스 메모리. 하루의 경계는 한국 시각 자정. 탈퇴하면 그 사람의 줄을 지운다 (`quota.py`)
- 막기: `/api/agent`, `/api/chat`, `/api/chat/stream`(스트림 열기 전), `/api/document` 시작 때 `quota_guard`(routers/agent.py)가 확인. 지켜보는 화물 재판정(`services/watch/watch.py`)도 그 사용자의 한도를 확인하고 넘으면 건너뛴다. 한 요청 안에서는 한 번만 확인해서 처리 도중 넘어도 끝까지 답한다
- 화면: 요청을 마칠 때마다 `GET /api/usage`(routers/history.py)를 읽는다. 다 쓰면 입력창·서류 사진 버튼을 막고 안내를 띄운다. 10% 아래로 남으면 미리 알린다
- 운영자 예외: 운영자는 막지 않는다. 사용량은 쌓되 확인에서 뺀다. 서명 확인한 로그인 이메일로 operators 표를 보고 5분 기억한다. `/api/usage`도 운영자에게는 한도 없음(limit null)으로 준다
- 한도 값: 환경변수 `DAILY_TOKENS_PER_USER` (.env.example 100000). 비우거나 0이면 막지 않는다 (키 없는 테스트·채점 환경)

## 하지 않는 것
- 금액(원) 기준 상한. 모델마다 단가가 달라 토큰으로 센다. `DAILY_COST_CAP_KRW`는 `.env.example`에 칸만 있고 읽는 코드가 없다. 요청 하나의 토큰 상한은 `MAX_TOKENS_PER_REQUEST`가 따로 맡는다(`llm.chat`, SDD 5.6)
- 사람별 다른 한도, 오래된 사용량 줄 정리 (탈퇴 때 그 사람 줄만 지우고, 날짜가 지난 줄을 자동으로 지우는 cron은 없다)

## 완료 기준
- `backend/tests/unit/test_quota.py`: 토큰이 쌓임, 로그인 사용자 기준, 한도 이상이면 429, 처리 도중 넘긴 요청은 끝까지 답함, 한도 비면 막지 않음, 운영자는 막지 않음, /api/usage 값
