// GET /api/sessions 프록시. 내 계획 목록 (SDD 2절).

import { NextResponse } from "next/server";
import { mockSessionList } from "@/lib/mock";
import { apiBase, forward, mockUser, unauthorized } from "@/lib/proxy";

export async function GET(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const query = url.searchParams.toString();
  if (apiBase()) return forward(req, `/api/sessions${query ? `?${query}` : ""}`, "GET");

  const user = mockUser(req);
  if (!user) return unauthorized();
  return NextResponse.json(mockSessionList());
}
