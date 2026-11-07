// 화면 로그인 (설계 10절 로그인, 계획 4b Task 7). 토큰만 다루고 사용자 id는 서버가 토큰에서 꺼낸다.
// - dev: 이 컴퓨터·e2e에서 개발 토큰을 직접 넣는다. 탭을 닫으면 잊는다(sessionStorage).
// - supabase: Supabase Auth 구글 로그인 세션의 access_token을 쓴다 (createClient, signInWithOAuth).
// [주의] 토큰을 번들에 넣지 않는다. NEXT_PUBLIC_ 값은 주소와 공개 키뿐이다.
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// [왜] 운영 빌드는 기본이 supabase다. 개발 로그인은 NEXT_PUBLIC_AUTH=dev일 때(그리고 npm run dev 기본)만 켜진다
export const AUTH_MODE: "dev" | "supabase" =
  (process.env.NEXT_PUBLIC_AUTH ?? (process.env.NODE_ENV === "production" ? "supabase" : "dev")) === "dev"
    ? "dev"
    : "supabase";
const DEV_KEY = "marvia-dev-token";

let client: SupabaseClient | null = null;

function supabase(): SupabaseClient {
  // [왜] 공개(anon) 키와 주소만 쓴다. 서버가 토큰 서명·소유자 목록을 다시 본다
  client ??= createClient(process.env.NEXT_PUBLIC_SUPABASE_URL ?? "", process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "");
  return client;
}

export async function currentToken(): Promise<string | null> {
  // [주의] 저장소가 막혔거나 Supabase 설정이 비면 던진다. 토큰 없음으로 본다
  try {
    if (AUTH_MODE === "dev") return sessionStorage.getItem(DEV_KEY);
    const { data } = await supabase().auth.getSession();
    return data.session?.access_token ?? null;
  } catch {
    return null;
  }
}

export async function signIn(devToken?: string): Promise<void> {
  try {
    if (AUTH_MODE === "dev") {
      if (devToken) sessionStorage.setItem(DEV_KEY, devToken);
      return;
    }
    await supabase().auth.signInWithOAuth({ provider: "google", options: { redirectTo: window.location.origin } });
  } catch {
    // 저장하지 못하거나 설정이 비면 currentToken이 null이라 로그인 쪽에 머문다
  }
}

export async function signOut(): Promise<void> {
  try {
    if (AUTH_MODE === "dev") sessionStorage.removeItem(DEV_KEY);
    else await supabase().auth.signOut();
  } catch {
    // 지울 것이 없다
  }
}
