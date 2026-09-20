---
# 이동·여유 규칙값. 코드(backend/app/domain/rules.py)가 이 프론트매터를 읽는다.
# 값을 바꾸려면 여기만 고친다. 코드에 숫자를 적지 않는다 (SDD 7절 원칙).
buffer_client_min: 20            # 고객사·현장 방문의 여유(분). 지각이 신뢰 문제인 자리
buffer_deploy_min: 15            # 배포·인솔의 여유(분). 인솔 시각 10~20분 전 도착
car_traffic_pct: 15              # 자동차 소요에 얹는 정체 여유(%)
car_traffic_min_min: 10          # 정체 여유의 최소값(분)
car_traffic_rush_pct: 25         # 출퇴근 시간대의 정체 여유(%)
transit_transfer_extra_min: 10   # 환승이 있으면 더 얹는 시간(분)
luggage_requires_car: true       # 장비·짐이 있으면 대중교통으로 보내지 않는다
pickup_wait_min: 5               # 태우는 지점에서 기다리는 시간(분)
pickup_counts_from_board: true   # 태워지는 사람의 소요시간은 탑승 이후 구간만
max_pickup_per_car: 1            # 차 한 대당 픽업 한 명. 다중 픽업 순서 최적화는 범위 밖
route_cache_ttl_hours: 24        # 경로 응답을 캐시에 두는 시간. 길이 하루 뒤에는 달라진다
geocode_cache_ttl_hours: 720     # 지오코딩 응답을 캐시에 두는 시간(30일). 장소 좌표는 잘 안 바뀐다
---
# 이동과 여유

근거 사례: 마곡 방문에서 지도 앱이 55분이라 했는데 환승 대기까지 더해 실제로는 더 걸렸다. 그래서
환승이 있으면 따로 얹는다. 고객사 미팅 지각은 신뢰 문제라 여유를 더 크게 잡는다 (김승욱).

## 값이 쓰이는 곳

| 키 | 어디서 | 무엇을 |
|---|---|---|
| `buffer_client_min` | 5·7단계 | 함정 정비와 고객사 미팅의 여유 |
| `buffer_deploy_min` | 5·7단계 | 야간 배포의 여유 |
| `car_traffic_pct`·`car_traffic_min_min`·`car_traffic_rush_pct` | 5단계 | 자동차 소요에 얹는 정체분 |
| `transit_transfer_extra_min` | 5단계 | 환승 1회 이상이면 더한다 |
| `luggage_requires_car` | 5단계 | `constraints` 에 luggage 가 있으면 이동수단 판단에 쓴다 |
| `pickup_wait_min` | 4·5단계 | 운전자 경로에 태우는 시간 |
| `pickup_counts_from_board` | 4단계 | 태워지는 사람 경로를 탑승 지점부터 계산 |
| `max_pickup_per_car` | 4단계 | 한 대가 여러 명을 태우는 경우는 다루지 않는다 |
| `route_cache_ttl_hours` | `services/routes.py` | 같은 구간을 다시 물을 때 API 대신 캐시를 쓴다 |
| `geocode_cache_ttl_hours` | `services/geo.py` | 지오코딩 캐시 보관 시간 |

## 여유는 왜 따로 두나

경로 API 값은 "지금 길이 이렇다"는 예측이다. 늦으면 안 되는 자리일수록 그 예측만 믿을 수 없다.
여유를 소요시간에 섞지 않고 따로 두는 이유는, 화면에서 "경로 38분 + 여유 20분"처럼 근거를 나눠
보여 주기 위해서다 (docs/SDD.md 4절 ParticipantResult).

관련: docs/SDD.md 7절, 5절 4·5·7단계
