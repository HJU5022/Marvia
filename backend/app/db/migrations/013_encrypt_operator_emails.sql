-- 운영자·이력의 이메일을 평문에서 지문(찾기용) + 암호문(보기용) + 가린 값(목록용)으로 (10-01, docs/specs/operator-admin.md).
--
-- 전에는 operators.email(평문)을 출입증 email과 비교해 운영자인지 정했다. Fernet 암호문은 같은 값도 매번 달라
-- 비교할 수 없어서 평문으로 뒀는데, 운영자 이메일도 개인정보라 고객 정보와 같은 기준으로 맞춘다.
-- - email_hash: HMAC-SHA256 지문 (crypto.fingerprint). 운영자 찾기와 중복 확인은 이것으로만 한다
-- - email_enc: Fernet 암호문 (crypto.encrypt). 운영자 화면에서만 풀어 보여 준다
-- - email_masked: ks***@g***.com. 열쇠를 잃어도 누구였는지 짐작할 수 있게
-- 평문 칸(email, target_email, actor_email)은 남기되 비워 둔다. 기존 행은 scripts/ops/encrypt_operator_emails.py가 옮기고 비운다
-- (마이그레이션은 SQL이라 열쇠로 잠글 수 없다). 새 행은 코드가 평문을 쓰지 않는다.
-- operator_audit·admin_actions는 INSERT만 하는 이력이지만, 평문을 지우는 이 이전 한 번만 기존 줄을 고친다 (Spec에 기록).

ALTER TABLE operators ADD COLUMN IF NOT EXISTS email_hash TEXT;
ALTER TABLE operators ADD COLUMN IF NOT EXISTS email_enc TEXT;
ALTER TABLE operators ADD COLUMN IF NOT EXISTS email_masked TEXT;
ALTER TABLE operators DROP CONSTRAINT IF EXISTS operators_pkey;
ALTER TABLE operators ALTER COLUMN email DROP NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS operators_email_hash_key ON operators (email_hash);

ALTER TABLE operator_audit ADD COLUMN IF NOT EXISTS target_email_enc TEXT;
ALTER TABLE operator_audit ADD COLUMN IF NOT EXISTS target_email_masked TEXT;
ALTER TABLE operator_audit ADD COLUMN IF NOT EXISTS actor_email_enc TEXT;
ALTER TABLE operator_audit ADD COLUMN IF NOT EXISTS actor_email_masked TEXT;
ALTER TABLE operator_audit ALTER COLUMN target_email DROP NOT NULL;

ALTER TABLE admin_actions ADD COLUMN IF NOT EXISTS actor_email_enc TEXT;
ALTER TABLE admin_actions ADD COLUMN IF NOT EXISTS actor_email_masked TEXT;
