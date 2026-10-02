---
# 계약 C6. 부산항 기준값의 원본. 코드는 이 프론트매터를 읽는다 (SDD 3.6, CLAUDE.md "임계값을 코드에 적지 않는다").
# 키 하나는 skills/*/rules.md 중 한 파일에만 둔다. backend/app/services/rules.py가 모두 합쳐 읽고, 같은 키가 두 파일에 있으면 실패한다 (10-01).
busan_ref: {lat: 35.10, lng: 129.05}
busan_radius_nm: 30
busan_port_code: KRPUS
---

# 부산항 기준값

| 키 | 뜻 | 읽는 곳 |
|---|---|---|
| busan_ref | 부산항 기준점(위도·경도). 남은 거리와 "부산 앞" 여부를 이 점에서 잰다 | services/signals.py (anchor_wait), mcp_server/tools/distance.py |
| busan_radius_nm | 기준점에서 이 해리 안이면 부산 앞으로 본다 | services/signals.py (anchor_wait) |
| busan_port_code | 부산항 UN/LOCODE. AIS 목적지 코드(dest_changed)와 UNI-PASS 양륙항(지원 범위 확인)을 이 값과 비교한다 | services/signals.py, routers/agent.py |
