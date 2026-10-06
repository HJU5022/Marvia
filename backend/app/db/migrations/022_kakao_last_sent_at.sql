-- 카카오톡 연결 표에 마지막 발송 시각 (10-06, 설정 화면 "마지막 발송").
--
-- 연결한 시각(linked_at)은 016에 이미 있다. 마지막으로 알림을 보낸 시각은 없어서 새 칸을 만든다.
-- services/kakao.send_to_user가 카카오가 받아들인 뒤에만 now()로 갱신한다 (실패한 시도는 적지 않는다).
-- 새 칸이라 기존 줄은 비어 있고, 다음 발송 때 채워진다. 여러 번 실행해도 결과는 같다 (IF NOT EXISTS).

ALTER TABLE kakao_links ADD COLUMN IF NOT EXISTS last_sent_at TIMESTAMPTZ;
