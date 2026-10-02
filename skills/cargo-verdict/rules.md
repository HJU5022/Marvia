---
# 계약 C6. 2층 등급 판정 표의 재료. 코드(services/verdict.py)가 이 프론트매터를 읽는다 (SDD 3.6, 09-30 D7, 10-01).
# 키 하나는 skills/*/rules.md 중 한 파일에만 둔다. backend/app/services/rules.py가 모두 합쳐 읽고, 같은 키가 두 파일에 있으면 실패한다.
margin_act_days: 2
act_signals: [anchor_wait, customs_hold, sales_date_exceeded]
gray_signals: [anchor_wait, customs_hold]
ignore_signals: [navstat_mismatch]
ignore_dest_values: [broken, empty]
---

# 2층 등급 판정 표

코드(services/verdict.py)가 아래 키를 읽어 등급을 정한다. 등급을 정하는 곳은 여기와 그 코드뿐이다. SKILL.md는 등급을 정하지 않고 설명하는 법만 적는다.
신호(triggered·clear·unknown)는 ais-reliability/rules.md "1층 신호 7종" 표대로 코드가 먼저 정한다.

| 등급 | 조건 | 키 |
|---|---|---|
| act | act_signals 중 하나라도 켜짐. 또는 다른 신호가 켜졌는데 days_margin이 margin_act_days 미만 | act_signals, margin_act_days |
| watch | act_signals는 꺼져 있고 다른 신호가 하나라도 켜짐. 또는 켜진 신호가 없어도 days_margin이 margin_act_days 미만 | margin_act_days |
| fine | 켜진 신호 없음. unknown은 켜진 것으로 세지 않는다 | |

- 세지 않는 신호: ignore_signals는 켜져도 등급에 넣지 않는다. dest_changed는 값이 깨진 목적지(broken)·빈 목적지(empty)면 세지 않는다(ignore_dest_values). 배의 실제 상태가 아니라 AIS 입력 오류일 수 있어서다
- 회색 지대: gray_signals 중 unknown이 있으면 표가 등급을 낮게 낼 수 있다. 이때만 LLM이 표 등급 이상으로 올릴 수 있다 (낮추기 불가)
- 판매 예정일이 없으면 days_margin이 없어 여유 조건은 보지 않는다. 배 상태만으로 정한다
