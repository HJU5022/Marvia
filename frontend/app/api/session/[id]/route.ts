// GET /api/session/{id} 프록시. 공유 링크 화면이 부른다. 로그인 필수.
// DELETE 도 같은 자리. 내 계획 목록에서 지울 때 쓴다 (SDD 2절, 주선자 본인만).

import { NextResponse } from "next/server";
import { mockDeleteSession, mockSession } from "@/lib/mock";
import { apiBase, forward, mockUser, unauthorized } from "@/lib/proxy";

export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await ctx.params;
  if (apiBase()) return forward(req, `/api/session/${encodeURIComponent(id)}`, "GET");

  if (!mockUser(req)) return unauthorized();
  const res = mockSession(id);
  if (!res) return NextResponse.json({ detail: "세션이 없거나 만료됐습니다" }, { status: 404 });
  return NextResponse.json(res);
}


export async function DELETE(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await ctx.params;
  if (apiBase()) return forward(req, `/api/session/${encodeURIComponent(id)}`, "DELETE");

  if (!mockUser(req)) return unauthorized();
  mockDeleteSession(id);
  return new NextResponse(null, { status: 204 });
}
