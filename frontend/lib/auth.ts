"use client";

// 구글 로그인(Supabase Auth). 서비스 전체가 로그인 뒤에 있다 (SDD 2절).
// Supabase 설정이 없을 때 로그인 없이 쓰는 로컬 모드는 개발 서버(next dev)에서만 켜진다.
// 이 경우 백엔드도 AUTH_REQUIRED=false 여야 한다. 배포 빌드에서 설정이 없으면 화면이 막힌다.

import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";
import { useEffect, useState } from "react";
import { LOCAL_USER_ID } from "@/lib/dev-user";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const authConfigured = Boolean(url && anonKey);
export const localMode = !authConfigured && process.env.NODE_ENV !== "production";

let client: SupabaseClient | null = null;
function supabase(): SupabaseClient | null {
  if (!authConfigured) return null;
  if (!client) client = createClient(url as string, anonKey as string);
  return client;
}

export type AuthState =
  | { status: "loading" }
  | { status: "signed_out" }
  | { status: "misconfigured" }
  | { status: "signed_in"; userId: string; token: string | null; local: boolean };

export function useAuth(): AuthState {
  const [state, setState] = useState<AuthState>(() =>
    localMode
      ? { status: "signed_in", userId: LOCAL_USER_ID, token: null, local: true }
      : authConfigured
        ? { status: "loading" }
        : { status: "misconfigured" },
  );

  useEffect(() => {
    const sb = supabase();
    if (!sb) return;
    const apply = (session: Session | null) =>
      setState(
        session
          ? { status: "signed_in", userId: session.user.id, token: session.access_token, local: false }
          : { status: "signed_out" },
      );
    sb.auth.getSession().then(({ data }) => apply(data.session));
    const { data } = sb.auth.onAuthStateChange((_event, session) => apply(session));
    return () => data.subscription.unsubscribe();
  }, []);

  return state;
}

export async function signInWithGoogle(): Promise<void> {
  const sb = supabase();
  if (!sb) return;
  await sb.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: window.location.href },
  });
}

export async function signOut(): Promise<void> {
  await supabase()?.auth.signOut();
}

export function authHeaders(auth: AuthState): Record<string, string> {
  if (auth.status === "signed_in" && auth.token) {
    return { Authorization: `Bearer ${auth.token}` };
  }
  return {};
}
