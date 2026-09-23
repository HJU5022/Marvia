-- 조회 이력 (작업 A12, SDD 3.9 query_log · 4.4 GET /api/history).
--
-- /api/agent가 한 번 돌 때마다 한 줄 남긴다. 화면의 "조회 이력"이 이 표를 읽는다.
-- B/L 원본은 넣지 않는다. bl_masked(앞4자+****+뒤4자)만 남긴다 (SDD 3.5, 7절).
-- 개인정보와 화주 정보도 넣지 않는다.

CREATE TABLE IF NOT EXISTS query_log (
  id BIGSERIAL PRIMARY KEY,
  request_id TEXT,
  session_id TEXT NOT NULL,
  bl_masked TEXT,
  status TEXT,
  verdict TEXT,
  vessel_match TEXT,
  decided_by TEXT,
  retry_count SMALLINT,
  model TEXT,
  trace_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 이력 화면은 세션별 최신순으로만 읽는다
CREATE INDEX IF NOT EXISTS query_log_session_created_idx ON query_log (session_id, created_at DESC);
