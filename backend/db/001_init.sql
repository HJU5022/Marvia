-- Converge 테이블 5개. 기준: docs/테이블정의서.md v2.1
-- 로컬(compose가 initdb로 자동 실행)과 Supabase(SQL Editor에 붙여넣기) 양쪽에 같은 파일.
-- FK는 results.session_id 하나만. 로그·피드백은 세션 삭제 후에도 집계에 남아야 해서 FK 없음.
-- sessions.user_id는 auth.users를 가리키지만 FK 없음 (로컬에는 auth 스키마가 없다).

-- gen_random_uuid()는 Postgres 13+ 내장. 확장 불필요.

-- 1. sessions — 대화 한 건. 공유 링크의 대상.
CREATE TABLE IF NOT EXISTS sessions (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  preset             text NOT NULL DEFAULT 'si_deploy',   -- ship_maintenance / si_deploy
  meet_at            timestamptz,                          -- 미정이면 NULL (임시 세션)
  purpose            text,
  destination_name   text,
  destination_lng    double precision,
  destination_lat    double precision,
  participants_enc   bytea NOT NULL,                       -- 참석자 목록 JSON 암호화
  participant_count  smallint NOT NULL,
  rendezvous_enc     bytea,                                -- 집결지 암호화. 없으면 NULL
  access             jsonb,                                -- {required, applied, lead_min}
  schedule_confirmed boolean,
  constraints        jsonb NOT NULL DEFAULT '[]',
  status             text NOT NULL DEFAULT 'draft',        -- draft / pins_confirmed / computed / failed
  user_id            uuid NOT NULL,                        -- 주선자 auth.users.id. FK 없음
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  expires_at         timestamptz NOT NULL                  -- 코드가 계산해 넣는다. 기본값 없음
);
CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions (expires_at);
CREATE INDEX IF NOT EXISTS sessions_user_created_idx ON sessions (user_id, created_at DESC);

-- 2. results — 세션의 계산 결과. 재질문마다 새 행.
CREATE TABLE IF NOT EXISTS results (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id            uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  candidates_enc        bytea NOT NULL,
  per_participant_enc   bytea NOT NULL,
  model_small           text,
  model_large           text,
  prompt_version        text,
  routed_to             text NOT NULL,                     -- small / large
  rendezvous_departure  text,                              -- "HH:MM"
  provisional           boolean NOT NULL DEFAULT false,
  trace_id              text,
  confidence            numeric(3,2),
  created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS results_session_created_idx ON results (session_id, created_at DESC);

-- 3. request_logs — 구조화 로그. 식별 정보 없음. FK 없음.
CREATE TABLE IF NOT EXISTS request_logs (
  id            bigserial PRIMARY KEY,
  request_id    uuid NOT NULL,
  session_id    uuid,
  stage         text NOT NULL,      -- slot_extract / vision / geocode / ... / judge / validate
  provider      text NOT NULL,      -- openrouter / local_gguf / kakao_local / kakao_mobility / tmap
  model_or_api  text,
  tokens_in     integer,
  tokens_out    integer,
  cost_usd      numeric(10,6),
  latency_ms    integer NOT NULL,
  status        text NOT NULL,      -- ok / retry / fallback / error
  error_type    text,               -- schema_violation / foreign_char / timeout / quota / auth / unknown
  retry_no      smallint NOT NULL DEFAULT 0,
  cache_hit     boolean NOT NULL DEFAULT false,
  routed_to     text,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS request_logs_created_idx ON request_logs (created_at);
CREATE INDEX IF NOT EXISTS request_logs_stage_status_idx ON request_logs (stage, status);
CREATE INDEX IF NOT EXISTS request_logs_session_idx ON request_logs (session_id);

-- 4. route_cache — 외부 API 응답 캐시. 좌표는 해시로만.
CREATE TABLE IF NOT EXISTS route_cache (
  cache_key     text PRIMARY KEY,   -- sha256(provider, 출발·도착 좌표 4자리, 이동수단, 시각 30분 단위)
  provider      text NOT NULL,
  response_enc  bytea NOT NULL,
  summary       jsonb,              -- {duration_sec, distance_m, transfer_count, fare}
  hit_count     integer NOT NULL DEFAULT 0,
  created_at    timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL   -- 경로 24시간, 지오코딩 30일
);
CREATE INDEX IF NOT EXISTS route_cache_expires_at_idx ON route_cache (expires_at);

-- 5. feedback — 사용자 선택 기록. FK 없음.
CREATE TABLE IF NOT EXISTS feedback (
  id                bigserial PRIMARY KEY,
  session_id        uuid NOT NULL,
  result_id         uuid NOT NULL,
  chosen_rank       smallint,          -- 1이 아니면 규칙 점검 신호
  edited_pin_count  smallint NOT NULL DEFAULT 0,
  re_ask_count      smallint NOT NULL DEFAULT 0,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS feedback_session_idx ON feedback (session_id);
