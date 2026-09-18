"use client";

// 로그인 뒤에만 children 을 보여준다. 익명 열람 경로는 없다 (SDD 2절).

import type { ReactNode } from "react";
import { signInWithGoogle, signOut, type AuthState } from "@/lib/auth";

interface Props {
  auth: AuthState;
  reason: string;
  children: ReactNode;
}

export default function AuthGate({ auth, reason, children }: Props) {
  if (auth.status === "loading") {
    return <div className="gate">로그인 상태를 확인하는 중…</div>;
  }
  if (auth.status === "misconfigured") {
    return (
      <div className="gate">
        <p>로그인 설정이 없어 서비스를 열 수 없습니다.</p>
        <p className="muted">NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY 를 확인하세요.</p>
      </div>
    );
  }
  if (auth.status === "signed_out") {
    return (
      <div className="gate">
        <p>{reason}</p>
        <button type="button" className="primary" onClick={() => void signInWithGoogle()}>
          구글로 로그인
        </button>
      </div>
    );
  }
  return <>{children}</>;
}

export function UserBar({ auth }: { auth: AuthState }) {
  if (auth.status !== "signed_in") return null;
  return (
    <span className="userbar">
      {auth.local ? (
        <span className="badge badge-warn">로컬 모드 · 인증 없음</span>
      ) : (
        <button type="button" className="link" onClick={() => void signOut()}>
          로그아웃
        </button>
      )}
    </span>
  );
}
