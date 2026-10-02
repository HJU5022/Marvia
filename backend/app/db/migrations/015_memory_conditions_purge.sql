-- 화물 비서 기억 2단계: B/L 조건 칸, 확인 대기 값, 메모장 가득 참 표시, 끝난 화물 90일 정리 (docs/specs/memory.md, 10-02 결정).
--
-- 014가 만든 두 표에 칸을 더하고, 보관 함수 하나와 pg_cron 예약을 둔다. 방식은 008(조회 기록 90일)과 같다.
--
-- user_cargo에 더하는 칸
-- - original_bl: 원본 B/L이 필요한가. 'required'(원본 필요) / 'surrendered'(서렌더, 원본 불필요) / NULL(모름)
-- - to_order_bank: 수하인이 "TO ORDER OF ... BANK"(은행 지시식)인가. NULL은 모름
-- - freight_term: 운임 'prepaid'(선불) / 'collect'(착불) / NULL, incoterm: 'CIF' / 'FOB' / 'CFR' / NULL
--   세 조건은 판정 등급에 쓰지 않는다. 등급은 코드 판정 표가 정한다 (services/verdict.py). 비서가 짚을 거리로만 쓴다
--   (원본 필요 + 서렌더 아님 → 원본 B/L·은행 L/G 챙기기, 착불 → 반출 전에 운임 납부). 출처는 서류 사진(확인한 값)과 사용자
-- - pending: 대화에서 나온 화물 값 변경(set_cargo)을 바로 적용하지 않고 확인 대상으로 둔다 (Spec 쓰기 흐름 4).
--   모양: [{"field": "sale_due_date", "value": "2026-10-03", "noted_at": "2026-10-02"}]
-- user_memory에 더하는 칸
-- - full_at: 상한(3,000자)을 줄여도 넘어 새 기억을 저장하지 못한 시각 (Spec EC-06). 저장에 성공하거나 사용자가 지우면 NULL.
--   "메모장이 가득 찼어요, 정리해 주세요"를 저장된 척 없이 알리는 근거다
--
-- 보관 (Spec "보관과 크기"): 끝난(done) 화물은 완료 90일 뒤 잠긴 B/L과 세부 값을 지우고 한 줄 요약 재료만 남긴다.
-- 남기는 것: bl_masked, label, status, done_at, last_verdict, last_stage, last_checked_at (요약은 코드가 이 값으로 만든다,
-- services/cargo.py done_summary). LLM이 요약을 만들지 않는다. 틀린 기억이 영구히 남지 않게 하려는 것이다.
-- 그 화물에 달린 메모장 항목(걱정·할 일)은 이 함수가 지우지 않는다. 상한을 넘을 때 코드가 줄이는 순서에서 먼저 빠진다.

ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS original_bl TEXT
  CHECK (original_bl IN ('required', 'surrendered'));
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS to_order_bank BOOLEAN;
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS freight_term TEXT
  CHECK (freight_term IN ('prepaid', 'collect'));
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS incoterm TEXT
  CHECK (incoterm IN ('CIF', 'FOB', 'CFR'));
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS pending JSONB NOT NULL DEFAULT '[]';

-- status·vessel_source도 정해진 값만 받게 한다. 014에는 주석으로만 적혀 있었다
ALTER TABLE user_cargo DROP CONSTRAINT IF EXISTS user_cargo_status_check;
ALTER TABLE user_cargo ADD CONSTRAINT user_cargo_status_check CHECK (status IN ('active', 'done'));
ALTER TABLE user_cargo DROP CONSTRAINT IF EXISTS user_cargo_vessel_source_check;
ALTER TABLE user_cargo ADD CONSTRAINT user_cargo_vessel_source_check CHECK (vessel_source IN ('mrn', 'user'));

ALTER TABLE user_memory ADD COLUMN IF NOT EXISTS full_at TIMESTAMPTZ;

CREATE OR REPLACE FUNCTION purge_done_cargo(keep_days integer DEFAULT 90)
RETURNS integer
LANGUAGE sql
AS $$
  WITH gone AS (
    UPDATE user_cargo
    SET bl_encrypted = NULL,
        sale_due_date = NULL, sale_due_asked = false,
        forwarder_eta = NULL, forwarder_eta_noted_at = NULL,
        vessel_mmsi = NULL, voyage_no = NULL, vessel_source = NULL,
        last_days_margin = NULL, last_eta = NULL,
        original_bl = NULL, to_order_bank = NULL, freight_term = NULL, incoterm = NULL,
        pending = '[]',
        updated_at = now()
    WHERE status = 'done'
      AND done_at < now() - make_interval(days => keep_days)
      AND bl_encrypted IS NOT NULL
    RETURNING 1
  )
  SELECT count(*)::integer FROM gone;
$$;

-- 008과 같은 방식으로 예약한다. 위치 03:00, 조회 기록 03:10에 이어 03:20 KST(18:20 UTC).
-- Supabase에서는 pg_cron을 먼저 켜고 이 파일을 적용한다. 거꾸로 되면 아래 한 줄을 SQL 편집기에서 직접 실행한다.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cron') THEN
    PERFORM cron.schedule('marvia-purge-done-cargo', '20 18 * * *', 'SELECT purge_done_cargo()');
  END IF;
END
$$;
