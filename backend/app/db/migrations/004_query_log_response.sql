-- 조회 결과 전체 저장 (작업 C-9 후속 질문, 09-27 결정).
--
-- 후속 질문은 같은 세션·같은 B/L의 가장 최근 결과를 꺼내 그 안에서만 답한다.
-- 그래서 query_log 한 줄에 AgentResponse 전체를 JSON으로 같이 남긴다.
-- AgentResponse에는 B/L 원본이 없다. 품명·중량·화주 정보도 없다 (SDD 3.5, 7절).
-- 로그인이 붙으면 session_id 자리를 사용자 ID로 쓴다 (SDD 7절: 지금은 session_id로 구분).

ALTER TABLE query_log ADD COLUMN IF NOT EXISTS response JSONB;

-- 후속 질문은 세션 + B/L별 최신 한 줄만 읽는다
CREATE INDEX IF NOT EXISTS query_log_session_bl_created_idx ON query_log (session_id, bl_masked, created_at DESC);
