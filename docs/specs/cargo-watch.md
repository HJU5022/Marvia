# Spec: 감시·지도 (10-02, 1단계는 화면만)

## 무엇을
왼쪽 메뉴 "내 화물"을 드롭다운(화물 조회 `/`, 감시·지도 `/watch`)으로 만들고, 감시·지도에서 로그인 사용자의 모든 화물(user_cargo) B/L에 대해
배의 마지막 위치를 한 지도에 보여 준다. B/L마다 서로 다른 마커(색 + 글자 A, B, C…)를 쓰고, 마우스를 올리면
선명, 가린 B/L, 운송 화물 이름표, 판정, 통관 단계, 도착 예정, 위치 수신 시각이 뜬다.

## 결정 (10-02 사용자)
- 화물 등록: 로그인 사용자가 B/L을 조회하면 user_cargo에 자동 등록, 다시 조회하면 마지막 판정·위치 갱신
- 감시: 기존 수집 worker에 합쳐 6시간마다 user_cargo 배 위치를 positions에 저장. 지도는 저장된 마지막 위치만 읽는다 (지도를 열 때 ShipFinder를 부르지 않는다)
- 반출이 끝난 화물은 지도에서 빼고 개수만 알린다
- 운송 화물은 사용자가 붙인 이름표(user_cargo.label)만 보여 준다. UNI-PASS 품명은 저장·표시하지 않는다 (SDD 3.5)

## 단계
1. **화면 (지금)**: `web/components/WatchMap.tsx`, `web/app/watch/page.tsx`, 메뉴 드롭다운, 예시 데이터 `web/lib/fixtures/watch-map.json`(가공값).
   `getWatchList()`는 실제·데모 모두 예시를 돌려주고 화면에 "예시 화면"을 표시한다
2. **서버 (보류)**: ShipFinder 호출 한도가 소진돼(10-02 status 38 "The number of queries exceeded") 위치 수집을 할 수 없다.
   스케줄러는 켜지 않는다 (사용자 지시). 한도가 풀리면 진행한다
   - 조회 뒤 user_cargo 등록·갱신 (routers/agent.py `_logged` 근처)
   - worker 위치 수집 대상에 user_cargo 활성 배 추가 (worker/collector.py)
   - `GET /api/watch`: 사용자 화물과 마지막 위치. `getWatchList()`를 이 통로로 바꾸고 sample=false

## 같이 바꾼 것
- 왼쪽 메뉴를 아이콘만 보이게 줄였다. 마우스를 올리거나 키보드 초점을 주면 이름 말풍선이 뜬다. "내 화물"은 말풍선 대신 드롭다운이 뜬다
- 휴대폰 가로 메뉴는 드롭다운 대신 "화물 조회"와 "감시·지도"를 바로 펼쳐 6칸으로 보이고, 모든 칸을 아이콘 위·글자 아래로 맞췄다
