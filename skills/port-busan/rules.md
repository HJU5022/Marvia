---
# 계약 C6. 부산항 기준값의 원본. 코드는 이 프론트매터를 읽는다 (SDD 3.6, CLAUDE.md "임계값을 코드에 적지 않는다").
# 키 하나는 skills/*/rules.md 중 한 파일에만 둔다. backend/app/services/rules.py가 모두 합쳐 읽고, 같은 키가 두 파일에 있으면 실패한다 (10-01).
busan_ref: {lat: 35.10, lng: 129.05}
busan_radius_nm: 30
busan_port_code: KRPUS
# 해수부 입항 일정 조회 기간·선명 비교 기준 (mcp_server/tools/port_schedule.py가 읽는다, 10-06 점검)
port_schedule_lookback_days: 3
port_schedule_lookahead_days: 7
port_schedule_name_match_ratio: 0.85
---

# 부산항 기준값

| 키 | 뜻 | 읽는 곳 |
|---|---|---|
| busan_ref | 부산항 기준점(위도·경도). 남은 거리와 "부산 앞" 여부를 이 점에서 잰다 | services/signals.py (anchor_wait), mcp_server/tools/distance.py |
| busan_radius_nm | 기준점에서 이 해리 안이면 부산 앞으로 본다 | services/signals.py (anchor_wait) |
| busan_port_code | 부산항 UN/LOCODE. AIS 목적지 코드(dest_changed)와 UNI-PASS 양륙항(지원 범위 확인)을 이 값과 비교한다 | services/signals.py, routers/agent.py |
| port_schedule_lookback_days | 해수부 관제 실적(실제 입항·접안)을 오늘부터 며칠 전까지 볼지. get_port_schedule 기본값 | mcp_server/tools/port_schedule.py |
| port_schedule_lookahead_days | 해수부 입항 신고(입항 예정)를 오늘부터 며칠 뒤까지 볼지. 부산은 신고가 1주 앞까지 나온다 (09-23 실측). get_port_schedule 기본값 | mcp_server/tools/port_schedule.py |
| port_schedule_name_match_ratio | 선명으로만 찾을 때 이 비율 이상 닮은 이름을 같은 배로 본다 (difflib 유사도, 정확·부분 일치가 없을 때만) | mcp_server/tools/port_schedule.py |
