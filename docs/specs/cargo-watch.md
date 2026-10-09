# Spec: 지켜보는 화물 (감시·지도)

## 무엇을
왼쪽 메뉴 "내 화물"을 드롭다운(화물 조회 `/`, 지켜보는 화물 `/watch`)으로 만들고, `/watch`에서 사용자가 "지켜보기"를 켠 화물의 배 위치를 한 지도에 보여 준다.
B/L마다 서로 다른 마커(색 + 글자 A, B, C…)를 쓰고, 마우스를 올리면 화물 이름, 가린 B/L, 국적, 통관 단계, 도착 예정, 위치 수신 시각이 뜬다.
배마다 지나온 길(최근 위치 최대 12점, `services/watch/watch.py TRACK_POINTS`)을 그 배 색의 선으로 잇는다.

## 결정
- 화물 등록: 로그인 사용자가 B/L을 조회하면 `user_cargo`에 자동 등록되고, 다시 조회하면 마지막 판정·위치가 갱신된다 (`services/account/memory.py`, docs/specs/memory.md)
- 지켜보기는 사용자가 직접 켠 화물만, 사용자당 최대 5건 (`services/watch/watch.py MAX_WATCH`). 모든 화물을 감시하면 ShipFinder 하루 한도(50회)와 LLM 비용이 사용자 모르게 나가기 때문이다
- 지도는 저장된 위치만 읽는다 (지도를 열 때 ShipFinder를 부르지 않는다)
- 반출이 끝난 화물(`status = done`)은 지도에서 빼고 개수만 알린다. 지켜보기도 켤 수 없다 (409)
- 이름은 사용자가 붙인 이름표(`user_cargo.label`)를 우선 쓰고, 없으면 UNI-PASS 품명(`goods_name`, 020)을 쓴다. 판정 LLM에는 품명을 주지 않는다

## 구현 상태

| 항목 | 상태 | 위치 |
|---|---|---|
| 화면 | 구현. 실제 모드에서는 `GET /api/watch`를 읽고, 체험(데모) 모드에서는 예시 `web/lib/fixtures/watch-map.json`을 보여 주며 "예시 화면"으로 표시 | `web/components/WatchMap.tsx`, `web/app/watch/page.tsx`, `web/lib/api.ts getWatchList` |
| 켜기·끄기 버튼 | 구현. 결과 화면의 `WatchToggle` | `web/components/WatchToggle.tsx`, `PUT /api/cargo/watch`, `POST /api/cargo/watch/state` |
| 감시 목록 API | 구현 | `GET /api/watch` (`routers/watch.py`, `services/watch/watch.watch_list`) |
| 위치 저장 표 | `watch_positions` (017, 연구용 `positions`와 별도). 30일 지난 줄은 지키는 배를 빼고 지운다 (021) | docs/ERD.md |
| 위치가 쌓이는 길 1 | 사용자가 조회·재판정할 때 받은 위치를 한 점 남긴다 (`services/watch/cargo._keep_position`, 같은 보고 시각은 한 줄) | `backend/app/services/watch/cargo.py` |
| 위치가 쌓이는 길 2 | worker가 지켜보는 배(`user_cargo.watch`, active)의 위치를 받아 쌓는다. 위치를 가장 오래 못 받은 배부터, ShipFinder 실행 예산 안에서 | `worker/collector.py collect_watch_positions` |
| 주기 실행 | 기본 꺼짐. `WORKER_SCHEDULE=on`이면 `WORKER_INTERVAL_HOURS`(기본 6시간)마다 수집, `WATCH_ENABLED=on`이면 수집 뒤에 재판정 | `worker/run.py`, `.env.example` |
| 재판정과 알림 | 구현. 지켜보는 화물을 조회와 같은 판정 길로 다시 판정하고, 등급이 바뀌면 `changed_from·changed_at·change_seen`에 기록하고 카카오톡으로 알린다. 한 번에 5건(`RUN_LIMIT`), 위치를 알려 둔 배만 | `services/watch/watch.run_watch`, `worker/watch.py` |
| 안 본 변화 | 접속하면 띠로 보여 주고 "봤음"으로 바꾼다 | `GET /api/watch/changes`, `POST /api/watch/changes/seen` |

처음 Spec은 "1단계 화면만, 서버는 보류"였다. ShipFinder 호출 한도(status 38 "The number of queries exceeded") 때문에 위치 수집을 켜지 못했기 때문이다. 이후 서버 쪽이 만들어졌고, 주기 수집은 호출 한도 때문에 지금도 기본 꺼져 있다. 그래서 수집이 꺼진 채에도 지도에 점이 생기도록 조회할 때 위치를 남기는 길 1을 뒀다.

## 같이 바꾼 것
- 왼쪽 메뉴: 아이콘만 보이게 접을 수 있다. 접으면 마우스를 올리거나 키보드 초점을 줄 때 이름 말풍선이 뜬다. "내 화물"은 말풍선 대신 하위 메뉴(드롭다운)가 뜬다 (`web/components/Shell.tsx`, 개편 내용은 web/DESIGN.md)
- 휴대폰 화면은 가로 메뉴로 바뀐다

## 지도 바탕
지도 바탕은 `web/lib/basemap.ts`가 세 단계로 고른다: OpenFreeMap 벡터 타일(WebGL) → 미리 구워 둔 타일(`web/public/basemap`, `web/scripts/bake-basemap.mjs`) → Natural Earth 해안선(`drawLocalGeography`). 자세한 것은 web/README.md.

## 배 단위 지켜보기

- B/L 없이 배(MMSI)만 지켜보는 표 `vessel_watch`(마이그레이션 023)와 `GET·POST·DELETE /api/watch/vessels`를 더했다. 화물 표(`user_cargo`)에 넣지 않아 B/L 재판정·카카오톡 알림 경로에는 닿지 않고, 판정과 알림은 만들지 않았다. 워커는 같은 배 번호로 위치를 받는다 (실사용 57번, 커밋 `28e5dc5` `e3f37ba` `07a4441`)
- 채팅 에이전트에 `watch_vessel` 도구를 더했다. 후보 배를 채팅에서 바로 지켜보게 한다 (실사용 79번, 커밋 `d715999`, `00cb06a`)
- 같은 호출부호가 여러 척이면 선명이 같은 배, 그다음 최근 신호 배를 고르고(`vessel_pick.py`), 한도 소진은 503으로 알린다 (실사용 64·66번, 커밋 `5f24e99`)
