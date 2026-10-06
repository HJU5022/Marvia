-- 1명당 하루 LLM 토큰 사용량 (docs/specs/token-quota.md, 10-02).
--
-- owner: 로그인했으면 "user:<Supabase 사용자 ID>", 아니면 "session:<세션 ID>". 이메일·이름은 넣지 않는다.
-- day: 한국 시각 날짜. 자정이 지나면 새 줄이 생겨 한도가 다시 찬다.
-- tokens: 그날 LLM 호출의 입력+출력 토큰 합계. services/quota.py가 호출마다 더한다.
-- 오래된 줄을 지우는 함수는 아직 없다. 하루 한 사람 한 줄이라 크기가 작다.

CREATE TABLE IF NOT EXISTS token_usage (
  owner      TEXT NOT NULL,
  day        DATE NOT NULL,
  tokens     INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (owner, day)
);

-- 005와 같다. 공개 키(Data API)로는 읽지 못하게 RLS를 켜고 규칙은 두지 않는다
ALTER TABLE token_usage ENABLE ROW LEVEL SECURITY;
