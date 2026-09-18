// GET /api/session/{id} 프록시. 공유 링크 화면이 부른다. 로그인 필수.

import { NextResponse } from "next/server";
import { mockSession } from "@/lib/mock";
import { apiBase, forward, mockUser, unauthorized } from "@/lib/proxy";

export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await ctx.params;
  if (apiBase()) return forward(req, `/api/session/${encodeURIComponent(id)}`, "GET");

  if (!mockUser(req)) return unauthorized();
  const res = mockSession(id);
  if (!res) return NextResponse.json({ detail: "세션이 없거나 만료됐습니다" }, { status: 404 });
  return NextResponse.json(res);
}
