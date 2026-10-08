# Spec: 운영자 관리 (관리 탭, 고객 관리, 운영자 등록·해지)

아래 "추가" 절의 고객 수정·강제 탈퇴·마스킹 해제·일시 정지·이메일 암호화는 모두 구현돼 있다 (`routers/admin.py`, `services/account/customers.py`, `services/account/operators.py`, migrations 009~013, 018). 처음 설계 절과 "추가" 절이 다른 곳은 "추가"가 맞다.

SDD 5절과 작업 리스트에 없는 기능이라 CLAUDE.md "Spec 먼저" 규칙에 따라 쓴다. 로그인(G3) 뒤에 붙는 확장이다.

## Why

- **상황**: 로그인이 필수다(backend/app/auth.py). 사람이 생겼으니 누가 쓰는지, 누가 관리하는지를 알아야 한다.
- **문제**:
  1. 가입자 수와 활동(가입일, 마지막 로그인)을 보려면 지금은 Supabase 대시보드에 들어가야 하고, 그 화면은 이메일을 그대로 보여 준다
  2. 관리 권한을 줄 방법이 없다. 준다 해도 누가 언제 줬는지, 누가 뺏었는지 남지 않는다
- **측정 지표**: 없음 (운영 편의 기능. 평가셋·게이트와 무관)

## Goal

- 운영자만 보는 "관리" 탭에서 고객 목록(이메일·이름 마스킹, 가입일, 마지막 로그인)을 본다
- 운영자가 이메일로 신규 운영자를 등록하고 해지한다. 등록·해지는 누가 언제 했는지 DB에 이력으로 남는다
- 일반 사용자는 내 화물(화물 조회 `/`, 지켜보는 화물 `/watch`), 화물 현황(`/cargo`), 조회 이력(`/history`), 설정(`/settings`) 메뉴를 본다. 평가 지표(`/metrics`)와 관리(`/admin`)는 운영자에게만 보인다 (평가 지표는 모델 비교·비용 같은 시스템 품질 화면이라 일반 사용자에게 필요 없다. 주소로 들어와도 운영자가 아니면 안내만, `web/components/OperatorOnly.tsx`). 처음 Spec은 "내 화물, 조회 이력, 설정 3개 탭"이었으나 이후 화물 현황·지켜보는 화물이 생겼다
- **성공 기준**: 운영자가 아니면 관리 API가 403. 이력 표는 지우거나 고치지 않고 쌓기만 한다. 화면·API 응답 어디에도 고객 이메일 원문이 나오지 않는다
- **Out of Scope** (처음 설계 기준): 고객 계정 정지·삭제(뒤에 "추가" 절로 구현됨), 고객별 조회 기록 열람(지금도 안 함), 운영자 등급 나누기, 이메일 알림, 감사 로그 내보내기

## What

**Happy Path**
1. 최초 운영자: 사람이 `python -m scripts.ops.grant_operator <이메일>`을 한 번 실행한다. 이력에 등록자는 `bootstrap`으로 남는다
2. 운영자가 로그인하면 GET /api/me가 `is_operator: true`를 주고, 화면 사이드바에 "관리" 탭이 생긴다
3. 관리 > 고객 관리: 가입자 목록을 마스킹해서 보여 준다 (Supabase 관리자 API)
4. 관리 > 운영자: 이메일을 입력해 등록, 목록에서 해지, 아래에 등록·해지 이력
5. 등록된 이메일로 그 사람이 로그인하면 그때부터 운영자다 (가입 전에도 미리 등록 가능)

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 운영자가 아닌 사람이 관리 API 호출 | 403. 화면은 관리 탭을 숨기지만 서버가 최종 판단 |
| EC-02 | 로그인 기능이 꺼진 환경(채점용 compose) | 사용자가 없으므로 관리 API 403, is_operator false |
| EC-03 | 이미 운영자인 이메일을 다시 등록 | 409, 이력 안 남김 |
| EC-04 | 자기 자신을 해지 | 400. 마지막 운영자가 사라져 아무도 관리 못 하게 되는 것을 막는다 |
| EC-05 | 해지했던 사람을 다시 등록 | 등록 가능. 이력에 grant가 한 줄 더 쌓인다 |
| EC-06 | 이메일 형식 오류, 대소문자 차이 | 400 / 소문자로 맞춰 저장 |
| EC-07 | Supabase 관리자 키 없음·호출 실패 | 고객 목록만 503, 운영자 기능은 DB만 쓰므로 계속 동작 |
| EC-08 | DB 없음 | 관리 API 503, /api/me는 is_operator false |

## How

**DB (마이그레이션 009_operators.sql)**
- `operators`: 지금 상태. 처음에는 email(소문자, PK), granted_by, granted_at, revoked_by, revoked_at이었고, 013 이후 키는 `email_hash`(018이 NOT NULL PRIMARY KEY로 올림)이고 평문 email 칸은 018이 비어 있으면 지운다 (아래 암호화 절, docs/ERD.md). 활성은 revoked_at IS NULL
- `operator_audit`: 이력. id, action(grant / revoke), target_email, actor_user_id(또는 bootstrap), actor_email, created_at. INSERT만 한다
- 이메일 원문은 운영자 표에만 둔다. 운영자 본인이 권한을 받으려면 로그인 이메일과 맞춰야 하기 때문이다. 고객 표는 만들지 않는다(Supabase Auth가 원본)
- 005와 같이 RLS를 켜고 규칙은 두지 않는다. 공개 키로는 읽을 수 없다

**운영자 판단**: 출입증(JWT)의 email 클레임(서명 확인 뒤 값)을 operators와 대조한다. 화면이 보낸 값은 믿지 않는다

**API (backend/app/routers/admin.py)**

| 경로 | 권한 | 응답 |
|---|---|---|
| GET /api/me | 로그인 | user_id, email, is_operator, profile_complete (정지된 계정이면 403 account_suspended) |
| GET /api/admin/customers | 운영자 | 마스킹한 이메일·이름·전화·주소, profile_complete, is_suspended, created_at, last_sign_in_at, is_operator |
| GET /api/admin/operators | 운영자 | 활성 운영자 목록 + 이력 최근 100건 |
| POST /api/admin/operators | 운영자 | {email} 등록 |
| POST /api/admin/operators/revoke | 운영자 | {email} 해지 |

**마스킹 (services/account/operators.py mask_email, mask_name)**: 이메일은 앞 2자 + *** @ 도메인 첫 글자 + *** + 최상위 도메인 (`ka***@g***.com`). 이름은 첫 글자 + * (`김**`). 고객 목록 응답에 원문을 넣지 않는다. 운영자 목록은 운영자끼리 누가 권한을 가졌는지 알아야 하므로 원문을 보여 준다

**화면 (web/)**: 사이드바 링크를 is_operator로 나눈다 (`web/components/Shell.tsx`). /admin 한 페이지(`web/components/AdminPage.tsx`)에 "고객 관리"와 "운영자 관리" 두 탭. 고객 관리에는 고객 작업 이력(GET /api/admin/actions)도 보인다. 해지는 화면 안에서 한 번 더 확인한다

**테스트**: backend/tests/integration/test_admin.py, test_customers_admin.py (추가 절의 수정·탈퇴·마스킹 해제·정지). 마스킹, 권한(403), 중복 등록(409), 자기 해지(400), 이력 기록을 가짜 DB·가짜 Supabase로 확인한다. 키 없이 돈다

## 추가: 고객 수정·강제 탈퇴·마스킹 해제, 테스트 고객

사용자 지시: 고객 관리에서 운영자가 직접 수정·탈퇴하고, 사유서를 쓰고 마스킹을 풀 수 있게. 테스트 고객 3명을 넣어 둔다.

**동작**

| 동작 | API | 규칙 |
|---|---|---|
| 수정 | PUT /api/admin/customers/{user_id}/profile | 이름·휴대전화·주소만. 검사 규칙은 본인 입력과 같다(services/account/profile.clean). 동의 시각은 바꾸지 않는다. 이메일은 구글 계정이라 못 바꾼다 |
| 강제 탈퇴 | DELETE /api/admin/customers/{user_id} | 기록 → 회원 정보 → 계정 순서(services/account/account.withdraw와 같다). 운영자 계정은 해지 먼저(409), 자기 자신은 안 됨(400) |
| 마스킹 해제 | POST /api/admin/customers/{user_id}/unmask {reason} | 사유 10~500자 필수. 그 고객 한 명의 이메일·이름·전화·주소 원문을 돌려준다. 화면은 60초 뒤 다시 가린다 |

**이력 (011_admin_actions.sql)**: admin_actions(id, action: customer_update / customer_delete / unmask (012가 customer_suspend / customer_resume 추가), target_user_id, target_email_masked, actor_user_id, actor_email, reason, created_at). INSERT만. 마스킹 해제는 원문을 보기 전에 먼저 기록한다(기록 실패면 원문을 주지 않는다). 대상은 탈퇴 뒤에도 알아볼 수 있게 가린 이메일로 남긴다

**Edge Cases (추가)**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-09 | 사유 10자 미만 | 400, 원문 안 줌, 기록 안 남김 |
| EC-10 | 없는 고객 | 404 |
| EC-11 | 회원 정보가 없는 고객을 수정 | 운영자가 새로 입력할 수 있다. 동의 시각은 운영자 입력 시각, 이력에 남는다 |
| EC-12 | 운영자 계정 강제 탈퇴 | 409. 운영자 해지 먼저 |

**테스트 고객**: scripts/ops/seed_test_users.py가 testuser1~3@marvia.test 계정(Supabase 관리자 API, user_metadata.test=true)과 가공 회원 정보를 만든다. 실제 사람이 아님을 이름(testUser1~3)으로 드러낸다. 다시 돌리면 이미 있는 계정은 건너뛴다

## 추가: 고객 계정 일시 정지

사용자 지시: 고객 관리에 일시 정지 버튼. 정지하면 그 고객은 로그인·조회를 못 하고, 해제하면 되돌린다.

| 동작 | API | 규칙 |
|---|---|---|
| 정지 | POST /api/admin/customers/{user_id}/suspend {reason} | 사유 10~500자 필수. 운영자 계정은 해지 먼저(409), 자기 자신 불가(400). 이미 정지면 409 |
| 해제 | POST /api/admin/customers/{user_id}/resume | 정지 중이 아니면 409 |

- 두 곳을 같이 막는다. (1) Supabase 관리자 API로 계정 차단(ban_duration): 새 로그인·출입증 갱신 불가. (2) suspended_users 표: 이미 발급된 출입증(최대 1시간)으로 와도 auth.current_user가 403. 차단 확인은 요청마다 DB 한 번
- DB를 못 읽으면 정지 확인을 건너뛴다(서비스를 멈추지 않음, 실패 로그). Supabase 차단은 그대로 유효하다
- 정지·해제는 admin_actions에 customer_suspend, customer_resume으로 남는다 (012에서 CHECK 확장)
- 강제 탈퇴하면 정지 줄도 지운다
- 정지된 사람이 화면에 들어오면 "정지된 계정" 안내만 보인다 (GET /api/me가 403 account_suspended)

## 추가: 운영자 이메일 암호화 (013)

처음 설계는 operators.email(평문)을 출입증 email과 비교해 운영자를 가렸다. Fernet 암호문은 같은 값도 매번 달라 비교할 수 없어서였다. 운영자 이메일도 개인정보라 고객 정보와 기준을 맞춘다(사용자 지시).
- operators: email_hash(HMAC-SHA256 지문, 찾기·중복 확인용, crypto.fingerprint) + email_enc(Fernet, 화면용) + email_masked. 평문 칸은 비운다
- operator_audit: target/actor 이메일을 암호문 + 가린 값으로. admin_actions의 처리자 이메일도 같다
- 암호문·지문 열쇠는 PII_ENCRYPTION_KEY (B/L 열쇠와 분리, .env.example에 키 이름 추가). 지문은 그 열쇠에서 용도 이름을 붙여 갈라 쓴다. 열쇠가 없으면 운영자 기능은 닫힌 쪽으로 실패(운영자 아님, 등록 503)
- 화면 응답 모양은 그대로(서버가 풀어서 준다). 열쇠가 바뀌어 못 풀면 가린 값
- 기존 행은 scripts/ops/encrypt_operator_emails.py로 옮기고 평문을 비웠다. INSERT만 하는 이력 표를 고친 유일한 예외다
