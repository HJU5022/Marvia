# Spec: 운영자 관리 (관리 탭, 고객 관리, 운영자 등록·해지)

작성 2026-10-01 김승욱. SDD 5절과 작업 리스트에 없는 기능이라 CLAUDE.md "Spec 먼저" 규칙에 따라 쓴다. 로그인(G3) 뒤에 붙는 확장이다.

## Why

- **상황**: 09-30부터 로그인이 필수다(backend/app/auth.py). 사람이 생겼으니 누가 쓰는지, 누가 관리하는지를 알아야 한다.
- **문제**:
  1. 가입자 수와 활동(가입일, 마지막 로그인)을 보려면 지금은 Supabase 대시보드에 들어가야 하고, 그 화면은 이메일을 그대로 보여 준다
  2. 관리 권한을 줄 방법이 없다. 준다 해도 누가 언제 줬는지, 누가 뺏었는지 남지 않는다
- **측정 지표**: 없음 (운영 편의 기능. 평가셋·게이트와 무관)

## Goal

- 운영자만 보는 "관리" 탭에서 고객 목록(이메일·이름 마스킹, 가입일, 마지막 로그인)을 본다
- 운영자가 이메일로 신규 운영자를 등록하고 해지한다. 등록·해지는 누가 언제 했는지 DB에 이력으로 남는다
- 일반 사용자는 기존 4개 탭(내 화물, 조회 이력, 평가 지표, 설정)만 본다
- **성공 기준**: 운영자가 아니면 관리 API가 403. 이력 표는 지우거나 고치지 않고 쌓기만 한다. 화면·API 응답 어디에도 고객 이메일 원문이 나오지 않는다
- **Out of Scope**: 고객 계정 정지·삭제, 고객별 조회 기록 열람, 운영자 등급 나누기, 이메일 알림, 감사 로그 내보내기

## What

**Happy Path**
1. 최초 운영자: 사람이 `python -m scripts.grant_operator <이메일>`을 한 번 실행한다. 이력에 등록자는 `bootstrap`으로 남는다
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
- `operators`: 지금 상태. email(소문자, PK), granted_by, granted_at, revoked_by, revoked_at. 활성은 revoked_at IS NULL
- `operator_audit`: 이력. id, action(grant / revoke), target_email, actor_user_id(또는 bootstrap), actor_email, created_at. INSERT만 한다
- 이메일 원문은 운영자 표에만 둔다. 운영자 본인이 권한을 받으려면 로그인 이메일과 맞춰야 하기 때문이다. 고객 표는 만들지 않는다(Supabase Auth가 원본)
- 005와 같이 RLS를 켜고 규칙은 두지 않는다. 공개 키로는 읽을 수 없다

**운영자 판단**: 출입증(JWT)의 email 클레임(서명 확인 뒤 값)을 operators와 대조한다. 화면이 보낸 값은 믿지 않는다

**API (backend/app/routers/admin.py)**

| 경로 | 권한 | 응답 |
|---|---|---|
| GET /api/me | 로그인 | user_id, email, is_operator |
| GET /api/admin/customers | 운영자 | 마스킹한 이메일·이름, created_at, last_sign_in_at, is_operator |
| GET /api/admin/operators | 운영자 | 활성 운영자 목록 + 이력 최근 100건 |
| POST /api/admin/operators | 운영자 | {email} 등록 |
| POST /api/admin/operators/revoke | 운영자 | {email} 해지 |

**마스킹 (services/operators.py mask_email, mask_name)**: 이메일은 앞 2자 + *** @ 도메인 첫 글자 + *** + 최상위 도메인 (`ka***@g***.com`). 이름은 첫 글자 + * (`김**`). 고객 목록 응답에 원문을 넣지 않는다. 운영자 목록은 운영자끼리 누가 권한을 가졌는지 알아야 하므로 원문을 보여 준다

**화면 (web/)**: 사이드바 링크를 is_operator로 나눈다. /admin 한 페이지에 "고객 관리"와 "운영자" 두 탭. 해지는 화면 안에서 한 번 더 확인한다

**테스트**: backend/tests/test_admin.py. 마스킹, 권한(403), 중복 등록(409), 자기 해지(400), 이력 기록을 가짜 DB·가짜 Supabase로 확인한다. 키 없이 돈다
