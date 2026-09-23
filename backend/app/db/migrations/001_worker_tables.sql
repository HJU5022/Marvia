-- 수집 워커 테이블 (작업 D1·D2). 위치 스냅샷, 입항 신고 스냅샷, 관제 이벤트, 추적 대상.
--
-- positions는 SDD 3.9 그대로다.
-- SDD 3.9의 arrivals(한 척 한 줄) 대신 두 테이블로 나눴다 (09-23 결정, 위키 "문서와 달라진 점").
--   arrival_reports: 해수부 선박운항정보의 입항 신고를 조회할 때마다 남긴다. 입항 뒤 '최종' 신고가
--                    되면 예정 시각이 실제 시각으로 덮이고 API는 이력을 주지 않아서(09-23 실측),
--                    예정값은 우리가 미리 찍어 둬야 지연을 잴 수 있다.
--   control_events:  관제정보의 입항·투묘·양묘·접안·이안·출항 이벤트. 투묘→양묘 시간으로
--                    부산 앞 대기 기준을 실제 분포에서 정한다 (09-23 결정).
-- targets는 SDD 5.10의 worker/targets.json 대신 DB에 둔다. 컨테이너가 다시 떠도 남아야 해서다.
--
-- 같은 값을 두 번 넣지 않도록 유니크 인덱스를 둔다. NULL끼리는 서로 다르게 취급되므로
-- COALESCE로 빈 값을 채운 식에 인덱스를 건다. 워커는 INSERT ... ON CONFLICT DO NOTHING으로 넣는다.

CREATE TABLE IF NOT EXISTS positions (
  id BIGSERIAL PRIMARY KEY,
  mmsi INTEGER NOT NULL,
  ts TIMESTAMPTZ NOT NULL,          -- last_time (선박 보고 시각)
  fetched_at TIMESTAMPTZ NOT NULL,
  lat DOUBLE PRECISION, lng DOUBLE PRECISION,
  sog REAL, cog REAL, navistat SMALLINT,
  dest TEXT, destcode TEXT, ais_eta TIMESTAMPTZ,
  raw JSONB NOT NULL                -- 실제 응답 원본. DB에만 두고 레포에 올리지 않는다 (ShipFinder 약관)
);
CREATE INDEX IF NOT EXISTS positions_mmsi_ts ON positions (mmsi, ts DESC);
-- 같은 보고 시각을 다시 받으면 새 정보가 아니다
CREATE UNIQUE INDEX IF NOT EXISTS positions_mmsi_ts_uq ON positions (mmsi, ts);

CREATE TABLE IF NOT EXISTS arrival_reports (
  id BIGSERIAL PRIMARY KEY,
  call_sign TEXT,
  ship_name TEXT NOT NULL,
  ship_kind TEXT,
  stage TEXT,                       -- reqstSeNm: 최초/변경/최종
  arrival_at TIMESTAMPTZ,           -- etryptDt. 최종이면 실제 입항 시각에 가깝다
  facility TEXT,                    -- laidupFcltyNm, 신고한 선석 또는 박지
  mrn TEXT,                         -- mrNum, 입항 적하목록 관리번호
  fetched_at TIMESTAMPTZ NOT NULL   -- 이 값을 처음 본 시각
);
-- 신고 내용이 바뀌었을 때만 새 줄이 생긴다. 그래서 줄을 시간순으로 보면 예정 변경 이력이 된다
CREATE UNIQUE INDEX IF NOT EXISTS arrival_reports_uq ON arrival_reports (
  COALESCE(call_sign, ''), COALESCE(mrn, ''), COALESCE(stage, ''),
  COALESCE(arrival_at, 'epoch'::timestamptz), COALESCE(facility, '')
);
CREATE INDEX IF NOT EXISTS arrival_reports_call_sign ON arrival_reports (call_sign, fetched_at);

CREATE TABLE IF NOT EXISTS control_events (
  id BIGSERIAL PRIMARY KEY,
  call_sign TEXT,
  ship_name TEXT NOT NULL,
  kind TEXT NOT NULL,               -- cntrlNm: 입항/접안/이안/투묘/양묘/출항
  at TIMESTAMPTZ NOT NULL,          -- cntrlOpertDt
  facility TEXT,                    -- fcltyNm. 박지면 묘박, 선석이면 접안
  fetched_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS control_events_uq ON control_events (COALESCE(call_sign, ''), kind, at);

CREATE TABLE IF NOT EXISTS targets (
  call_sign TEXT PRIMARY KEY,       -- 해수부와 ShipFinder를 잇는 값
  mmsi INTEGER,                     -- ShipFinder 검색으로 찾은 값. 못 찾으면 NULL로 두고 위치는 안 받는다
  ship_name TEXT,
  planned_at TIMESTAMPTZ,           -- 선정할 때 본 입항 예정
  selected_at TIMESTAMPTZ NOT NULL
);
