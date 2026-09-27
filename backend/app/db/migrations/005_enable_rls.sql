-- 모든 표에 RLS(행 단위 보안)를 켠다. 규칙(policy)은 만들지 않는다 (09-27).
--
-- Supabase는 public 스키마의 표를 Data API(웹 창구)로 자동 공개한다. 이 창구는 공개 키(publishable key)로
-- 들어오는데, 공개 키는 프론트에 들어가 누구나 볼 수 있다. RLS가 꺼져 있으면 그 키만으로 조회 이력(query_log)
-- 등을 읽고 지울 수 있다. RLS를 켜고 규칙을 두지 않으면 창구로는 아무 줄도 보이지 않는다.
--
-- 백엔드·워커는 창구가 아니라 DATABASE_URL로 직접 붙는다. 표 주인 계정(Supabase의 postgres, 로컬 compose의 app)은
-- RLS를 적용받지 않으므로(FORCE를 쓰지 않음) 지금처럼 읽고 쓴다. 로컬·채점용 postgres에도 그대로 적용해도 된다.

ALTER TABLE targets ENABLE ROW LEVEL SECURITY;
ALTER TABLE positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE arrival_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE control_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE query_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY;
