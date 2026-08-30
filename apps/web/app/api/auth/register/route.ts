import { NextRequest, NextResponse } from "next/server";
import { register } from "@/lib/agent";
import { setSessionCookie } from "@/lib/auth";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  try {
    const data = await register(body.username, body.password);
    const res = NextResponse.json(data, { status: 201 });
    if (data.token) setSessionCookie(res, data.token);
    return res;
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 400 });
  }
}
