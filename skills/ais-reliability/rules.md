---
# 계약 C6. 1층 신호 임계값의 원본. 코드는 이 프론트매터를 읽는다 (SDD 3.6, CLAUDE.md "임계값을 코드에 적지 않는다").
position_stale_hours: 6
eta_conflict_hours: 12
anchor_speed_kn: 0.5
anchor_wait_hours: 24
busan_radius_nm: 30
margin_act_days: 2
busan_ref: {lat: 35.10, lng: 129.05}
priority: [mof_actual, mof_planned, ais_eta, ais_dest]
# 1층 신호 기준 (services/signals.py가 읽는다)
navstat_moored_max_kn: 2.0
navstat_underway_min_kn: 0.3
customs_hold_words: [검사, 보류, 정지, 반송, 폐기]
# 2층 등급 판정 표 (services/verdict.py가 읽는다, 10-01)
act_signals: [anchor_wait, customs_hold, sales_date_exceeded]
gray_signals: [anchor_wait, customs_hold]
ignore_signals: [navstat_mismatch]
ignore_dest_values: [broken, empty]
---

# 1층 신호 7종

| id | 켜지는 조건 | 임계값 키 |
|---|---|---|
| position_stale | 마지막 수신이 임계 시간보다 오래됨 | position_stale_hours |
| eta_conflict | AIS ETA와 해수부 입항예정 차이가 임계 시간 초과 | eta_conflict_hours |
| anchor_wait | 부산 반경 안, 임계 속도 이하로 임계 시간 이상 정지 | busan_radius_nm, anchor_speed_kn, anchor_wait_hours |
| dest_changed | 목적지 코드가 비었거나 KRPUS가 아님 | 없음 |
| navstat_mismatch | 항해상태와 속도가 안 맞음: 정박·계류인데 기준보다 빠름, 또는 항해 중인데 기준보다 느림 | navstat_moored_max_kn, navstat_underway_min_kn |
| customs_hold | 통관 단계 이름에 기준 낱말이 들어감 (검사 지정·보류 등) | customs_hold_words |
| sales_date_exceeded | days_margin < 0. 배가 정상이어도 판매 예정일을 넘김 | 없음 (0이 기준) |

# 2층 등급 판정 표

코드(services/verdict.py)가 아래 키를 읽어 등급을 정한다. 등급을 정하는 곳은 여기와 그 코드뿐이다. SKILL.md는 등급을 정하지 않고 설명하는 법만 적는다.

| 등급 | 조건 | 키 |
|---|---|---|
| act | act_signals 중 하나라도 켜짐. 또는 다른 신호가 켜졌는데 days_margin이 margin_act_days 미만 | act_signals, margin_act_days |
| watch | act_signals는 꺼져 있고 다른 신호가 하나라도 켜짐. 또는 켜진 신호가 없어도 days_margin이 margin_act_days 미만 | margin_act_days |
| fine | 켜진 신호 없음. unknown은 켜진 것으로 세지 않는다 | |

- 세지 않는 신호: ignore_signals는 켜져도 등급에 넣지 않는다. dest_changed는 값이 깨진 목적지(broken)·빈 목적지(empty)면 세지 않는다(ignore_dest_values). 배의 실제 상태가 아니라 AIS 입력 오류일 수 있어서다
- 회색 지대: gray_signals 중 unknown이 있으면 표가 등급을 낮게 낼 수 있다. 이때만 LLM이 표 등급 이상으로 올릴 수 있다 (낮추기 불가)
- 판매 예정일이 없으면 days_margin이 없어 여유 조건은 보지 않는다. 배 상태만으로 정한다

# 상충 시 우선순위

priority 순서대로 첫 유효값을 신뢰 ETA로 쓴다: 해수부 실적 > 해수부 입항 예정 > AIS ETA > AIS 목적지 문자열.
AIS 목적지·ETA는 선원이 손으로 넣는 값이라 가장 자주 틀린다. 수집 데이터로 검증해 틀리면 이 순서를 고친다 (PRD 6.4).
