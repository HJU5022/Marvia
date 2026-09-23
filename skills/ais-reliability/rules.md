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
---

# 1층 신호 7종

| id | 켜지는 조건 | 임계값 키 |
|---|---|---|
| position_stale | 마지막 수신이 임계 시간보다 오래됨 | position_stale_hours |
| eta_conflict | AIS ETA와 해수부 입항예정 차이가 임계 시간 초과 | eta_conflict_hours |
| anchor_wait | 부산 반경 안, 임계 속도 이하로 임계 시간 이상 정지 | busan_radius_nm, anchor_speed_kn, anchor_wait_hours |
| dest_changed | 목적지 코드가 비었거나 KRPUS가 아님 | 없음 |
| navstat_mismatch | 항해상태와 속도가 안 맞음 | 없음 |
| customs_hold | 통관 검사 지정·보류 | 없음 |
| sales_date_exceeded | days_margin < 0. 배가 정상이어도 판매 예정일을 넘김 | 없음 (0이 기준) |

# 상충 시 우선순위

priority 순서대로 첫 유효값을 신뢰 ETA로 쓴다: 해수부 실적 > 해수부 입항 예정 > AIS ETA > AIS 목적지 문자열.
AIS 목적지·ETA는 선원이 손으로 넣는 값이라 가장 자주 틀린다. 수집 데이터로 검증해 틀리면 이 순서를 고친다 (PRD 6.4).
