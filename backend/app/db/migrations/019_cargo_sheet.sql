-- 내 화물 현황 표와 엑셀 받기 (10-06 정운 결정, 아버지가 손으로 쓰는 관리표 기준).
--
-- 화주는 신용장(L/C) 개설일·번호, B/L 번호, 출항·입항·입고 날짜를 한 줄씩 직접 적어 관리한다.
-- 신용장 하나에 B/L이 여러 개 붙는다(실제 표에서 2~6개). 그래서 신용장은 따로 표(user_lc)로 두고
-- 화물 표(014 user_cargo) 줄이 lc_id로 그 신용장을 가리킨다.
-- - user_lc: 사용자가 은행에서 연 신용장. 번호와 개설일은 사용자가 직접 넣는다(Marvia가 알 길이 없다)
-- - departed_on / departed_source: 출항일. UNI-PASS·해수부에는 해외 항구 출항 날짜가 없어서(연계가이드 v4.1 확인)
--   사용자가 넣거나(manual) 포워더 도착 통지서 사진의 ETD에서 읽는다(document)
-- - arrived_on: 실제 입항 신고된 날. UNI-PASS 이력 '입항보고 수리' 처리일 (아버지 기준 "입항신고된 날")
-- - warehoused_on: 창고에 들어간 날. UNI-PASS 이력 '반입신고' 처리일
-- - forwarder_name / carrier_name / container_no: UNI-PASS frwrEntsConm·shcoFlco·cntrNo (10-06 추가, 전에는 버리던 칸)
-- 새 칸이라 기존 줄은 비어 있고, 다음 조회 때 채워진다. 여러 번 실행해도 결과는 같다 (IF NOT EXISTS).
-- 신용장 번호는 B/L과 달리 UNI-PASS 조회 열쇠가 아니라서 암호화하지 않는다. 대신 RLS를 켜고 서버만 읽는다(014와 같다).

CREATE TABLE IF NOT EXISTS user_lc (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  lc_no TEXT NOT NULL CHECK (char_length(lc_no) BETWEEN 1 AND 35),  -- 길이 35는 services/cargo_sheet.LC_NO_MAX와 같다
  opened_on DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, lc_no)
);
ALTER TABLE user_lc ENABLE ROW LEVEL SECURITY;

ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS lc_id BIGINT REFERENCES user_lc(id) ON DELETE SET NULL;  -- 신용장을 지워도 화물 줄은 남는다
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS departed_on DATE;
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS departed_source TEXT CHECK (departed_source IN ('manual', 'document'));  -- manual: 사용자가 넣음 / document: 도착 통지서 사진에서 읽음
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS arrived_on DATE;
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS warehoused_on DATE;
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS forwarder_name TEXT;
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS carrier_name TEXT;
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS container_no TEXT;
