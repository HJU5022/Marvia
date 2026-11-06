-- 감시 목록 (계획 3d, 설계 1절 "출항부터 반출까지 지켜본다"). 여러 번 돌려도 결과가 같다(IF NOT EXISTS).
-- [주의] 실제 화물 번호는 이 표에 평문으로 두지 않는다 (설계 8절, R-033). 앱이 암호화(Fernet)한 값만 넣고,
--        서버 코드(marvia.watch)가 다시 조회할 때만 푼다. LLM·트레이스에는 토큰만 넘긴다 (설계 12절)
CREATE TABLE IF NOT EXISTS watches (
    id bigserial PRIMARY KEY,
    user_id text NOT NULL,
    number_enc text NOT NULL, -- Fernet 토큰. 키는 MARVIA_WATCH_KEY
    number_hash text NOT NULL, -- 키가 있는 HMAC-SHA256 16진수. 같은 번호 검사에만 쓴다
    stage text NOT NULL DEFAULT '', -- 마지막으로 본 통관 단계. 모르면 빈 글
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, number_hash) -- [왜] 암호문은 넣을 때마다 달라서 해시로 같은 화물을 가린다
);

-- 다시 조회해 단계가 바뀐 기록. 다음 대화 처음에 보여 주면 seen을 참으로 바꾼다
CREATE TABLE IF NOT EXISTS watch_events (
    id bigserial PRIMARY KEY,
    watch_id bigint NOT NULL REFERENCES watches (id) ON DELETE CASCADE,
    old_stage text NOT NULL,
    new_stage text NOT NULL,
    found_at timestamptz NOT NULL DEFAULT now(),
    seen boolean NOT NULL DEFAULT false
);
