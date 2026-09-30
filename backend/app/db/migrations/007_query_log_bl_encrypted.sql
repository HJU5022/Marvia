-- 로그인 사용자의 B/L 원본을 잠가서 남기는 칸 (② 암호화, 09-30 결정).
--
-- 메모리("이 B/L 다시 볼까요?")가 다시 조회하려면 원본이 필요하다. bl_masked로는 못 한다.
-- 서버(backend/app/crypto.py)가 Fernet으로 잠근 글자만 들어온다. 열쇠는 DB에 없다(.env의 BL_ENCRYPTION_KEY).
-- 손님 조회와 열쇠가 없을 때는 비어 있다. 같은 값도 잠글 때마다 결과가 달라 이 칸으로는 검색하지 않는다(찾기는 bl_masked).
-- 보관은 90일 (09-30 결정). 자동 삭제는 삭제 단계에서 붙인다.

ALTER TABLE query_log ADD COLUMN IF NOT EXISTS bl_encrypted TEXT;
