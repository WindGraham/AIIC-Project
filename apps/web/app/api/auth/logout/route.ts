import { NextRequest, NextResponse } from "next/server";
import { logout } from "@/lib/agent";
import { clearSessionCookie, getSessionToken } from "@/lib/auth";

export async function POST(req: NextRequest) {
  const token = await getSessionToken();
  try {
    if (token) await logout(token);
  } catch {
    /* ignore */
  }
  const res = NextResponse.json({ ok: true });
  clearSessionCookie(res);
  return res;
}
