# 0019. 지켜보기는 사용자가 켠 화물만, 사용자당 최대 5건으로 한다

상태: 채택

## 맥락
ShipFinder는 하루 50회 호출 한도가 있다. 넘으면 status 38("The number of queries exceeded")이 난다. 화물을 다시 판정할 때마다 LLM 비용도 든다. 처음 spec은 "1단계 화면만, 서버는 보류"였다. 호출 한도 때문에 위치 수집을 켜지 못해서였다.

## 결정
- 지켜보기는 사용자가 직접 켠 화물만, 사용자당 최대 5건이다 (`services/watch/watch.py MAX_WATCH`). 배 한 척 단위 지켜보기도 같은 값으로 따로 세어 최대 5척이다 (`services/watch/vessel_watch.py`).
- 지도는 저장된 위치만 읽는다. 지도를 열 때 ShipFinder를 부르지 않는다.
- 주기 수집은 기본 꺼짐(`WORKER_SCHEDULE=off`, `WATCH_ENABLED` 빈 값)이다. 켜면 6시간마다 돈다. 계획은 3시간이었으나 ShipFinder 하루 50회 한도 때문에 바꿨다 ([SDD](../Marvia_SDD.md) "부록. 계획 대비 변경" 표 워커 주기 행).
- 세부 규칙(반출 끝난 화물 409, 조회 때 받은 위치를 지도 점으로 남기기)은 [specs/cargo-watch.md](../specs/cargo-watch.md)에 있다.

## 대안
- 모든 화물 자동 감시: ShipFinder 하루 한도와 LLM 비용이 사용자 모르게 나가서 택하지 않았다.

## 결과
- 좋아진 것: 호출 한도와 LLM 비용이 사용자가 켠 범위 안에 있다.
- 대가: 운영 worker는 주기 수집과 자동 재판정이 꺼진 채 한 번만 실행한다 ([release_manifest.json](../release_manifest.json) `deploy.worker`). 알림은 카카오톡만 있고 이메일, 푸시는 만들지 않았다 ([PRD 4절](../Marvia_PRD.md)).

## 근거
- [specs/cargo-watch.md](../specs/cargo-watch.md)
- [SDD](../Marvia_SDD.md) 5.10절, 5.18절
- `.env.example` `WORKER_SCHEDULE`, `WORKER_INTERVAL_HOURS`, `WATCH_ENABLED`
