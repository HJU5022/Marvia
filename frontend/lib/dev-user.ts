// 로그인 없는 로컬 모드(next dev + Supabase 설정 없음)에서 쓰는 사용자 id.
// lib/auth.ts(브라우저)와 lib/proxy.ts(서버)가 같이 쓴다. mock 데이터를 브라우저 번들에 넣지 않으려고 따로 둔다.
export const LOCAL_USER_ID = "local-dev-user";
