# Marvia DB ERD

표는 21개다(마이그레이션 기록 표 `schema_migrations` 포함). 정의는 `backend/app/db/migrations/`의 파일 27개(번호 001~023)에 있고, 이 문서는 그 파일 기준이다.

## 기본 규칙

| 항목 | 내용 | 근거 |
|---|---|---|
| 적용 | 서버(`backend/app/main.py`)와 worker가 뜰 때 `db.apply_migrations`가 파일 이름 순서대로 한 번씩 적용한다. 전체를 pg advisory lock으로 감싸고 파일 하나를 한 트랜잭션으로 묶어, 두 프로세스가 동시에 떠도 같은 파일을 두 번 적용하지 않는다 | `backend/app/db/__init__.py`, SDD 3.9 |
| 같은 번호 파일 | 016(kakao_links, token_usage), 017(cargo_watch, watch_positions), 018(conversations, db_cleanup), 021(cargo_vessel_name, watch_positions_purge). 파일 이름 전체 순서로 적용한다 | `ls backend/app/db/migrations` |
| DB | Supabase Postgres(운영·개발)와 compose의 로컬 postgres | `docker-compose.yml` |
| RLS | 21개 표 모두 RLS(행 단위 보안)를 켜고 규칙(policy)은 두지 않는다. Supabase는 표를 Data API로 자동 공개하는데, 프론트에 들어가는 공개 키로는 이렇게 하면 아무 줄도 보이지 않는다. 백엔드와 worker는 `DATABASE_URL`로 표 주인 계정에 직접 붙어 RLS를 받지 않는다 | `005_enable_rls.sql`, 이후 표를 만드는 파일마다 같은 줄 |
| pg_cron | 오래된 줄 지우기 함수는 모든 DB에 만든다. 하루 한 번 예약은 pg_cron이 있는 DB(Supabase)에서만 등록하고, 없는 DB(로컬 postgres)는 건너뛴다 | 002, 008, 015, 018, 021의 `cron.schedule` |
| 외래 키 | 두 곳뿐이다. `conversation_messages`→`conversations`(018, 대화를 지우면 말풍선도 함께), `user_cargo.lc_id`→`user_lc`(019, 신용장을 지워도 화물 줄은 남기려고 SET NULL). 그림의 나머지 선은 같은 값으로 이어 읽는 논리 연결이다 | 018, 019 |
| user_id | Supabase 로그인 사용자 ID(UUID 글자). 사용자 표 자체는 Supabase Auth(`auth.users`)에 있다 | |

## 그림

그림에는 칸을 일부만 그렸다. 전체 칸은 아래 절의 표에 있다. FK라고 적은 두 선만 외래 키다.

```mermaid
erDiagram
    targets ||--o{ positions : "mmsi"
    targets ||--o{ arrival_reports : "call_sign"
    targets ||--o{ control_events : "call_sign"
    AUTH_USERS ||--o{ query_log : "user_id"
    AUTH_USERS ||--o| user_profiles : "user_id"
    AUTH_USERS ||--o| suspended_users : "user_id"
    AUTH_USERS ||--o{ user_cargo : "user_id"
    AUTH_USERS ||--o| user_memory : "user_id"
    AUTH_USERS ||--o| user_forget : "user_id"
    AUTH_USERS ||--o| kakao_links : "user_id"
    AUTH_USERS ||--o{ conversations : "user_id"
    AUTH_USERS ||--o{ user_lc : "user_id"
    AUTH_USERS ||--o{ admin_actions : "target_user_id"
    AUTH_USERS ||--o{ vessel_watch : "user_id"
    user_lc ||--o{ user_cargo : "lc_id (FK)"
    user_cargo }o--o{ watch_positions : "vessel_mmsi = mmsi"
    vessel_watch }o--o{ watch_positions : "mmsi"
    conversations ||--o{ conversation_messages : "(user_id, id) (FK)"

    targets { text call_sign PK
              int mmsi
              text ship_name
              timestamptz planned_at
              timestamptz selected_at }
    positions { bigserial id PK
                int mmsi
                timestamptz ts
                timestamptz fetched_at
                float lat
                float lng
                real sog
                real cog
                smallint navistat
                text dest
                text destcode
                timestamptz ais_eta
                jsonb raw }
    vessel_watch { text user_id PK
                   bigint mmsi PK
                   text name
                   text flag
                   text dest
                   text eta
                   timestamptz created_at
                   timestamptz updated_at }
    watch_positions { bigserial id PK
                      bigint mmsi
                      timestamptz ts
                      timestamptz fetched_at
                      float lat
                      float lng
                      real sog
                      real cog
                      smallint navistat }
    arrival_reports { bigserial id PK
                      text call_sign
                      text ship_name
                      text ship_kind
                      text stage
                      timestamptz arrival_at
                      text facility
                      text mrn
                      timestamptz fetched_at }
    control_events { bigserial id PK
                     text call_sign
                     text ship_name
                     text kind
                     timestamptz at
                     text facility
                     timestamptz fetched_at }
    query_log { bigserial id PK
                text request_id
                text session_id
                text user_id
                text bl_masked
                text bl_encrypted
                text status
                text verdict
                text vessel_match
                text decided_by
                text trace_id
                jsonb response
                timestamptz created_at }
    user_profiles { text user_id PK
                    text name_enc
                    text phone_enc
                    text address_enc
                    timestamptz consent_at
                    timestamptz created_at
                    timestamptz updated_at }
    user_cargo { bigserial id PK
                 text user_id
                 text cargo_key
                 text bl_masked
                 text bl_encrypted
                 text bl_type
                 text label
                 text goods_name
                 text status
                 boolean watch
                 bigint lc_id FK
                 bigint vessel_mmsi
                 text last_verdict
                 timestamptz last_checked_at }
    user_lc { bigserial id PK
              text user_id
              text lc_no
              date opened_on }
    user_memory { text user_id PK
                  jsonb items
                  int version
                  jsonb previous
                  timestamptz full_at
                  timestamptz updated_at }
    user_forget { text user_id PK
                  timestamptz memo_deleted_at
                  timestamptz cargo_deleted_at }
    kakao_links { text user_id PK
                  text access_token_enc
                  text refresh_token_enc
                  timestamptz access_expires_at
                  timestamptz refresh_expires_at
                  timestamptz last_sent_at }
    conversations { text id PK
                    text user_id PK
                    text title_enc
                    text context_enc
                    text result_enc
                    timestamptz updated_at }
    conversation_messages { text user_id PK
                            text conversation_id PK
                            int seq PK
                            text role
                            text text_enc
                            text extra_enc
                            timestamptz created_at }
    token_usage { text owner PK
                  date day PK
                  int tokens
                  timestamptz updated_at }
    suspended_users { text user_id PK
                      text suspended_by
                      text reason
                      timestamptz suspended_at }
    operators { text email_hash PK
                text email_enc
                text email_masked
                text granted_by
                timestamptz granted_at
                text revoked_by
                timestamptz revoked_at }
    operator_audit { bigserial id PK
                     text action
                     text actor_user_id
                     text target_email_enc
                     text target_email_masked
                     text actor_email_enc
                     text actor_email_masked
                     timestamptz created_at }
    admin_actions { bigserial id PK
                    text action
                    text target_user_id
                    text target_email_masked
                    text actor_user_id
                    text actor_email_enc
                    text actor_email_masked
                    text reason
                    timestamptz created_at }
```

`schema_migrations`는 그림에 넣지 않았다(5절).

## 표 한눈에

쓰는 곳과 읽는 곳은 레포 코드(backend/app, worker, mcp_server, scripts)의 SQL 기준이다. 경로는 `backend/app/` 아래면 앞을 줄였다.

| 절 | 표 | 쓰는 곳 | 읽는 곳 |
|---|---|---|---|
| 1 | targets | worker/collector.py | worker/collector.py, `purge_old_positions` |
| 1 | positions | worker/collector.py | db `recent_positions`(정박 대기 신호, ts·lat·lng·sog만), worker |
| 1 | watch_positions | worker/collector.py, services/watch/vessel_watch.py | services/watch/watch.py, cargo.py, vessel_watch.py |
| 1 | vessel_watch | services/watch/vessel_watch.py (routers/watch.py `/api/watch/vessels`와 채팅이 부른다) | 같은 서비스, worker/collector.py |
| 1 | arrival_reports | worker/collector.py | 없음 (서비스는 해수부 API를 실시간으로 부른다) |
| 1 | control_events | worker/collector.py | `purge_old_positions`만 (서비스는 해수부 API를 실시간으로 부른다) |
| 2 | query_log | routers/agent.py `_logged` (db `log_query`) | db `recent_queries`(이력 화면), `latest_response`(후속 질문), 탈퇴 삭제 |
| 3 | user_profiles | services/account/profile.py | profile.py, 운영자 고객 목록, scripts/ops/rekey_personal_data.py |
| 3 | user_cargo | services/watch/cargo.py(services/account/memory.py가 `cargo.upsert_assessment`로 부른다), cargo_sheet.py, watch.py | 같은 서비스, worker/collector.py(지켜보는 배 찾기) |
| 3 | user_lc | services/watch/cargo_sheet.py | cargo_sheet.py, cargo.py |
| 3 | user_memory | services/account/memory.py | services/account/memory.py |
| 3 | user_forget | services/account/memory.py | services/account/memory.py, `purge_done_cargo` |
| 3 | kakao_links | services/watch/kakao.py | services/watch/kakao.py |
| 3 | token_usage | services/account/quota.py | services/account/quota.py |
| 3 | conversations, conversation_messages | services/chat/conversations.py | 같은 서비스(routers/conversations.py가 부른다), 탈퇴 삭제 |
| 3 | suspended_users | services/account/customers.py | auth.py(요청마다 확인), 고객 목록 |
| 4 | operators | services/account/operators.py | 운영자 판단, 운영자 목록 |
| 4 | operator_audit | services/account/operators.py | 운영자 화면 이력 |
| 4 | admin_actions | services/account/customers.py | 운영자 화면 이력 |
| 5 | schema_migrations | db/__init__.py | db/__init__.py |

## 1. 선박 수집 (worker가 쓴다, SDD 5.10)

### targets: 위치를 받을 대상 선박 (001)
| 칸 | 타입 | 설명 |
|---|---|---|
| call_sign | TEXT PK | 호출부호. 해수부 입항 신고와 ShipFinder 위치를 잇는 값 |
| mmsi | INTEGER | 선박 무선 식별 번호. ShipFinder 검색으로 찾는다. 못 찾으면 NULL이고 위치를 받지 않는다 |
| ship_name | TEXT | 선명 |
| planned_at | TIMESTAMPTZ | 대상으로 고를 때 본 부산 입항 예정 시각 |
| selected_at | TIMESTAMPTZ NOT NULL | 대상으로 고른 시각 |

### positions: 선박 위치 이력 (001, 002)
| 칸 | 타입 | 설명 |
|---|---|---|
| id | BIGSERIAL PK | 줄 번호 |
| mmsi | INTEGER NOT NULL | 어느 배의 위치인지. `targets.mmsi`와 같은 값(외래 키 아님) |
| ts | TIMESTAMPTZ NOT NULL | 배가 위치를 보고한 시각 (ShipFinder last_time). (mmsi, ts)는 중복 없음 |
| fetched_at | TIMESTAMPTZ NOT NULL | 우리가 받아 온 시각 |
| lat, lng | DOUBLE PRECISION | 위도, 경도 |
| sog | REAL | 속력(노트) |
| cog | REAL | 진행 방향(도) |
| navistat | SMALLINT | AIS 항해 상태 코드 (0 항해 중, 1 정박, 5 계류 등) |
| dest | TEXT | 배가 밝힌 목적지 원문. 아무 글이나 쓸 수 있어 LLM에 넘기지 않는다 (SDD 7절) |
| destcode | TEXT | 목적지 항구 코드 (예: KRPUS) |
| ais_eta | TIMESTAMPTZ | 배가 보낸 도착 예정 시각 |
| raw | JSONB NOT NULL | ShipFinder 응답 원본. DB에만 두고 레포에 올리지 않는다 (약관) |

인덱스: `positions_mmsi_ts (mmsi, ts DESC)`, 유니크 `positions_mmsi_ts_uq (mmsi, ts)` (같은 보고 시각을 다시 받아도 한 줄).
입항 30일이 지난 배의 위치는 `purge_old_positions()`가 지운다 (002, pg_cron `marvia-purge-positions`, 매일 18:00 UTC). 002 적용 때 pg_cron이 꺼져 있던 DB를 위해 008이 같은 이름으로 다시 등록한다.

### watch_positions: 지켜보는 배의 위치 (017_watch_positions, 021_watch_positions_purge, 023_vessel_watch)
지켜보기를 켠 화물(`user_cargo.watch`가 true이고 `status`가 active)과 배만 지켜보기(`vessel_watch`)의 배 위치다. 연구용 `positions`와 따로 둔다. worker가 ShipFinder에서 받아 쌓고(`collect_watch_positions`), 배만 지켜보기 서비스도 같은 문장으로 넣는다(`services/watch/vessel_watch.py` `INSERT_POSITION`). API(`services/watch/watch.py`, `cargo.py`)가 지도에 그린다 (docs/specs/cargo-watch.md).
| 칸 | 타입 | 설명 |
|---|---|---|
| id | BIGSERIAL PK | 줄 번호 |
| mmsi | BIGINT NOT NULL | 배. `user_cargo.vessel_mmsi`, `vessel_watch.mmsi`와 같은 값 |
| ts | TIMESTAMPTZ NOT NULL | 배가 위치를 보고한 시각. (mmsi, ts)는 UNIQUE |
| fetched_at | TIMESTAMPTZ NOT NULL | 받아 온 시각 |
| lat, lng | DOUBLE PRECISION NOT NULL | 위도, 경도 |
| sog, cog | REAL | 속력(노트), 진행 방향(도) |
| navistat | SMALLINT | AIS 항해 상태 코드 |

인덱스: `watch_positions_mmsi_ts (mmsi, ts DESC)`. `positions`와 달리 dest·ais_eta·raw는 저장하지 않는다.
30일이 지난 줄은 `purge_old_watch_positions()`가 지운다. 지켜보는 진행 중 화물의 배와 `vessel_watch`에 있는 배는 남긴다. 021이 처음 만들고 023이 `vessel_watch` 조건을 더해 다시 정의했다 (pg_cron `marvia-purge-watch-positions`, 매일 18:40 UTC).

### vessel_watch: B/L 없이 배만 지켜보기 (023_vessel_watch)
채팅의 도착 검색 목록이나 후보 배에서 "이 배 지켜볼래"를 누르면 사용자별로 한 줄이 생긴다. 판정도 통관도 없다. `user_cargo`에 넣지 않은 이유: `user_cargo`는 B/L 지문(cargo_key)이 열쇠이고 재판정·카카오톡 알림이 그 줄을 읽어서, B/L 없는 줄이 섞이면 재판정이 실패한다.
| 칸 | 타입 | 설명 |
|---|---|---|
| user_id | TEXT NOT NULL | 로그인 사용자 ID. PRIMARY KEY (user_id, mmsi)라 같은 배를 두 번 켜도 한 줄 |
| mmsi | BIGINT NOT NULL | 배 번호 |
| name | TEXT NOT NULL | 선명. 사용자가 채팅에서 본 값 |
| flag | TEXT | 국적 |
| dest | TEXT | 채팅에 보인 목적지 글 그대로 (자유 문장, 데이터로만 쓴다) |
| eta | TEXT | 채팅에 보인 도착 예정 글 그대로 (자유 문장) |
| created_at, updated_at | TIMESTAMPTZ NOT NULL | 만든 시각, 고친 시각 |

### arrival_reports: 해수부 입항 신고 (001)
| 칸 | 타입 | 설명 |
|---|---|---|
| id | BIGSERIAL PK | 줄 번호 |
| call_sign | TEXT | 호출부호 |
| ship_name | TEXT NOT NULL | 선명 |
| ship_kind | TEXT | 선박 종류 |
| stage | TEXT | 신고 구분 (최초, 변경, 최종) |
| arrival_at | TIMESTAMPTZ | 신고한 입항 일시. 최종 신고면 실제 입항 시각에 가깝다 |
| facility | TEXT | 신고한 선석 또는 박지 |
| mrn | TEXT | 입항 적하목록 관리번호. UNI-PASS 화물관리번호 앞 11자리와 같아 배를 특정한다 |
| fetched_at | TIMESTAMPTZ NOT NULL | 이 값을 처음 본 시각 |

유니크 인덱스 `arrival_reports_uq (call_sign, mrn, stage, arrival_at, facility)`, 빈 값은 COALESCE로 채운다. 신고 내용이 바뀔 때만 새 줄이 생겨, 시간순으로 보면 예정 변경 이력이 된다. 보조 인덱스 `arrival_reports_call_sign (call_sign, fetched_at)`.

### control_events: 해수부 관제 실적 (001)
| 칸 | 타입 | 설명 |
|---|---|---|
| id | BIGSERIAL PK | 줄 번호 |
| call_sign | TEXT | 호출부호 |
| ship_name | TEXT NOT NULL | 선명 |
| kind | TEXT NOT NULL | 관제 종류 (입항, 접안, 이안, 투묘, 양묘, 출항) |
| at | TIMESTAMPTZ NOT NULL | 관제 일시 |
| facility | TEXT | 시설. 박지면 묘박, 선석이면 접안 |
| fetched_at | TIMESTAMPTZ NOT NULL | 받아 온 시각 |

유니크 인덱스 `control_events_uq (COALESCE(call_sign,''), kind, at)`.

## 2. 조회 이력 (API가 쓴다)

### query_log: 조회 한 번당 한 줄 (003, 004, 006, 007, 008, 018_db_cleanup)
| 칸 | 타입 | 설명 |
|---|---|---|
| id | BIGSERIAL PK | 줄 번호 |
| request_id | TEXT | 요청 ID. 로그와 같은 값 |
| session_id | TEXT NOT NULL | 브라우저 세션. 로그인 꺼진 환경에서 사람을 가르는 값 |
| user_id | TEXT | 로그인 사용자 (006). 로그인 꺼진 환경이면 NULL |
| bl_masked | TEXT | 가운데 절반을 *로 가린 B/L (SDD 3.5) |
| bl_encrypted | TEXT | 서버 열쇠로 잠근 B/L 원본 (007, crypto.py). 로그인 사용자만. 다시 조회와 화물 시트가 읽는다 |
| status | TEXT | 응답 상태 (ok, partial, insufficient, failed, unsupported) |
| verdict | TEXT | 판정 등급. 저장 값은 fine, watch, act이고 화면 이름은 순항, 주의, 긴급. 판정이 없으면 NULL |
| vessel_match | TEXT | 선박 식별 결과 (confirmed, uncertain, none) |
| decided_by | TEXT | 등급을 누가 정했나 (rule: 판정 표, llm: 회색 지대에서 LLM이 올림) |
| trace_id | TEXT | Langfuse 트레이스 ID |
| response | JSONB | 응답 전체 (004). 후속 질문이 꺼내 쓴다. 화면 전용 UNI-PASS 처리 내역(customs_detail)과 컨테이너 번호 평문은 넣지 않는다 (`routers/agent.py _seal_containers`) |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() | 조회 시각 |

인덱스: `query_log_session_created_idx (session_id, created_at DESC)` (003), `query_log_session_bl_created_idx (session_id, bl_masked, created_at DESC)` (004), `query_log_user_created_idx (user_id, created_at DESC)` (006), `query_log_user_bl_created_idx (user_id, bl_masked, created_at DESC)` (018_db_cleanup, 로그인 사용자의 같은 B/L 후속 질문 조회용).
90일이 지난 줄은 `purge_old_queries()`가 지운다 (008, pg_cron `marvia-purge-queries`, 매일 18:10 UTC).

## 3. 회원과 기억 (로그인 사용자)

### user_profiles: 회원 정보 (010)
| 칸 | 타입 | 설명 |
|---|---|---|
| user_id | TEXT PK | 로그인 사용자 |
| name_enc | TEXT NOT NULL | 이름. 개인정보 열쇠(PII_ENCRYPTION_KEY)로 잠근 글자만 들어간다 |
| phone_enc | TEXT NOT NULL | 전화번호. 잠근 글자 |
| address_enc | TEXT NOT NULL | 주소. 잠근 글자 |
| consent_at | TIMESTAMPTZ NOT NULL | 수집·이용 동의 시각 (개인정보보호법 제15조). 동의 없이는 저장하지 않는다 |
| created_at, updated_at | TIMESTAMPTZ NOT NULL | 만든 시각, 고친 시각 |

탈퇴하면 이 줄을 지운다 (services/account/account.py).

### user_cargo: 사용자의 화물 표 (014, 015, 017_cargo_watch, 019, 020, 021_cargo_vessel_name)
화물 비서 기억, 화물 시트, 지켜보기가 함께 쓴다 (docs/specs/memory.md, docs/specs/cargo-watch.md). 조회하면 services/account/memory.py가 채운다.

기본 칸
| 칸 | 타입 | 설명 |
|---|---|---|
| id | BIGSERIAL PK | 줄 번호 |
| user_id | TEXT NOT NULL | 로그인 사용자. UNIQUE (user_id, cargo_key) |
| cargo_key | TEXT NOT NULL | B/L 원본의 HMAC 지문. 같은 사용자 안에서 같은 화물을 찾는 데만 쓴다 |
| bl_masked | TEXT NOT NULL | 가린 B/L |
| bl_encrypted | TEXT | 잠근 B/L 원본. 줄이 지워질 때(완료 3년 뒤 `purge_done_cargo`, 사용자가 잊기·탈퇴) 함께 사라진다. 화물 시트의 엑셀 내려받기만 이 값을 열어 원본을 적는다 (SDD 3.5의 예외) |
| bl_type | TEXT NOT NULL | MASTER, HOUSE |
| label | TEXT | 사용자가 붙인 이름표 (예: 고추). 사용자가 준 것만 쓴다 |
| goods_name | TEXT | UNI-PASS 품명 (020). 채팅 에이전트 LLM에는 주고 판정 LLM에는 주지 않는다. 주입 의심 문구면 저장하지 않는다 (`services/watch/cargo.py`, `guard.looks_like_injection`) |
| status | TEXT NOT NULL DEFAULT 'active' | active(진행 중), done(완료). CHECK (active, done) |
| done_at | TIMESTAMPTZ | 완료 시각 |
| created_at, updated_at | TIMESTAMPTZ NOT NULL | 만든 시각, 고친 시각 |

판정 입력과 지난 조회 요약
| 칸 | 타입 | 설명 |
|---|---|---|
| sale_due_date | DATE | 받아야 하는 날 |
| sale_due_asked | BOOLEAN NOT NULL DEFAULT false | 받아야 하는 날을 이미 물어봤는지 |
| forwarder_eta | DATE | 포워더가 알려 준 입항 예정일 |
| forwarder_eta_noted_at | DATE | 그 예정일을 들은 날 |
| last_verdict | TEXT | 마지막 판정 등급. 다음 조회 때 "지난번엔 주의"를 짚는다 |
| last_checked_at | TIMESTAMPTZ | 마지막 조회 시각 |
| last_days_margin | INTEGER | 마지막 여유 일수 |
| last_eta | DATE | 마지막 도착 예정 |
| last_stage | TEXT | 마지막 통관 단계 |
| pending | JSONB NOT NULL DEFAULT '[]' | 대화에서 나온 값 변경 중 사용자가 확인하지 않은 것 (015) |

선박
| 칸 | 타입 | 설명 |
|---|---|---|
| vessel_mmsi | BIGINT | 확정한 선박 |
| voyage_no | TEXT | 항차 번호 |
| vessel_source | TEXT | 선박을 어떻게 확정했는지. CHECK (mrn, user) |
| vessel_name, vessel_flag | TEXT | 확정한 선박 이름, 선적국 (021_cargo_vessel_name) |

B/L 조건 (015)
| 칸 | 타입 | 설명 |
|---|---|---|
| original_bl | TEXT | 원본 B/L 상태. CHECK (required, surrendered) |
| to_order_bank | BOOLEAN | 지시식 선하증권의 은행 지시 여부 |
| freight_term | TEXT | 운임 조건. CHECK (prepaid, collect) |
| incoterm | TEXT | 인코텀즈. CHECK (CIF, FOB, CFR) |

지켜보기 (017_cargo_watch)
| 칸 | 타입 | 설명 |
|---|---|---|
| watch | BOOLEAN NOT NULL DEFAULT false | 지켜보기 켬 |
| changed_from | TEXT | 지켜보는 중 바뀐 것의 이전 값 |
| changed_at | TIMESTAMPTZ | 바뀐 시각 |
| change_seen | BOOLEAN NOT NULL DEFAULT true | 사용자가 바뀐 것을 봤는지 |

화물 시트 (019)
| 칸 | 타입 | 설명 |
|---|---|---|
| lc_id | BIGINT | 신용장. FK `user_lc(id)` ON DELETE SET NULL |
| departed_on | DATE | 출항일 |
| departed_source | TEXT | 출항일을 어디서 얻었나. CHECK (manual: 사용자가 넣음, document: 도착 통지서 사진에서 읽음) |
| arrived_on, warehoused_on | DATE | 도착일, 입고일 |
| forwarder_name, carrier_name | TEXT | 포워더 이름, 선사 이름 |
| container_no | TEXT | UNI-PASS 컨테이너 번호 그대로. 한 칸에 번호 하나 또는 여럿을 ", "로 이은 글. 화물 시트가 보여 주려고 평문으로 둔다. LLM에는 [CNTR1]처럼 가려서 준다 |

완료(done)된 지 3년이 지난 줄은 `purge_done_cargo()`가 지우고, 그 화물의 메모장 항목도 함께 뺀다 (015, pg_cron `marvia-purge-done-cargo`, 매일 18:20 UTC).

### user_lc: 신용장 (019)
화물 시트(`/api/cargo/sheet`)에서 화물을 신용장 번호로 묶는다 (services/watch/cargo_sheet.py).
| 칸 | 타입 | 설명 |
|---|---|---|
| id | BIGSERIAL PK | 줄 번호 |
| user_id | TEXT NOT NULL | 로그인 사용자 |
| lc_no | TEXT NOT NULL | 신용장 번호. CHECK 길이 1~35 (`cargo_sheet.LC_NO_MAX`와 같다). UNIQUE (user_id, lc_no) |
| opened_on | DATE | 개설일 |
| created_at, updated_at | TIMESTAMPTZ NOT NULL | 만든 시각, 고친 시각 |

### user_memory: 사용자 메모장 (014, 015)
| 칸 | 타입 | 설명 |
|---|---|---|
| user_id | TEXT PK | 로그인 사용자 |
| items | JSONB NOT NULL DEFAULT '[]' | 종류가 정해진 기억 항목 목록. 화면용 마크다운은 코드가 만든다 |
| version | INTEGER NOT NULL DEFAULT 0 | 동시에 고칠 때 나중 것이 앞의 것을 덮지 않게 확인하는 번호 |
| previous | JSONB | 직전 버전. 잘못 고쳐졌을 때 되돌린다 |
| full_at | TIMESTAMPTZ | 메모장이 가득 찼던 시각 (015) |
| updated_at | TIMESTAMPTZ NOT NULL | 고친 시각 |

### user_forget: 잊기 표시 (015)
사용자가 메모장이나 화물 기억을 지웠다는 표시를 하루 남겨, 지운 직후 동시에 도는 저장이 다시 살리지 않게 한다 (services/account/memory.py `_FORGET_KEEP_SEC`).
| 칸 | 타입 | 설명 |
|---|---|---|
| user_id | TEXT PK | 로그인 사용자 |
| memo_deleted_at | TIMESTAMPTZ | 메모장을 지운 시각 |
| cargo_deleted_at | TIMESTAMPTZ | 화물 기억을 지운 시각 |

두 시각 중 늦은 것이 하루보다 오래되면 `purge_done_cargo()`가 줄을 지운다.

### kakao_links: 카카오 알림 연결 (016_kakao_links, 022)
| 칸 | 타입 | 설명 |
|---|---|---|
| user_id | TEXT PK | 로그인 사용자 |
| access_token_enc | TEXT NOT NULL | 카카오 접근 토큰. 개인정보 열쇠로 잠근 글자 |
| refresh_token_enc | TEXT NOT NULL | 갱신 토큰. 잠근 글자 |
| access_expires_at, refresh_expires_at | TIMESTAMPTZ NOT NULL | 두 토큰의 만료 시각 |
| linked_at, updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() | 연결한 시각, 고친 시각 |
| last_sent_at | TIMESTAMPTZ | 마지막으로 알림을 보낸 시각 (022) |

연결을 끊거나 탈퇴하면 줄을 지운다.

### token_usage: 하루 토큰 사용량 (016_token_usage)
사용자(또는 로그인 꺼진 환경의 세션)별 하루 LLM 토큰 한도를 세는 표다 (docs/specs/token-quota.md, services/account/quota.py).
| 칸 | 타입 | 설명 |
|---|---|---|
| owner | TEXT NOT NULL | 로그인했으면 user_id, 아니면 session_id |
| day | DATE NOT NULL | 날짜(한국 시각 자정 기준). PRIMARY KEY (owner, day) |
| tokens | INTEGER NOT NULL DEFAULT 0 | 그날 쓴 토큰 |
| updated_at | TIMESTAMPTZ NOT NULL | 고친 시각 |

### conversations, conversation_messages: 채팅 대화 목록 (018_conversations)
로그인 사용자의 채팅 대화를 저장해 목록에서 다시 연다 (services/chat/conversations.py, routers/conversations.py). 사용자 말에 B/L·전화번호가 섞일 수 있어 글과 JSON은 모두 개인정보 열쇠로 잠근 글자만 둔다. 열쇠가 없으면 저장하지 않는다.
| 칸 (conversations) | 타입 | 설명 |
|---|---|---|
| id | TEXT NOT NULL | 대화 번호. 채팅 요청의 session_id와 같다. PRIMARY KEY (user_id, id) |
| user_id | TEXT NOT NULL | 로그인 사용자 |
| title_enc | TEXT | 잠근 제목 |
| context_enc | TEXT | 잠근 마지막 판정 요청(reply.request). 오른쪽 칸을 마지막 화물로 되살리는 데 쓴다 |
| result_enc | TEXT | 잠근 마지막 판정 결과(reply.agent) |
| created_at, updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() | 만든 시각, 고친 시각 |

| 칸 (conversation_messages) | 타입 | 설명 |
|---|---|---|
| user_id, conversation_id | TEXT NOT NULL | PRIMARY KEY (user_id, conversation_id, seq). FK (user_id, conversation_id)→conversations(user_id, id) ON DELETE CASCADE |
| seq | INTEGER NOT NULL | 말풍선 순서 |
| role | TEXT NOT NULL | CHECK (user, assistant) |
| text_enc | TEXT NOT NULL | 잠근 말풍선 글 |
| extra_enc | TEXT | 잠근 화면 자료(선박 목록, 지도, 화물 줄 등) |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() | 시각 |

인덱스: `conversations_user_updated_idx (user_id, updated_at DESC)`. 마지막으로 고친 지 90일이 지난 대화는 `purge_old_conversations()`가 지운다 (018, pg_cron `marvia-purge-conversations`, 매일 18:30 UTC). 대화당 말풍선은 최근 200개까지 두고 목록은 50건까지 돌려준다 (services/chat/conversations.py `KEEP_MESSAGES`, `LIST_MAX`). 탈퇴하면 대화도 함께 지운다.

### suspended_users: 지금 정지된 계정 (012)
| 칸 | 타입 | 설명 |
|---|---|---|
| user_id | TEXT PK | 정지된 사용자. 요청마다 이 표를 봐서 이미 받은 출입증도 바로 막는다 |
| suspended_by | TEXT NOT NULL | 정지한 운영자 |
| reason | TEXT NOT NULL | 정지 사유 |
| suspended_at | TIMESTAMPTZ NOT NULL | 정지 시각 |

해제하면 줄을 지운다. 지난 정지·해제 기록은 admin_actions에 남는다.

## 4. 운영자

운영자 이메일은 지문(HMAC), 잠근 값, 가린 값으로만 둔다 (013). 009·011이 만든 평문 이메일 칸은 018_db_cleanup이 비어 있을 때만 지운다(부록).

### operators: 운영자 권한 (009, 013, 018_db_cleanup)
| 칸 | 타입 | 설명 |
|---|---|---|
| email_hash | TEXT | 이메일 HMAC 지문. 운영자인지 찾을 때 이것만 쓴다. 013에서 UNIQUE, 비어 있는 줄이 없으면 018_db_cleanup이 NOT NULL PRIMARY KEY로 올린다 |
| email_enc | TEXT | 잠근 이메일. 운영자 화면에서만 풀어 보여 준다 |
| email_masked | TEXT | 가린 이메일 (예: ks***@g***.com). 열쇠를 잃어도 누구였는지 짐작할 수 있게 |
| granted_by | TEXT NOT NULL | 등록한 운영자 ID. 스크립트로 넣은 최초 운영자는 bootstrap |
| granted_at | TIMESTAMPTZ NOT NULL | 등록 시각 |
| revoked_by | TEXT | 해지한 운영자 ID. 활성이면 NULL |
| revoked_at | TIMESTAMPTZ | 해지 시각. 활성이면 NULL |

### operator_audit: 운영자 등록·해지 이력 (009, 013, INSERT만)
| 칸 | 타입 | 설명 |
|---|---|---|
| id | BIGSERIAL PK | 줄 번호 |
| action | TEXT NOT NULL | grant(등록), revoke(해지). CHECK (grant, revoke) |
| actor_user_id | TEXT NOT NULL | 처리한 운영자 ID. 스크립트면 bootstrap |
| target_email_enc, target_email_masked | TEXT | 대상 이메일 (잠근 값, 가린 값) |
| actor_email_enc, actor_email_masked | TEXT | 처리한 운영자 이메일 (잠근 값, 가린 값) |
| created_at | TIMESTAMPTZ NOT NULL | 처리 시각 |

인덱스 `operator_audit_created_idx (created_at DESC)`.

### admin_actions: 운영자가 고객에게 한 일 (011, 012, 013, INSERT만)
| 칸 | 타입 | 설명 |
|---|---|---|
| id | BIGSERIAL PK | 줄 번호 |
| action | TEXT NOT NULL | customer_update(수정), customer_delete(강제 탈퇴), unmask(가린 정보 보기), customer_suspend(정지), customer_resume(해제). 011이 앞의 세 값으로 CHECK를 만들고 012가 두 값을 더해 다시 건다 |
| target_user_id | TEXT NOT NULL | 대상 고객 |
| target_email_masked | TEXT | 대상 가린 이메일. 탈퇴 뒤에도 누구였는지 남긴다 |
| actor_user_id | TEXT NOT NULL | 처리한 운영자 |
| actor_email_enc, actor_email_masked | TEXT | 처리한 운영자 이메일 (잠근 값, 가린 값) |
| reason | TEXT | 사유. 가린 정보 보기는 필수(10~500자), 수정·탈퇴는 비어 있을 수 있다 |
| created_at | TIMESTAMPTZ NOT NULL | 처리 시각 |

인덱스 `admin_actions_created_idx (created_at DESC)`. 가린 정보 보기(unmask)는 원문을 돌려주기 전에 여기에 먼저 쓴다. 쓰기에 실패하면 원문을 주지 않는다.

## 5. 시스템

### schema_migrations: 적용한 마이그레이션
마이그레이션 파일이 아니라 `db/__init__.py`가 처음 적용할 때 만든다. RLS는 005가 켠다.
| 칸 | 타입 | 설명 |
|---|---|---|
| name | TEXT PK | 마이그레이션 파일 이름 (예: 022_kakao_last_sent_at.sql) |
| applied_at | TIMESTAMPTZ | 적용 시각 |

## 부록

### 서비스가 읽지 않는 표와 칸

worker가 계속 쓰지만 서비스(API)는 읽지 않는다. 018_db_cleanup은 이 칸들을 지우지 않고 남겨 두었다.

| 대상 | 내용 |
|---|---|
| arrival_reports, control_events | 서비스는 해수부 API를 실시간으로 부른다. control_events는 `purge_old_positions`가 입항 시각을 찾을 때만 읽는다 |
| positions의 cog, navistat, dest, destcode, ais_eta, raw | 서비스는 `recent_positions`로 ts, lat, lng, sog만 읽는다 |

### 018_db_cleanup이 지우는 옛 칸

되돌릴 수 없는 삭제라 칸이 비어 있을 때만 지우고, 값이 남아 있으면 지우지 않고 NOTICE만 남긴다.

| 칸 | 이유 |
|---|---|
| query_log.retry_count, query_log.model | 003에서 만들었으나 저장하는 코드가 없다. 이력 응답의 model 칸은 null로 내보낸다 (`db/__init__.py`) |
| operators.email, operator_audit.target_email·actor_email, admin_actions.actor_email | 013에서 지문·암호문으로 옮긴 뒤 비워 둔 옛 평문 칸 |

표별 코드는 레포의 SQL로 확인했다. 운영 Supabase에서 018이 옛 칸을 실제로 지웠는지는 확인하지 못했다.

### DB에 넣지 않는 것

규칙의 원문은 SDD 3.5, 7절이다.

- B/L 원본 평문 (가린 값, 잠근 값, 지문만 둔다)
- UNI-PASS 중량·세관명·화주 정보와 화면 전용 처리 내역(customs_detail). 예외로 품명은 `user_cargo.goods_name`에 둔다 (020)
- 회원 정보와 운영자 이메일 평문
