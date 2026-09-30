-- 조회 기록 보관 기한 90일 (09-30 결정, 삭제 단계 1).
--
-- 근거: 개인정보보호법 제21조. 보유기간이 지나면 지체 없이, 복구·재생되지 않게 파기한다.
-- 1년 미이용 파기(유효기간제)는 2023.9.15 폐지돼 기간은 우리가 정한다. 수입 화물 한 건(선적→입항→통관→반출)이
-- 보통 몇 주라 다 끝나고도 넉넉하고, 메모리("이 B/L 다시 볼까요?")에도 충분해서 90일로 했다.
-- 로그인 사용자 줄(user_id, 잠긴 B/L)과 손님 줄을 가리지 않고 90일이 지나면 지운다.
--
-- 부르는 쪽은 위치 기록 삭제(002)와 같다. 규칙은 이 함수 하나에만 둔다.
--   Supabase(배포): pg_cron이 켜져 있으면 아래 DO 블록이 하루 한 번 실행을 등록한다
--   로컬·채점용 postgres:16: pg_cron이 없어 등록을 건너뛴다. 대신 워커가 실행마다 이 함수를 부른다

CREATE OR REPLACE FUNCTION purge_old_queries(keep_days integer DEFAULT 90)
RETURNS integer
LANGUAGE sql
AS $$
  WITH gone AS (
    DELETE FROM query_log
    WHERE created_at < now() - make_interval(days => keep_days)
    RETURNING 1
  )
  SELECT count(*)::integer FROM gone;
$$;

-- 이력 화면·메모리는 사용자·세션 인덱스를 쓴다. 삭제는 하루 한 번이라 created_at 인덱스를 따로 만들지 않는다

-- 예약은 위치 삭제(002)까지 같이 다시 등록한다. Supabase에 002가 적용된 09-27에는 pg_cron이 꺼져 있어
-- 위치 삭제 예약이 건너뛰어졌다(09-30 확인). 마이그레이션은 한 번만 돌므로 pg_cron을 나중에 켜도 저절로 안 생긴다.
-- cron.schedule은 같은 이름이면 덮어쓰므로 두 번 등록돼도 예약은 하나다.
-- 순서 주의: Supabase에서는 pg_cron을 먼저 켜고 이 파일을 적용해야 한다. 거꾸로 되면 아래 두 줄을 SQL 편집기에서 직접 실행한다.
DO $$
BEGIN
  -- cron 스키마가 있으면 pg_cron이 켜진 DB다. 위치 03:00 KST(18:00 UTC), 조회 기록 03:10 KST로 10분 띄운다
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cron') THEN
    PERFORM cron.schedule('marvia-purge-positions', '0 18 * * *', 'SELECT purge_old_positions()');
    PERFORM cron.schedule('marvia-purge-queries', '10 18 * * *', 'SELECT purge_old_queries()');
  END IF;
END
$$;
