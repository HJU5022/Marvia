# 0018. 남용 방어는 로그인과 1명당 하루 LLM 토큰 한도로 한다

상태: 채택

## 맥락
IP당 분당 20회 레이트 리밋(slowapi)은 계획이었으나 구현하지 않았다 ([SDD](../Marvia_SDD.md) "부록. 계획 대비 변경" 표 레이트 리밋 행). 비용이 한 사람 때문에 크게 늘지 않게 막을 선이 필요하다. 금액 기준 상한(SDD 8.1절 "비용 일일 상한(원화)" 행)도 구현하지 않았다.

## 결정
- 한 사람이 하루(한국 시각 자정 기준)에 쓰는 LLM 토큰(입력+출력)을 `DAILY_TOKENS_PER_USER`(`.env.example` 100000)로 막는다. 비우거나 0이면 막지 않는다.
- `llm.chat`이 성공 호출마다 쌓고(`services/account/quota.add()`), `token_usage` 표(마이그레이션 016)에 저장한다.
- 한도를 넘긴 요청은 끝까지 답하고, 다음 요청부터 429 `daily_token_limit`이다. 화면은 `GET /api/usage`로 읽어 입력을 막는다.
- 운영자는 막지 않는다. 금액 기준 상한은 만들지 않는다(`DAILY_COST_CAP_KRW`는 칸만 있고 읽는 코드가 없다). 요청당 토큰 상한 `MAX_TOKENS_PER_REQUEST`는 처음엔 칸만 있었다가 `llm.chat`이 읽도록 붙였다. 요청 안 누계가 상한에 닿으면 다음 LLM 호출을 하지 않고 부분 응답 경로로 간다.

## 대안
- IP당 레이트 리밋: 구현하지 않았다. 로그인 필수와 하루 토큰 한도가 대신한다 ([SDD 7.3절](../Marvia_SDD.md)).
- 금액(원) 기준 상한: 위 이유로 토큰을 택했다.

## 결과
- 좋아진 것: 한 사람의 비용이 하루 단위로 막힌다.
- 대가: 10만이라는 값은 실사용 데이터 없이 "하루 조회 10번 + 후속 질문 10번 약 10만 토큰"이라는 가정에서 나온 추정값이다.

## 근거
- [specs/token-quota.md](../specs/token-quota.md), [SDD](../Marvia_SDD.md) 5.20절, 7.3절, 8.1절, 부록 "계획 대비 변경"
- `backend/app/services/account/quota.py`
- 테스트: `backend/tests/unit/test_quota.py`
- 커밋 `acb5bd7`
