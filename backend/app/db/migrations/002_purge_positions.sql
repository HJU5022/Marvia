-- 위치 기록 보관 기한 (09-23 결정: 입항 30일 뒤 삭제).
--
-- 삭제 규칙은 이 함수 하나에만 둔다. 부르는 쪽만 다르다.
--   Supabase(배포): pg_cron이 켜져 있으면 아래 DO 블록이 하루 한 번 실행을 등록한다.
--                   pg_cron은 대시보드 Database → Extensions(또는 Integrations → Cron)에서 켠다
--   로컬·채점용 postgres:16: pg_cron이 없어 등록을 건너뛴다. 대신 워커가 실행마다 이 함수를 부른다
--
-- 입항 시각: 관제정보의 실제 입항 기록을 먼저 쓰고, 없으면 대상으로 고를 때 본 입항 예정을 쓴다.
-- 같은 배가 여러 번 들어오면 가장 최근 입항을 기준으로 한다. 덜 지우는 쪽이라 안전하다.
-- 입항 시각을 모르는 배(대상이 아닌 MMSI 등)의 기록은 지우지 않는다.

CREATE OR REPLACE FUNCTION purge_old_positions(keep_days integer DEFAULT 30)
RETURNS integer
LANGUAGE sql
AS $$
  WITH arrived AS (
    SELECT t.mmsi,
           COALESCE(
             (SELECT max(e.at) FROM control_events e WHERE e.call_sign = t.call_sign AND e.kind = '입항'),
             t.planned_at
           ) AS arrived_at
    FROM targets t
    WHERE t.mmsi IS NOT NULL
  ),
  gone AS (
    DELETE FROM positions p
    USING arrived a
    WHERE p.mmsi = a.mmsi
      AND a.arrived_at IS NOT NULL
      AND a.arrived_at < now() - make_interval(days => keep_days)
    RETURNING 1
  )
  SELECT count(*)::integer FROM gone;
$$;

DO $$
BEGIN
  -- cron 스키마가 있으면 pg_cron이 켜진 DB다. 매일 03:00 KST(18:00 UTC)에 지운다
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cron') THEN
    PERFORM cron.schedule('marvia-purge-positions', '0 18 * * *', 'SELECT purge_old_positions()');
  END IF;
END
$$;
