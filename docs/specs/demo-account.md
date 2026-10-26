# Spec: 데모 계정

관련: [operator-admin.md](./operator-admin.md) (서명 확인한 이메일로 사람을 가르는 방식), `backend/app/auth.py`, `web/lib/auth.ts`

## 현재 동작

- 배포 화면의 로그인 화면에 데모 계정(이메일·비밀번호)을 적어 두고, "데모 계정으로 둘러보기" 버튼으로 바로 로그인한다
- 데모 계정은 회원 탈퇴를 막는다(403). 내 기록 삭제는 막지 않는다

## 왜

- 로그인은 필수이고(auth.py 세 갈래) 로그인 방법이 Google뿐이라, 화면을 보러 온 사람이 자기 Google 계정 없이는 기능을 써 볼 수 없다
- 데모 계정은 여러 사람이 같이 쓴다. 누가 탈퇴하면 계정이 지워져 다음 사람이 들어오지 못한다

## 동작

| 항목 | 규칙 | 위치 |
|---|---|---|
| 계정 | Supabase 이메일 로그인 계정 1개. 대시보드에서 만들고 이메일 확인은 바로 끝낸다(Auto Confirm). 실제로 메일이 가지 않는 주소를 쓴다 | Supabase Authentication > Users |
| 화면 값 | `NEXT_PUBLIC_DEMO_EMAIL`, `NEXT_PUBLIC_DEMO_PASSWORD`. 둘 다 있을 때만 버튼과 계정 표기가 나온다. 화면에 공개하는 값이라 비밀값이 아니다 | `web/lib/auth.ts demoAccount`, `web/.env.example` |
| 로그인 | `signInWithPassword`로 이 페이지에서 바로 로그인한다. 백엔드는 출입증의 서명·만료·발급처·대상만 보므로 Google 로그인과 같은 길로 통과한다 | `web/lib/auth.ts signInWithDemo`, `backend/app/auth.py verify_claims` |
| 탈퇴 막기 | 서명 확인한 이메일(`verified_email`)이 `DEMO_ACCOUNT_EMAIL`과 같으면 `DELETE /api/account`가 403과 안내 문장을 돌려준다. 화면은 403의 detail을 그대로 보여 준다(`web/lib/api.ts`). 값이 비면 막지 않는다 | `backend/app/routers/account.py`, `.env.example` |

## 범위 밖

- 데모 계정끼리 대화 기록·화물 표·카카오 연결을 나누지 않는다. 같이 쓰는 계정이라 서로 보인다
- 이메일 가입·비밀번호 찾기 화면은 만들지 않는다. 로그인 화면에 비밀번호 입력 칸을 두지 않는다
