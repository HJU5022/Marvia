-- 고객 계정 일시 정지 (docs/specs/operator-admin.md "고객 계정 일시 정지", 10-01).
--
-- suspended_users: 지금 정지 중인 사람. 해제하면 줄을 지운다. 지난 정지·해제는 admin_actions에 남는다.
-- 이 표는 auth.current_user가 요청마다 user_id로 찾는다. 이미 받은 출입증(최대 1시간)도 바로 막으려는 것이다.
-- Supabase 계정 차단(ban)도 같이 건다. 그쪽은 새 로그인과 출입증 갱신을 막는다.

CREATE TABLE IF NOT EXISTS suspended_users (
  user_id       TEXT PRIMARY KEY,
  suspended_by  TEXT NOT NULL,
  reason        TEXT NOT NULL,
  suspended_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE suspended_users ENABLE ROW LEVEL SECURITY;

-- 운영자 작업 이력에 정지·해제를 더한다 (011의 CHECK 확장). 011의 기본 제약 이름은 admin_actions_action_check
ALTER TABLE admin_actions DROP CONSTRAINT IF EXISTS admin_actions_action_check;
ALTER TABLE admin_actions ADD CONSTRAINT admin_actions_action_check
  CHECK (action IN ('customer_update', 'customer_delete', 'unmask', 'customer_suspend', 'customer_resume'));
