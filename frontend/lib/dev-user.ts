// 로그인 없는 로컬 모드(next dev + Supabase 설정 없음)에서 쓰는 사용자 id.
// lib/auth.ts(브라우저)와 lib/proxy.ts(서버)가 같이 쓴다. mock 데이터를 브라우저 번들에 넣지 않으려고 따로 둔다.
//
// 값이 uuid 이고 백엔드와 같아야 하는 이유:
//   백엔드도 AUTH_REQUIRED=false 일 때 고정 사용자를 쓴다 (services/auth.py LOCAL_GRADER_USER_ID).
//   두 값이 다르면 내가 claim 한 핀이 화면에서 "다른 사람이 등록"으로 보인다. 실제로 겪었다 (09-20).
//   sessions.user_id 가 uuid 컬럼이라 문자열은 저장 단계에서도 막힌다.
export const LOCAL_USER_ID = "00000000-0000-0000-0000-000000000001";
