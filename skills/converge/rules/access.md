---
# 출입 절차 규칙값. 코드(backend/app/domain/rules.py)가 이 프론트매터를 읽는다.
# 값을 바꾸려면 여기만 고친다. 코드에 숫자를 적지 않는다 (SDD 7절 원칙).
gate_lead_min: 20                       # 함정: 위병소 출입 절차 소요(분). 하정운 확인 필요
lobby_lead_min: 15                      # SI: 1층 보안서류 작성·인솔 소요(분)
rendezvous_is_procedure_start: true     # 합류 지점은 역이 아니라 절차가 시작되는 곳
switch_if_delay_min: 30                 # 도착이 이만큼 어긋나면 출입조치를 포기하고 부두 밖으로
outside_landmark_kinds:                 # 절차 밖에서 만날 때 쓰는 자리
  - 항만 입구
  - 역
  - 부대 정문 앞
no_procedure_all_transit_no_rendezvous: true  # 절차가 없고 전원 대중교통이면 합류 자체가 불필요
pier_requires_access_applied: true      # 부두 안은 출입조치를 신청해 둔 경우에만 후보가 된다
---
# 출입 절차

근거 사례: 진해 정기점검에서 역산 기준이 점검 시각이 아니라 위병소 도착 기한이었다. 위병소에서
신분 확인과 인솔을 받는 시간이 따로 들기 때문이다 (하정운). 여의도 야간 배포는 1층에서 보안서류를
쓰고 인솔을 기다린다 (김승욱).

## 값이 쓰이는 곳

| 키 | 어디서 | 무엇을 |
|---|---|---|
| `gate_lead_min` | 파이프라인 5·7단계 | 함정 프리셋에서 약속 시각 앞에 빼 두는 절차 소요 |
| `lobby_lead_min` | 같은 곳 | SI 프리셋에서 빼 두는 절차 소요 |
| `rendezvous_is_procedure_start` | 3단계 후보 생성 | 후보 1순위를 역이 아니라 위병소·로비로 잡는다 |
| `switch_if_delay_min` | 5단계 | 도착 어긋남이 이 값을 넘으면 부두 밖 랜드마크로 전환 판정 |
| `outside_landmark_kinds` | 3단계 | 전환했을 때 찾을 자리의 종류 |
| `no_procedure_all_transit_no_rendezvous` | 5단계 | 합류 지점을 만들지 말지 |
| `pier_requires_access_applied` | 5단계 | 출입조치 전이면 부두 후보의 `access_ok` 를 false 로 |

## 왜 절차 시작점인가

역에서 만나 같이 들어가려 해도, 출입 절차는 위병소나 1층에서 시작된다. 역 집결은 그 앞 단계일 뿐이라
계산 기준이 되지 못한다. 절차가 시작되는 자리를 기준으로 역산해야 늦지 않는다.

관련: docs/SDD.md 7절, 5절 5·7단계
