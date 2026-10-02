-- 화물 비서 기억: 사용자별 화물 표(user_cargo)와 메모장(user_memory) (docs/specs/memory.md How, G4, 10-02).
--
-- Spec에는 "마이그레이션 009"로 적혀 있었지만 009는 이미 operators(009_operators.sql)가 쓰고 있어 014로 만든다.
-- 표만 만든다. 읽고 쓰는 코드, 완료 90일 뒤 bl_encrypted를 비우는 보관 함수·pg_cron은 아직 없다 (Spec 체크리스트).
--
-- user_cargo: 사용자가 조회한 화물 한 건당 한 줄.
-- - B/L 원본은 넣지 않는다. cargo_key는 HMAC(원본 B/L)로 같은 사용자 안에서 같은 화물을 찾는 데만 쓰고,
--   bl_masked는 가린 값(가운데 절반 *, SDD 3.5), bl_encrypted는 서버 Fernet 암호문(crypto.py, 007과 같은 방식)이다
-- - 마지막 판정 값(last_*)은 다음 조회 때 "지난번엔 지켜볼 것이었다"를 짚기 위한 요약이다
-- user_memory: 사용자당 한 줄. items는 종류가 정해진 항목 목록(JSONB)이고 마크다운은 코드가 만든다.
-- - version: 두 요청이 동시에 고칠 때 나중 것이 앞의 것을 덮지 않게 확인한다 (Spec EC-04)
-- - previous: 직전 버전. 잘못 고쳐졌을 때 되돌린다 (Spec EC-03)
-- 탈퇴하면 두 표의 그 사용자 줄을 지워야 한다 (services/account.py, 코드 연결은 아직).

CREATE TABLE IF NOT EXISTS user_cargo (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  cargo_key TEXT NOT NULL,
  bl_masked TEXT NOT NULL,
  bl_encrypted TEXT,
  bl_type TEXT NOT NULL,
  label TEXT,
  status TEXT NOT NULL DEFAULT 'active',  -- active / done
  sale_due_date DATE,
  sale_due_asked BOOLEAN NOT NULL DEFAULT false,
  forwarder_eta DATE,
  forwarder_eta_noted_at DATE,
  vessel_mmsi BIGINT,
  voyage_no TEXT,
  vessel_source TEXT,
  last_verdict TEXT,
  last_checked_at TIMESTAMPTZ,
  last_days_margin INTEGER,
  last_eta DATE,
  last_stage TEXT,
  done_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, cargo_key)
);

CREATE TABLE IF NOT EXISTS user_memory (
  user_id TEXT PRIMARY KEY,
  items JSONB NOT NULL DEFAULT '[]',
  version INTEGER NOT NULL DEFAULT 0,
  previous JSONB,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 005와 같다. 공개 키(Data API)로는 읽지 못하게 RLS를 켜고 규칙은 두지 않는다
ALTER TABLE user_cargo ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_memory ENABLE ROW LEVEL SECURITY;
