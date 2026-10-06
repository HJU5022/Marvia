-- DB 정리 (10-06). 코드가 쓰지도 읽지도 않는 칸을 지우고, 빠진 기본 키·인덱스를 채운다.
-- 지우기 전에 칸이 비어 있는지 확인하고, 값이 남아 있으면 그 칸은 지우지 않고 알림만 남긴다 (되돌릴 수 없는 삭제라서).
--
-- 지우는 것
-- - query_log.retry_count: 쓰는 코드도 읽는 코드도 없다. 늘 NULL (003부터)
-- - query_log.model: 이력 API가 읽지만 저장하는 코드가 없어 늘 NULL. 이력 응답의 model 칸은 null로 남긴다
-- - operators.email, operator_audit.target_email·actor_email, admin_actions.actor_email: 013에서 지문·암호문으로 옮기고 비운 옛 평문 칸
-- 채우는 것
-- - operators 기본 키: 013에서 email 기본 키를 지운 뒤 없었다. email_hash를 기본 키로
-- - query_log (user_id, bl_masked, created_at DESC): 로그인 사용자의 후속 질문 조회(latest_response) 조건에 맞는 인덱스가 없었다
-- 그대로 두는 것: user_cargo·user_memory(기억 기능이 씀), query_log.bl_encrypted(기억·후속 질문이 읽음),
--   arrival_reports·control_events·positions의 연구용 칸(worker 수집, 팀 결정 전)

DO $$
DECLARE
  item record;
  filled bigint;
BEGIN
  FOR item IN SELECT * FROM (VALUES
      ('query_log', 'retry_count'), ('query_log', 'model'),
      ('operators', 'email'), ('operator_audit', 'target_email'), ('operator_audit', 'actor_email'),
      ('admin_actions', 'actor_email')) AS t(tbl, col)
  LOOP
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = item.tbl AND column_name = item.col) THEN
      EXECUTE format('SELECT count(*) FROM %I WHERE %I IS NOT NULL', item.tbl, item.col) INTO filled;
      IF filled = 0 THEN
        EXECUTE format('ALTER TABLE %I DROP COLUMN %I', item.tbl, item.col);
      ELSE
        RAISE NOTICE '%.% 에 값이 % 줄 남아 있어 지우지 않았다', item.tbl, item.col, filled;
      END IF;
    END IF;
  END LOOP;

  -- email_hash가 빈 줄이 없을 때만 기본 키로 만든다
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'operators'::regclass AND contype = 'p')
     AND NOT EXISTS (SELECT 1 FROM operators WHERE email_hash IS NULL) THEN
    ALTER TABLE operators ALTER COLUMN email_hash SET NOT NULL;
    ALTER TABLE operators ADD PRIMARY KEY (email_hash);
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS query_log_user_bl_created_idx ON query_log (user_id, bl_masked, created_at DESC);
