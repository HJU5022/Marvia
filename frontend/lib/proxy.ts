// app/api/ 라우트 공용. 브라우저 요청을 백엔드(Cloud Run)로 넘긴다. 서버에서만 쓴다.
// NEXT_PUBLIC_API_BASE 가 없으면 null 을 돌려주고, 호출한 라우트가 lib/mock.ts 로 답한다.

import { NextResponse } from "next/server";
import { LOCAL_USER_ID } from "@/lib/dev-user";

export function apiBase(): string | null {
  const base = process.env.NEXT_PUBLIC_API_BASE;
  return base ? base.replace(/\/$/, "") : null;
}

export async function forward(req: Request, path: string, method: string): Promise<Response> {
  const base = apiBase();
  if (!base) throw new Error("NEXT_PUBLIC_API_BASE 가 없습니다");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const auth = req.headers.get("authorization");
  if (auth) headers.Authorization = auth;
  const body = method === "GET" ? undefined : await req.text();
  try {
    const res = await fetch(`${base}${path}`, { method, headers, body, cache: "no-store" });
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return NextResponse.json({ detail: "백엔드에 연결하지 못했습니다" }, { status: 502 });
  }
}

// mock 응답에서 쓸 사용자. 로그인 없는 mock 은 개발 서버에서만 허용한다 (익명 열람 경로 금지).
export function mockUser(req: Request): string | null {
  const auth = req.headers.get("authorization");
  if (auth?.startsWith("Bearer ")) return jwtSubject(auth.slice(7));
  return process.env.NODE_ENV === "production" ? null : LOCAL_USER_ID;
}

// mock 전용. 서명은 검증하지 않고 sub 만 읽는다. 실제 검증은 백엔드 services/auth.py 가 한다.
function jwtSubject(token: string): string | null {
  try {
    const payload = token.split(".")[1];
    const json = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as { sub?: unknown };
    return typeof json.sub === "string" ? json.sub : null;
  } catch {
    return null;
  }
}

export function unauthorized(): Response {
  return NextResponse.json({ detail: "로그인이 필요합니다" }, { status: 401 });
}
