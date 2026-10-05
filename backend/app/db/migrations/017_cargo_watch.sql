-- 화물 지켜보기 (G5 등록·감시·알림, 10-05 결정, docs/Marvia_개발_작업_리스트.md).
--
-- 사용자가 결과 화면에서 "지켜보기"를 누른 화물만 워커가 주기적으로 다시 판정한다. 그래서 새 표를 만들지 않고
-- 화물 표(014 user_cargo)에 칸 네 개만 더한다. 판정 요약(last_*)과 B/L 잠근 값이 이미 그 줄에 있어서다.
-- - watch: 지켜보는 화물인가. 기본은 꺼짐. 사용자당 최대 5건은 코드(services/watch.py)가 지킨다
-- - changed_from: 가장 최근에 바뀐 판정의 이전 등급(fine / watch / act). 바뀐 뒤 등급은 last_verdict다
-- - changed_at: 그 변화를 감지한 시각
-- - change_seen: 사용자가 바뀐 판정을 화면에서 봤는가. 바뀌면 false, 화면이 확인하면 true.
--   기본이 true인 이유: 기존 줄과 변화가 없는 줄이 "안 본 변화"로 보이면 안 된다
-- 새 칸이라 기존 줄의 값은 그대로이고, 여러 번 실행해도 결과는 같다 (IF NOT EXISTS).
-- 표가 같아서 RLS(014)와 탈퇴 때 지우기(services/cargo.delete_all)도 그대로 적용된다.

ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS watch BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS changed_from TEXT;
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS changed_at TIMESTAMPTZ;
ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS change_seen BOOLEAN NOT NULL DEFAULT true;
