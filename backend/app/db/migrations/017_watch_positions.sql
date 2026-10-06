-- 감시·지도용 선박 위치 이력 (docs/specs/cargo-watch.md, 10-02).
--
-- worker가 실행될 때마다(스케줄러가 켜지면 6시간마다) user_cargo의 진행 중 화물 배(vessel_mmsi) 위치를 받아 한 줄씩 쌓는다.
-- 감시·지도 화면은 배마다 이 줄들을 시각 순으로 이어 경로(작은 동그라미 + 선)를 그린다.
-- positions(연구용 대상 선박, 001)와 따로 둔다. 사용자 화물 감시는 대상과 보존 기간이 달라 섞지 않는다.
-- ShipFinder 응답 원본(raw)과 목적지 자유 문장(dest)은 넣지 않는다. 지도에 필요 없고, 원본은 약관상 줄이는 게 낫다.
-- 지금은 스케줄러가 꺼져 있고(ShipFinder 호출 한도, 10-02) user_cargo를 채우는 코드도 없어 비어 있다.

CREATE TABLE IF NOT EXISTS watch_positions (
  id         BIGSERIAL PRIMARY KEY,
  mmsi       BIGINT NOT NULL,            -- user_cargo.vessel_mmsi
  ts         TIMESTAMPTZ NOT NULL,       -- 배가 보고한 시각 (ShipFinder last_time)
  fetched_at TIMESTAMPTZ NOT NULL,       -- worker가 받아 온 시각
  lat        DOUBLE PRECISION NOT NULL,
  lng        DOUBLE PRECISION NOT NULL,
  sog        REAL,                       -- 속력(노트)
  cog        REAL,                       -- 진행 방향(도)
  navistat   SMALLINT,                   -- AIS 항해 상태 코드
  UNIQUE (mmsi, ts)                      -- 같은 보고를 두 번 받아도 한 줄
);

-- 화면이 배마다 최근 경로를 시각 순으로 읽는다
CREATE INDEX IF NOT EXISTS watch_positions_mmsi_ts ON watch_positions (mmsi, ts DESC);

-- 005와 같다. 공개 키(Data API)로는 읽지 못하게 RLS를 켜고 규칙은 두지 않는다
ALTER TABLE watch_positions ENABLE ROW LEVEL SECURITY;
