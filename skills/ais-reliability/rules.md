---
# 계약 C6. AIS 1층 신호 기준값의 원본. 코드는 이 프론트매터를 읽는다 (SDD 3.6, CLAUDE.md "임계값을 코드에 적지 않는다").
# 키 하나는 skills/*/rules.md 중 한 파일에만 둔다. backend/app/services/rules.py가 모두 합쳐 읽고, 같은 키가 두 파일에 있으면 실패한다 (10-01).
position_stale_hours: 6
eta_conflict_hours: 12
anchor_speed_kn: 0.5
anchor_wait_hours: 24
priority: [mof_actual, mof_planned, ais_eta, ais_dest]
# 항해상태 불일치 속도 기준 (services/signals.py가 읽는다)
navstat_moored_max_kn: 2.0
navstat_underway_min_kn: 0.3
---

# 1층 신호 7종

코드(services/signals.py)가 아래 키를 읽어 신호마다 triggered·clear·unknown을 정한다. 키가 다른 Skill 폴더에 있으면 괄호에 적었다.

| id | 켜지는 조건 | 임계값 키 |
|---|---|---|
| position_stale | 마지막 수신이 임계 시간보다 오래됨 | position_stale_hours |
| eta_conflict | AIS ETA와 해수부 입항예정 차이가 임계 시간 초과 | eta_conflict_hours |
| anchor_wait | 부산 반경 안, 임계 속도 이하로 임계 시간 이상 정지 | anchor_speed_kn, anchor_wait_hours, busan_radius_nm·busan_ref (port-busan/rules.md) |
| dest_changed | 목적지 코드가 비었거나 부산 항구 코드가 아님 | busan_port_code (port-busan/rules.md) |
| navstat_mismatch | 항해상태와 속도가 안 맞음: 정박·계류인데 기준보다 빠름, 또는 항해 중인데 기준보다 느림 | navstat_moored_max_kn, navstat_underway_min_kn |
| customs_hold | 통관 단계 이름에 기준 낱말이 들어감 (검사 지정·보류 등) | customs_hold_words (customs-stages/rules.md) |
| sales_date_exceeded | days_margin < 0. 배가 정상이어도 판매 예정일을 넘김 | 없음 (0이 기준) |

등급(fine·watch·act)은 이 신호들을 재료로 cargo-verdict/rules.md 키를 읽어 코드가 정한다.

# 상충 시 우선순위 (priority)

priority 순서대로 첫 유효값을 신뢰 ETA(trusted_eta)로 쓴다: 해수부 실적 > 해수부 입항 예정 > AIS ETA > AIS 목적지 문자열.
이 순서를 고르는 이유는 SKILL.md "출처 우선순위" 절에 있다. 수집 데이터로 검증해 틀리면 이 순서를 고친다 (PRD 6.4).
