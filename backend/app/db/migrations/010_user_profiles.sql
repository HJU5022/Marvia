-- 회원 정보: 이름, 전화번호, 주소 (docs/specs/user-profile.md, 10-01).
--
-- 세 값은 서버(backend/app/crypto.py, Fernet)에서 잠근 글자만 들어온다. 원문은 이 표에 없다.
-- 잠근 글자는 같은 값이어도 매번 달라서 검색·정렬에 쓸 수 없다. 이 표는 user_id로만 찾는다.
-- consent_at: 수집·이용 동의 시각 (개인정보보호법 제15조). 동의 없이는 저장하지 않으므로 NOT NULL.
-- 탈퇴하면 이 줄도 지운다 (services/account.py).

CREATE TABLE IF NOT EXISTS user_profiles (
  user_id     TEXT PRIMARY KEY,
  name_enc    TEXT NOT NULL,
  phone_enc   TEXT NOT NULL,
  address_enc TEXT NOT NULL,
  consent_at  TIMESTAMPTZ NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 005와 같다. 공개 키(Data API)로는 읽지 못하게 RLS를 켜고 규칙은 두지 않는다
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
