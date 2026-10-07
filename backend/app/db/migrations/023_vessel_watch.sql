-- B/L 없이 배(MMSI)만 지켜보기 (10-08 정운 실사용 57번).
--
-- 채팅에서 도착 검색 목록이나 후보 배를 보다가 "이 배 지켜볼래"를 누르면 사용자별로 한 줄을 만든다.
-- 화물 표(user_cargo, 017)에 억지로 넣지 않고 따로 둔 이유: user_cargo는 B/L 지문(cargo_key)이 열쇠이고 재판정·카카오톡 알림이
-- 그 줄을 읽는다. B/L이 없는 줄이 섞이면 재판정이 "B/L을 못 연다"로 실패하고 판정 변화 띠도 엉킨다. 기존 지켜보기는 그대로 둔다.
-- 판정도 통관도 없다. 배 이름·국적·목적지·도착 예정은 사용자가 채팅에서 본 값을 그대로 적은 글이고(dest, eta는 자유 문장),
-- 위치는 worker가 watch_positions(017)에 받아 두는 값을 같은 배 번호로 읽는다 (worker/collector.py SELECT_WATCHED).
-- 여러 번 실행해도 결과는 같다 (IF NOT EXISTS, OR REPLACE).

CREATE TABLE IF NOT EXISTS vessel_watch (
  user_id    TEXT NOT NULL,
  mmsi       BIGINT NOT NULL,
  name       TEXT NOT NULL,
  flag       TEXT,
  dest       TEXT,                          -- 채팅에 보인 목적지 글 그대로 (데이터로만 쓴다)
  eta        TEXT,                          -- 채팅에 보인 도착 예정 글 그대로
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, mmsi)               -- 같은 배를 두 번 켜도 한 줄
);

-- 005와 같다. 공개 키(Data API)로는 읽지 못하게 RLS를 켜고 규칙은 두지 않는다
ALTER TABLE vessel_watch ENABLE ROW LEVEL SECURITY;

-- 021의 보관 규칙에 "배만 지켜보는 배"를 더한다. 지켜보는 동안은 30일이 지나도 지도 경로를 남기고, 끄면 30일 뒤 지운다.
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
      AND NOT EXISTS (SELECT 1 FROM vessel_watch v WHERE v.mmsi = w.mmsi)
    RETURNING 1
  )
  SELECT count(*)::integer FROM gone;
$$;
