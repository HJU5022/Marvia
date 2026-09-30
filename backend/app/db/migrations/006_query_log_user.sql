-- 조회 이력을 로그인한 사용자에 묶는다 (작업 G3, SDD 3.9 query_log의 user_id 칸).
--
-- 로그인은 Supabase Auth(구글)가 하고, 백엔드는 출입증(JWT)에서 사용자 ID(sub)만 꺼내 여기에 넣는다.
-- 손님(로그인 안 함) 조회는 user_id가 비어 있고, 지금처럼 session_id로만 구분한다.
-- 로그인한 사람도 화면 세션은 있으므로 session_id NOT NULL은 그대로 둔다.
-- 이메일·이름은 넣지 않는다. 사용자 ID만으로 이력을 묶을 수 있고, 개인정보는 적게 둘수록 좋다.

ALTER TABLE query_log ADD COLUMN IF NOT EXISTS user_id TEXT;

-- 로그인 사용자의 이력·메모리는 사용자별 최신순으로 읽는다
CREATE INDEX IF NOT EXISTS query_log_user_created_idx ON query_log (user_id, created_at DESC);
