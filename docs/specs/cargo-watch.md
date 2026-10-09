# Spec: 지켜보는 화물 (감시·지도)

관련: [ADR 0019](../adr/0019-watch-user-opt-in-limit.md) (사용자가 켠 화물만 지켜보는 이유), [SDD 5.18](../Marvia_SDD.md)

## 현재 동작

- 지켜보기는 두 종류다. **화물 단위**는 B/L로 조회한 화물에 켜고, 재판정과 카카오톡 알림까지 한다. **배 단위**는 B/L 없이 배(MMSI)만 켜고, 위치만 쌓는다
- `/watch`(사이드바 "화물" 묶음의 "감시 화물")는 지켜보는 화물의 배 위치를 한 지도에 보여 준다. B/L마다 다른 마커(색 + 글자 A, B, C…)를 쓰고, 마우스를 올리면 화물 이름, 가린 B/L, 국적, 통관 단계, 도착 예정, 위치 수신 시각이 뜬다
- 배마다 지나온 길(최근 위치 최대 12점, `services/watch/watch.py TRACK_POINTS`)을 그 배 색의 선으로 잇는다
- 주기 수집과 재판정은 기본 꺼져 있다. ShipFinder 스타터 키가 하루 50회라서 개발 중에 계속 돌면 한도를 넘기 때문이다 (`worker/run.py` 모듈 설명). 그래도 지도에 점이 생기도록, 사용자가 조회할 때 받은 위치를 한 점씩 남긴다

## 결정

| 규칙 | 이유 | 위치 |
|---|---|---|
| 로그인 사용자가 B/L을 조회하면 `user_cargo`에 자동 등록되고, 다시 조회하면 마지막 등급(코드 이름 verdict)과 위치가 갱신된다 | 화물 목록을 따로 입력하지 않게 한다 | `services/watch/cargo.py`, [memory.md](memory.md) |
| 지켜보기는 사용자가 직접 켠 화물만, 사용자당 최대 5건 | 모든 화물을 감시하면 ShipFinder 하루 한도(50회)와 LLM 비용이 사용자 모르게 나간다 | `services/watch/watch.py MAX_WATCH`, `RUN_LIMIT` 주석 |
| 지도는 저장된 위치만 읽는다 | 지도를 열 때마다 ShipFinder를 부르지 않는다 | `services/watch/watch.watch_list` |
| 반출이 끝난 화물(`status = done`)은 지도에서 빼고 개수만 알린다. 지켜보기도 켤 수 없다(409) | 더 볼 위치가 없다 | `routers/watch.py _ERRORS` |
| 이름은 사용자가 붙인 이름표(`user_cargo.label`)를 먼저 쓰고, 없으면 UNI-PASS 품명(`goods_name`, `020_goods_name.sql`)을 쓴다. 판정 LLM에는 품명을 주지 않는다 | 판정에 품명이 필요 없다 ([SDD 3.5](../Marvia_SDD.md)) | `services/llm_config.py JUDGE_CUSTOMS_EXCLUDE` |

## 구성

| 동작 | 위치 |
|---|---|
| 지도 화면. 실제 모드는 `GET /api/watch`를 읽고, 체험(데모) 모드는 예시 `web/lib/fixtures/watch-map.json`을 "예시 화면"으로 표시한다 | `web/components/WatchMap.tsx`, `web/app/watch/page.tsx`, `web/lib/api.ts getWatchList` |
| 켜기·끄기 버튼(결과 화면의 `WatchToggle`) | `web/components/WatchToggle.tsx`, `PUT /api/cargo/watch`, `POST /api/cargo/watch/state` |
| 감시 목록 API | `GET /api/watch` (`routers/watch.py`, `services/watch/watch.watch_list`) |
| 위치 저장 표 `watch_positions` (`017_watch_positions.sql`). 연구용 `positions`와 따로 둔다. 지금 지켜보는 진행 중 화물의 배를 빼고, 보고 시각이 30일 지난 줄을 지운다 (`021_watch_positions_purge.sql`) | [ERD.md](../ERD.md) |
| 위치가 쌓이는 길 1: 사용자가 조회·재판정할 때 받은 위치를 한 점 남긴다. 같은 보고 시각은 한 줄 | `services/watch/cargo._keep_position` |
| 위치가 쌓이는 길 2: worker가 지켜보는 배(`user_cargo.watch`이고 active, 또는 `vessel_watch`)의 위치를 받아 쌓는다. 위치를 가장 오래 못 받은 배부터, ShipFinder 실행 예산 안에서 | `worker/collector.py collect_watch_positions`, `SELECT_WATCHED` |
| 주기 실행: 기본 꺼짐. `WORKER_SCHEDULE=on`이면 `WORKER_INTERVAL_HOURS`(기본 6)시간마다 수집하고, `WATCH_ENABLED=on`이면 수집 뒤에 재판정한다 | `worker/run.py`, `.env.example` |
| 재판정과 알림: 지켜보는 화물을 조회와 같은 판정 길(`routers/agent._assess`)로 다시 판정한다. 등급이 바뀌면 `changed_from`, `changed_at`, `change_seen`에 기록하고 카카오톡으로 알린다. 한 번에 5건(`RUN_LIMIT`). `worker/run.py`가 부를 때는 배를 아는 화물만 다시 판정한다(`known_vessel_only`) | `services/watch/watch.run_watch`, `worker/watch.py` |
| 안 본 변화: 접속하면 띠로 보여 주고 "봤음"으로 바꾼다 | `GET /api/watch/changes`, `POST /api/watch/changes/seen` |
| 배 단위 지켜보기: 표 `vessel_watch` (`023_vessel_watch.sql`)와 `GET·POST·DELETE /api/watch/vessels`. 화물 표(`user_cargo`)에 넣지 않아 재판정·카카오톡 알림 경로에 닿지 않는다. 판정과 알림은 없다. worker는 같은 배 번호로 위치를 받는다 | `routers/watch.py`, `worker/collector.py` |
| 채팅 에이전트 도구 `watch_vessel`: 채팅에서 본 후보 배를 바로 지켜보게 한다 | `services/chat/tools.py` |
| 호출부호만 오면 ShipFinder 검색으로 MMSI를 정한다. 여러 척이면 선명이 같은 배, 그다음 최근 신호 배. 한 척도 없으면 422, 검색 실패와 하루 한도 소진은 503(안내문이 다르다) | `services/watch/vessel_pick.py`, `routers/watch.py` |

## 화면 틀과 지도 바탕

## 배 단위 지켜보기

- B/L 없이 배(MMSI)만 지켜보는 표 `vessel_watch`(마이그레이션 023)와 `GET·POST·DELETE /api/watch/vessels`를 더했다. 화물 표(`user_cargo`)에 넣지 않아 B/L 재판정·카카오톡 알림 경로에는 닿지 않고, 판정과 알림은 만들지 않았다. 워커는 같은 배 번호로 위치를 받는다 (실사용 57번, 커밋 `28e5dc5` `e3f37ba` `07a4441`)
- 채팅 에이전트에 `watch_vessel` 도구를 더했다. 후보 배를 채팅에서 바로 지켜보게 한다 (실사용 79번, 커밋 `d715999`, `00cb06a`)
- 같은 호출부호가 여러 척이면 선명이 같은 배, 그다음 최근 신호 배를 고르고(`vessel_pick.py`), 한도 소진은 503으로 알린다 (실사용 64·66번, 커밋 `5f24e99`)
- 감시 지도에서 배만 지켜보는 배는 화물과 같은 동그라미 알파벳 핀(화물 다음 글자)으로 그리고 같은 클러스터로 묶는다. 판정이 없어 흰 바탕 회색 점선 핀이고, 클러스터 테두리 판정색에는 들어가지 않으며, 오른쪽 내 화물 목록에는 넣지 않는다(지도 아래 `WatchedVessels` 목록에 따로). 실사용 69번의 방향 화살표를 바꿨다 (`web/components/WatchMap.tsx` Spot, 커밋 `ec506b6` `b93ba50`)
