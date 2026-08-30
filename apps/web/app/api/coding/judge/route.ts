import { NextRequest, NextResponse } from "next/server";
import { codingJudge } from "@/lib/agent";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  try {
    return NextResponse.json(await codingJudge(body));
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
