-- 카카오톡 알림 연결: 사용자별 카카오 토큰 (카카오톡 "나에게 보내기", 10-02).
--
-- 알림은 사용자가 화면을 보지 않을 때 보내므로, 연결할 때 카카오가 준 토큰을 서버가 보관해야 한다.
-- access 토큰은 약 12시간, refresh 토큰은 60일 산다 (카카오 로그인 REST API 문서). 만료 시각을 두어 갱신 시점을 안다.
-- 두 토큰은 서버(backend/app/crypto.py, Fernet, PII_ENCRYPTION_KEY)에서 잠근 글자만 들어온다. 원문은 이 표에 없다.
-- 카카오 토큰은 인증정보라 암호화해서 저장한다 (안전성 확보조치 기준 제7조).
-- 회원 정보(010 user_profiles)와 표를 나눈 이유: 카카오 연결은 회원 정보와 따로 생기고 따로 끊긴다.
-- 연결 해제·탈퇴하면 이 줄을 지운다.

CREATE TABLE IF NOT EXISTS kakao_links (
  user_id            TEXT PRIMARY KEY,
  access_token_enc   TEXT NOT NULL,
  refresh_token_enc  TEXT NOT NULL,
  access_expires_at  TIMESTAMPTZ NOT NULL,
  refresh_expires_at TIMESTAMPTZ NOT NULL,
  linked_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 005와 같다. 공개 키(Data API)로는 읽지 못하게 RLS를 켜고 규칙은 두지 않는다
ALTER TABLE kakao_links ENABLE ROW LEVEL SECURITY;
