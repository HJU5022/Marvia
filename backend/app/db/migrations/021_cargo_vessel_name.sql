-- 내 화물 표에 선명·국적 칸 (10-06 오후, 감시 목록 GET /api/watch).
--
-- 새 화면의 감시 목록 한 줄은 [등급 색 점] B/L · 선명 · 품명 · 입항 예정일이다 (위키 Marvia-프론트-개편 결정).
-- 지금까지 화물 표에는 배 번호(vessel_mmsi)만 있고 이름·국적이 없어서 목록에 선명을 보여 줄 수 없었다.
-- 조회 응답의 확정된 배(C1 vessel.name, vessel.flag)를 그대로 적는다. flag는 UNI-PASS shipNat 우선이다 (schemas/agent.py VesselInfo).
-- 새 칸이라 기존 줄은 비어 있고, 다음 조회 때 채워진다. 여러 번 실행해도 결과는 같다 (IF NOT EXISTS).

ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS vessel_name TEXT;
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS vessel_flag TEXT;
