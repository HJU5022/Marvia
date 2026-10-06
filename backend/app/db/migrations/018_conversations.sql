-- 대화 목록 (ChatGPT·Claude식, 10-06 정운 결정). 로그인 사용자의 채팅 대화를 저장해 목록에서 다시 열 수 있게 한다.
--
-- 대화 번호(id)는 채팅 요청의 session_id다 (화면이 이미 보내는 글자). 사용자마다 따로 세므로 PK는 (user_id, id)다.
-- 사용자 말에는 B/L 원본과 전화번호가 섞일 수 있어 글·JSON 칸은 모두 서버가 PII 열쇠로 잠근 글자만 둔다
-- (crypto.encrypt_pii, 003~007 조회 기록과 같은 방식). 잠그지 못하면(열쇠 없음) 코드가 저장하지 않는다.
--
-- conversations: 대화 한 건당 한 줄
-- - title_enc: 제목. 처음엔 첫 사용자 말 앞 20자, LLM 제목이 만들어지면 바뀐다
-- - context_enc: 마지막 AgentRequest JSON, result_enc: 마지막 AgentResponse JSON (화면 오른쪽 칸을 다시 그리는 자료)
-- conversation_messages: 말풍선 한 줄. seq는 대화 안 순서(1부터), extra_enc는 답 말풍선의 화면 자료(선박 표·지도 등) JSON
-- - 대화당 마지막 200줄만 둔다. 넘으면 코드가 오래된 줄부터 지운다 (services/conversations.py)
-- 대화가 지워지면 말풍선도 같이 지워진다 (ON DELETE CASCADE). 탈퇴 때 지우기는 services/account.py가 부른다.
--
-- 보관 90일 (008과 같다): 마지막으로 대화한 때(updated_at)로부터 90일이 지난 대화를 지운다.
-- 규칙은 아래 함수 하나에만 둔다. Supabase는 pg_cron이 하루 한 번, pg_cron이 없는 로컬·채점용 DB는 워커가 실행마다 부른다.

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  title_enc TEXT,
  context_enc TEXT,
  result_enc TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, id)
);

CREATE TABLE IF NOT EXISTS conversation_messages (
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  text_enc TEXT NOT NULL,
  extra_enc TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, conversation_id, seq),
  FOREIGN KEY (user_id, conversation_id) REFERENCES conversations (user_id, id) ON DELETE CASCADE
);

-- 목록은 사용자별 최근 대화순이다. 90일 삭제는 하루 한 번이라 updated_at만의 인덱스는 따로 만들지 않는다
CREATE INDEX IF NOT EXISTS conversations_user_updated_idx ON conversations (user_id, updated_at DESC);

-- 005와 같다. 공개 키(Data API)로는 읽지 못하게 RLS를 켜고 규칙은 두지 않는다
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_messages ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION purge_old_conversations(keep_days integer DEFAULT 90)
RETURNS integer
LANGUAGE sql
AS $$
  WITH gone AS (
    DELETE FROM conversations
    WHERE updated_at < now() - make_interval(days => keep_days)
    RETURNING 1
  )
  SELECT count(*)::integer FROM gone;
$$;

-- 008과 같은 방식으로 예약한다. 위치 03:00, 조회 기록 03:10, 끝난 화물 03:20에 이어 03:30 KST(18:30 UTC).
-- Supabase에서는 pg_cron을 먼저 켜고 이 파일을 적용한다. 거꾸로 되면 아래 한 줄을 SQL 편집기에서 직접 실행한다.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cron') THEN
    PERFORM cron.schedule('marvia-purge-conversations', '30 18 * * *', 'SELECT purge_old_conversations()');
  END IF;
END
$$;
