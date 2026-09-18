// PATCH /api/session/{id}/participants 프록시. 핀 claim·위치 수정 (SDD 7절 핀 소유권). 로그인 필수.

import { NextResponse } from "next/server";
import { mockPatch } from "@/lib/mock";
import { apiBase, forward, mockUser, unauthorized } from "@/lib/proxy";
import type { ParticipantPatchRequest } from "@/types/agent";

export async function PATCH(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await ctx.params;
  if (apiBase()) return forward(req, `/api/session/${encodeURIComponent(id)}/participants`, "PATCH");

  const user = mockUser(req);
  if (!user) return unauthorized();
  const body = (await req.json()) as ParticipantPatchRequest;
  const out = mockPatch(id, user, body);
  return NextResponse.json(out.body, { status: out.status });
}
