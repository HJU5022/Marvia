# 0019. 지켜보기는 사용자가 켠 화물만, 사용자당 최대 5건으로 한다

상태: 채택

## 맥락
ShipFinder는 하루 50회 호출 한도가 있다. 한도를 넘으면 status 38("The number of queries exceeded")이 난다. 처음 spec은 "1단계 화면만, 서버는 보류"였다 (`docs/specs/cargo-watch.md`).

## 결정
- 지켜보기는 사용자가 직접 켠 화물만, 사용자당 최대 5건이다 (`services/watch/watch.py MAX_WATCH`). 모든 화물을 감시하면 ShipFinder 하루 한도와 LLM 비용이 사용자 모르게 나가기 때문이다.
- 지도는 저장된 위치만 읽는다. 지도를 열 때 ShipFinder를 부르지 않는다.
- 반출이 끝난 화물은 지도에서 빼고 켤 수도 없다(409).
- 주기 수집은 기본 꺼짐(`WORKER_SCHEDULE=off`, `WATCH_ENABLED` 기본 꺼짐)이다. 수집 주기는 계획의 3시간에서 6시간으로 바꿨다. ShipFinder 하루 50회 한도 때문이다 (SDD 5.10절).
- 수집이 꺼진 채에도 지도에 점이 생기도록 사용자가 조회, 재판정할 때 받은 위치를 한 점 남긴다.

## 대안
- 전체 화물 자동 감시: 위 한도와 비용 이유로 택하지 않았다.

## 결과
좋아진 것: 호출 한도와 LLM 비용이 사용자가 켠 범위 안에 있다. 대가: 주기 가동은 하지 않아 작업 리스트 D1, D2가 일부 완료(코드 완료, 주기 가동 안 함)다. 이메일, 푸시 알림은 만들지 않았고 카카오톡만 있다 (`docs/Marvia_PRD.md` 4절).

## 근거
- `docs/specs/cargo-watch.md` "결정", "구현 상태"
- `docs/Marvia_SDD.md` 5.10절, 5.18절
- `docs/Marvia_개발_작업_리스트.md` D1, D2 행
