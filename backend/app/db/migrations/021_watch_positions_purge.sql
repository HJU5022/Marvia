-- 감시·지도 위치 기록(017 watch_positions) 보관 기한 (10-06 점검: 017에는 삭제 규칙이 없어 계속 쌓였다).
--
-- 기한은 연구용 위치 기록(002 purge_old_positions)과 같은 30일이다. 다만 기준 시각이 다르다.
-- 002는 targets와 해수부 입항 실적으로 "입항 30일 뒤"를 잰다. watch_positions의 배(user_cargo.vessel_mmsi)는 targets에
-- 없을 수 있어 입항 시각을 모른다. 그래서 "더 지켜보지 않는 배의, 보고 시각(ts)이 30일 지난 줄"을 지운다.
--   - 지금 지켜보는 진행 중 화물(user_cargo watch, status active)의 배는 기간과 상관없이 남긴다. 지도가 그 배의 경로를 그린다
--   - 지켜보기를 끄거나 반출이 끝나면 워커가 더 받지 않으므로(worker/collector.py SELECT_WATCHED) 마지막 보고 30일 뒤면 다 지워진다
-- 규칙은 이 함수 하나에만 둔다. Supabase는 pg_cron이 하루 한 번, pg_cron이 없는 로컬·채점용 DB는 워커가 실행마다 부른다
-- (backend/app/db purge_watch_positions, worker/run.py). 여러 번 불러도 결과는 같다.

CREATE OR REPLACE FUNCTION purge_old_watch_positions(keep_days integer DEFAULT 30)
RETURNS integer
LANGUAGE sql
AS $$
  WITH gone AS (
    DELETE FROM watch_positions w
    WHERE w.ts < now() - make_interval(days => keep_days)
      AND NOT EXISTS (
        SELECT 1 FROM user_cargo c
        WHERE c.vessel_mmsi = w.mmsi AND c.watch AND c.status = 'active'
      )
    RETURNING 1
  )
  SELECT count(*)::integer FROM gone;
$$;

-- 008·018과 같은 방식으로 예약한다. 위치 03:00, 조회 기록 03:10, 끝난 화물 03:20, 대화 03:30에 이어 03:40 KST(18:40 UTC).
-- Supabase에서는 pg_cron을 먼저 켜고 이 파일을 적용한다. 거꾸로 되면 아래 한 줄을 SQL 편집기에서 직접 실행한다.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cron') THEN
    PERFORM cron.schedule('marvia-purge-watch-positions', '40 18 * * *', 'SELECT purge_old_watch_positions()');
  END IF;
END
$$;
