// 화면 로그인 (설계 10절 로그인, 계획 4b Task 7). 토큰만 다루고 사용자 id는 서버가 토큰에서 꺼낸다.
// - dev: 이 컴퓨터·e2e에서 개발 토큰을 직접 넣는다. 탭을 닫으면 잊는다(sessionStorage).
// Supabase 로그인은 Task 7e에서 더한다.
// [주의] 토큰을 번들에 넣지 않는다. NEXT_PUBLIC_ 값은 주소와 공개 키뿐이다.

export const AUTH_MODE: "dev" | "supabase" = "dev";
const DEV_KEY = "marvia-dev-token";

export async function currentToken(): Promise<string | null> {
  // [주의] 저장소가 막힌 브라우저(사생활 보호 등)는 접근만으로 던진다. 토큰 없음으로 본다
  try {
    return sessionStorage.getItem(DEV_KEY);
  } catch {
    return null;
  }
}

export async function signIn(devToken?: string): Promise<void> {
  try {
    if (devToken) sessionStorage.setItem(DEV_KEY, devToken);
  } catch {
    // 저장하지 못하면 currentToken이 null이라 로그인 쪽에 머문다
  }
}

export async function signOut(): Promise<void> {
  try {
    sessionStorage.removeItem(DEV_KEY);
  } catch {
    // 지울 것이 없다
  }
}
