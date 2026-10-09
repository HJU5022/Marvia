# Spec: 회원 정보 필수 입력 (이름, 전화번호, 주소) 암호화 저장과 마스킹

운영자 관리(operator-admin.md)에 이어지는 확장이다. SDD에 없는 기능이라 Spec을 먼저 둔다.

## Why

- **문제**: 고객 관리의 이름이 구글 프로필 이름이라 실제 이름이 아니다. 연락할 전화번호와 주소도 없다
- **결정(사용자 지시)**: 로그인한 사람은 이름·전화번호·주소를 반드시 입력한다. 저장은 암호화, 보여 줄 때는 마스킹

## Goal

- 로그인 뒤 회원 정보가 없으면 조회 화면 대신 입력 화면이 나온다. 입력하고 동의해야 쓸 수 있다
- DB에는 세 값을 잠근 글자만 둔다. 운영자 고객 관리에는 가린 값만 나간다. 원문은 본인에게만 보인다
- 탈퇴하면 회원 정보도 지운다
- **Out of Scope**: 전화번호 인증(SMS), 주소 검색 API, 이름으로 검색. (운영자가 고객 정보 원문 보기는 처음엔 범위 밖이었으나 같은 날 operator-admin.md "마스킹 해제"로 사유를 남기는 조건으로 구현됐다)

## What

**Happy Path**
1. 로그인 → GET /api/me의 profile_complete가 false → 회원 정보 입력 화면(필수 3칸 + 수집·이용 동의)
2. PUT /api/profile → 서버가 형식 검사, 잠가서 저장 → 화면이 원래 화면으로
3. 설정 > 회원 정보 탭(`web/components/SettingsPage.tsx`, `ProfileForm`)에서 본인 정보 확인·수정 (본인에게는 원문)
4. 관리 > 고객 관리: 이름 김**, 전화 010-****-5678, 주소 앞 두 마디 + *** (서울특별시 강남구 ***)

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 동의 체크 안 함 | 400. 화면도 버튼을 막는다 (개인정보보호법 제15조 수집·이용 동의) |
| EC-02 | 전화번호 형식 오류 | 숫자만 남겨 010·011·016~019로 시작하는 10~11자리만 받는다. 아니면 400 |
| EC-03 | 이름 1자 미만·30자 초과, 주소 5자 미만·200자 초과 | 400 |
| EC-04 | 암호화 열쇠 없음 | 503. 원문을 그대로 저장하지 않는다 |
| EC-05 | 로그인 기능 꺼진 환경 | 사용자가 없으므로 입력 화면 없음, profile_complete true로 본다 |
| EC-06 | DB 없음 | 503. /api/me는 profile_complete false가 아니라 true로 답해 화면을 막지 않는다 |
| EC-07 | 열쇠가 바뀌어 열 수 없음 | 고객 관리에는 "확인 불가", 본인 화면은 다시 입력 요청 |
| EC-08 | 탈퇴 | 기록 → 회원 정보 → 계정 순서로 지운다 |

## How

- **DB (010_user_profiles.sql)**: user_profiles(user_id PK, name_enc, phone_enc, address_enc, consent_at, created_at, updated_at). 세 칸은 Fernet으로 잠근 글자. RLS 켜고 규칙 없음(005와 같음)
- **열쇠**: PII_ENCRYPTION_KEY (B/L 열쇠와 분리, 사용자 결정). 회원 정보와 운영자 이메일(암호문·지문)만 이 열쇠를 쓰고 B/L 원본은 BL_ENCRYPTION_KEY 그대로. 한쪽이 새도 다른 쪽은 안전하다. 없으면 B/L 열쇠로 대신하지 않고 막는다. 처음 B/L 열쇠로 잠갔던 기존 값은 scripts/ops/rekey_personal_data.py로 옮겼다. 같은 DB를 쓰는 환경은 같은 PII 열쇠가 있어야 읽을 수 있다
- **API**: GET /api/profile(본인 원문), PUT /api/profile(저장), GET /api/me에 profile_complete 추가, GET /api/admin/customers에 마스킹한 phone·address·이름(입력값 우선, 없으면 구글 이름)
- **마스킹 (services/account/profile.py)**: 이름 첫 글자 + *, 전화 앞 3자리와 뒤 4자리, 주소 앞 두 마디 + ***
- **동의 문구**: 수집 항목(이름, 전화번호, 주소), 목적(화물 관련 연락과 본인 확인), 보유 기간(탈퇴 시까지), 거부 시 서비스 이용 불가. consent_at에 동의 시각을 남긴다
- **구현 상태**: 위 동작은 모두 코드에 있다. `routers/profile.py`(GET·PUT /api/profile), `services/account/profile.py`(검사·마스킹·암호화, 검사값 NAME_MAX 30, ADDRESS 5~200, 전화 `^01[016789]\d{7,8}$`), `routers/admin.py`(GET /api/me의 profile_complete), 화면 `web/components/ProfileForm.tsx`(`mode="required"`면 입력 화면, Shell이 `needProfile`일 때 띄움). 운영자가 고객 정보를 고치는 길도 같은 검사를 쓴다(`save(..., by_operator=True)`).
- **테스트**: backend/tests/integration/test_profile.py. 형식 검사, 동의 없음 400, 잠근 값만 DB에 가는지, 마스킹, 관리 목록에 원문 없음, 탈퇴 순서
