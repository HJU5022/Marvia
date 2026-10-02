-- 화물 비서 기억 2단계: B/L 조건 칸, 확인 대기 값, 메모장 가득 참 표시, 삭제 표시, 끝난 화물 3년 보관 (docs/specs/memory.md, 10-02 결정).
--
-- 014가 만든 두 표에 칸을 더하고, 삭제 표시 표 하나, 보관 함수 하나와 pg_cron 예약을 둔다. 예약 방식은 008(조회 기록 90일)과 같다.
-- 아직 어디에도 적용하지 않은 파일이라 10-02 결정 D3(보관 규칙 변경)과 검증 지적(삭제 뒤 되살아남)에 맞춰 이 파일을 고쳤다.
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
-- user_forget (삭제 표시): 사용자가 메모장 전부 지우기·내 기록 삭제·탈퇴를 한 시각. 응답 뒤에 도는 기억 쓰기(services/memory.py
-- remember, LLM이 길면 1~2분)가 그 사이 삭제를 되살리지 않게, 시작 시각보다 늦은 삭제가 있으면 쓰지 않는다 (10-02 검증 지적 1).
-- - memo_deleted_at: 메모장을 지운 시각 (DELETE /api/memory, 내 기록 삭제, 탈퇴)
-- - cargo_deleted_at: 화물 표를 지운 시각 (내 기록 삭제, 탈퇴. 메모장 전부 지우기는 화물 표를 지우지 않는다, 결정 D2)
-- 사용자 ID 말고 다른 값은 없다. 뒤 작업보다 충분히 긴 하루가 지나면 정리 함수가 지운다.
--
-- 보관 (Spec "보관과 크기", 10-02 결정 D3): 끝난(done) 화물은 반출(done_at) 뒤 3년 동안 그대로 두고, 3년이 지나면 화물 줄 전체와
-- 그 화물에 달린 메모장 항목(걱정·할 일·화물별 거래처)을 함께 지운다. 이 사람에 대한 항목(선호·반복 일정·사람 단위 거래처)은 건드리지 않는다.
-- 3년 값은 아래 함수 기본값(keep_period) 한 곳에만 둔다. 처리방침에 "끝난 화물은 반출 후 3년 보관"으로 알린다.

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

CREATE TABLE IF NOT EXISTS user_forget (
  user_id TEXT PRIMARY KEY,
  memo_deleted_at TIMESTAMPTZ,
  cargo_deleted_at TIMESTAMPTZ
);
ALTER TABLE user_forget ENABLE ROW LEVEL SECURITY;  -- 005와 같은 이유

-- keep_period: 끝난 화물 보관 기간 (10-02 결정 D3, 반출 후 3년). 이 값을 바꿀 곳은 여기 한 곳이다.
-- forget_keep: 삭제 표시를 남겨 두는 기간. 뒤 작업(기억 쓰기) 하나가 끝나기에 충분히 길면 된다
CREATE OR REPLACE FUNCTION purge_done_cargo(keep_period interval DEFAULT interval '3 years',
                                            forget_keep interval DEFAULT interval '1 day')
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  removed integer;
BEGIN
  -- 한 문장 안에서 화물 줄을 지우고(gone), 그 화물에 달린 메모장 항목(화물별 칸)을 뺀다.
  -- 직전 버전(previous)에도 남지 않게 비운다
  WITH gone AS (
    DELETE FROM user_cargo
    WHERE status = 'done' AND done_at < now() - keep_period
    RETURNING user_id, cargo_key
  ), cleaned AS (
    UPDATE user_memory m
    SET items = COALESCE((
          SELECT jsonb_agg(i) FROM jsonb_array_elements(m.items) i
          WHERE NOT (i->>'section' = 'cargo'
                     AND i->>'cargo_key' IN (SELECT g.cargo_key FROM gone g WHERE g.user_id = m.user_id))
        ), '[]'::jsonb),
        previous = NULL,
        version = m.version + 1,
        updated_at = now()
    WHERE m.user_id IN (SELECT user_id FROM gone)
    RETURNING 1
  )
  SELECT count(*)::integer INTO removed FROM gone;

  DELETE FROM user_forget
  WHERE GREATEST(COALESCE(memo_deleted_at, '-infinity'), COALESCE(cargo_deleted_at, '-infinity')) < now() - forget_keep;

  RETURN removed;
END
$$;

-- 008과 같은 방식으로 예약한다. 위치 03:00, 조회 기록 03:10에 이어 03:20 KST(18:20 UTC). 하루 한 번이면 충분하다.
-- Supabase에서는 pg_cron을 먼저 켜고 이 파일을 적용한다. 거꾸로 되면 아래 한 줄을 SQL 편집기에서 직접 실행한다.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cron') THEN
    PERFORM cron.schedule('marvia-purge-done-cargo', '20 18 * * *', 'SELECT purge_done_cargo()');
  END IF;
END
$$;
