# Spec: 회원 정보 필수 입력 (이름, 전화번호, 주소) 암호화 저장과 마스킹

관련: [operator-admin.md](operator-admin.md) (고객 관리 화면), [SDD 5.15](../Marvia_SDD.md), [ADR 0005](../adr/0005-bl-masking-not-to-llm.md) (B/L 열쇠)

## 현재 동작

- 로그인 뒤 회원 정보가 없으면 조회 화면 대신 입력 화면이 나온다. 이름·전화번호·주소를 넣고 수집·이용에 동의해야 쓸 수 있다
- DB에는 세 값을 암호화한 글자만 둔다. 운영자 고객 관리에는 가린 값만 나가고, 원문은 본인에게만 보인다
- 탈퇴하면 회원 정보도 지운다

## 왜

고객 관리의 이름은 구글 프로필 이름이라 실제 이름이 아니고, 연락할 전화번호와 주소도 없다. 그래서 세 값을 필수로 받는다. 개인정보라 저장은 암호화하고 보여 줄 때는 가린다.

**범위 밖**: 전화번호 인증(SMS), 주소 검색 API, 이름으로 검색. 운영자가 원문을 보는 길은 사유를 남기는 조건으로만 있다 ([operator-admin.md](operator-admin.md) "마스킹 해제")

## 동작

**정상 흐름**
1. 로그인하면 `GET /api/me`의 profile_complete가 false일 때 회원 정보 입력 화면(필수 3칸 + 수집·이용 동의)이 나온다
2. `PUT /api/profile`: 서버가 형식을 검사하고 암호화해 저장한다. 화면은 원래 화면으로 돌아간다
3. 설정 > 회원 정보 탭(`web/components/SettingsPage.tsx`, `ProfileForm`)에서 본인 정보를 확인·수정한다 (본인에게는 원문)
4. 관리 > 고객 관리: 이름 김**, 전화 010-****-5678, 주소 앞 두 마디 + *** (서울특별시 강남구 ***)

**예외**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 동의 체크 안 함 | 400. 화면도 버튼을 막는다 (개인정보보호법 제15조 수집·이용 동의) |
| EC-02 | 전화번호 형식 오류 | 숫자만 남겨 010·011·016~019로 시작하는 10~11자리만 받는다. 아니면 400 |
| EC-03 | 이름 1자 미만·30자 초과, 주소 5자 미만·200자 초과 | 400 |
| EC-04 | 암호화 열쇠 없음 | 503. 원문을 그대로 저장하지 않는다 |
| EC-05 | 로그인 기능 꺼진 환경 | 사용자가 없으므로 입력 화면 없음, profile_complete true로 본다 |
| EC-06 | DB 없음 | 503. /api/me는 profile_complete를 true로 답해 화면을 막지 않는다 |
| EC-07 | 열쇠가 바뀌어 열 수 없음 | 고객 관리에는 "확인 불가", 본인 화면은 다시 입력 요청 |
| EC-08 | 탈퇴 | 기록, 회원 정보, 계정 순서로 지운다 |

## 구현

- **DB** (`010_user_profiles.sql`): user_profiles(user_id PK, name_enc, phone_enc, address_enc, consent_at, created_at, updated_at). 세 칸은 Fernet으로 암호화한 글자다. RLS를 켜고 규칙은 두지 않는다(`005_enable_rls.sql`과 같다)
- **열쇠**: `PII_ENCRYPTION_KEY`. 회원 정보와 운영자 이메일(암호문·지문)만 이 열쇠를 쓰고, B/L 원본은 `BL_ENCRYPTION_KEY`를 쓴다. 열쇠를 나눈 이유는 한쪽이 새도 다른 쪽은 안전하게 하기 위해서다. PII 열쇠가 없으면 B/L 열쇠로 대신하지 않고 막는다. 같은 DB를 쓰는 환경은 같은 PII 열쇠가 있어야 읽을 수 있다
- **API**: `GET /api/profile`(본인 원문), `PUT /api/profile`(저장), `GET /api/me`의 profile_complete, `GET /api/admin/customers`의 가린 phone·address·이름(입력값 우선, 없으면 구글 이름)
- **동의 문구**: 수집 항목(이름, 전화번호, 주소), 목적(화물 관련 연락과 본인 확인), 보유 기간(탈퇴 시까지), 거부 시 서비스 이용 불가. consent_at에 동의 시각을 남긴다

| 파일 | 책임 |
|---|---|
| `backend/app/routers/profile.py` | `GET`·`PUT /api/profile` |
| `backend/app/services/account/profile.py` | 형식 검사(`NAME_MAX` 30, `ADDRESS_MIN`·`ADDRESS_MAX` 5~200, 전화 `^01[016789]\d{7,8}$`), 마스킹(이름 첫 글자 + *, 전화 앞 3자리와 뒤 4자리, 주소 앞 두 마디 + ***), 암호화 저장. 운영자가 고치는 길도 같은 검사를 쓴다(`save(..., by_operator=True)`, 동의 시각은 그대로) |
| `backend/app/routers/admin.py` | `GET /api/me`의 profile_complete |
| `web/components/ProfileForm.tsx` | `mode="required"`면 입력 화면. `Shell`이 `needProfile`일 때 띄운다 |

## 완료 기준

`backend/tests/integration/test_profile.py`: 형식 검사, 동의 없음 400, 암호화한 값만 DB에 가는지, 마스킹, 관리 목록에 원문 없음, 탈퇴 순서
