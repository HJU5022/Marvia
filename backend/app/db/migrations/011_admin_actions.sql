-- 운영자가 고객에게 한 일 이력: 수정, 강제 탈퇴, 마스킹 해제 (docs/specs/operator-admin.md 추가 절, 10-01).
--
-- INSERT만 한다. 고치거나 지우는 코드를 두지 않는다 (operator_audit와 같은 원칙).
-- 마스킹 해제(unmask)는 원문을 돌려주기 전에 먼저 여기에 쓴다. 쓰기에 실패하면 원문을 주지 않는다.
-- target_email_masked: 강제 탈퇴 뒤에는 Supabase 계정이 없어 user_id만으로는 누구였는지 모른다. 가린 이메일로 남긴다.
-- reason: 마스킹 해제 사유(필수, 10~500자). 수정·탈퇴는 비어 있을 수 있다.

CREATE TABLE IF NOT EXISTS admin_actions (
  id                  BIGSERIAL PRIMARY KEY,
  action              TEXT NOT NULL CHECK (action IN ('customer_update', 'customer_delete', 'unmask')),
  target_user_id      TEXT NOT NULL,
  target_email_masked TEXT,
  actor_user_id       TEXT NOT NULL,
  actor_email         TEXT,
  reason              TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS admin_actions_created_idx ON admin_actions (created_at DESC);

-- 005와 같다. 공개 키로는 읽지 못하게 RLS를 켜고 규칙은 두지 않는다
ALTER TABLE admin_actions ENABLE ROW LEVEL SECURITY;
