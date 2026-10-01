-- 운영자 권한과 등록·해지 이력 (docs/specs/operator-admin.md, 10-01).
--
-- operators: 지금 누가 운영자인가. 이메일 한 줄에 한 사람. 해지하면 지우지 않고 revoked_*를 채운다.
--   다시 등록하면 같은 줄을 활성으로 되돌린다(granted_* 갱신, revoked_* 비움). 지난 등록·해지는 operator_audit에 남는다.
--   이메일은 소문자로 맞춰 넣는다. 로그인 출입증(JWT)의 email과 대조하기 때문이다 (Spec "운영자 판단").
--   가입 전에도 미리 등록할 수 있어서 Supabase 사용자 ID가 아니라 이메일을 키로 쓴다.
-- operator_audit: 누가 누구를 언제 등록·해지했나. INSERT만 한다. 고치거나 지우는 코드를 두지 않는다.
--   actor_user_id는 등록한 운영자의 Supabase 사용자 ID, 스크립트로 넣은 최초 운영자는 'bootstrap'이다.

CREATE TABLE IF NOT EXISTS operators (
  email       TEXT PRIMARY KEY CHECK (email = lower(email)),
  granted_by  TEXT NOT NULL,
  granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_by  TEXT,
  revoked_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS operator_audit (
  id            BIGSERIAL PRIMARY KEY,
  action        TEXT NOT NULL CHECK (action IN ('grant', 'revoke')),
  target_email  TEXT NOT NULL,
  actor_user_id TEXT NOT NULL,
  actor_email   TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 관리 화면은 최근 이력부터 읽는다
CREATE INDEX IF NOT EXISTS operator_audit_created_idx ON operator_audit (created_at DESC);

-- 005와 같다. 공개 키(Data API)로는 읽지 못하게 RLS를 켜고 규칙은 두지 않는다. 백엔드는 표 주인 계정이라 영향 없음
ALTER TABLE operators ENABLE ROW LEVEL SECURITY;
ALTER TABLE operator_audit ENABLE ROW LEVEL SECURITY;
