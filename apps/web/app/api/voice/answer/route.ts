import { NextRequest, NextResponse } from "next/server";
import { voiceAnswer } from "@/lib/agent";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  try {
    const data = await voiceAnswer(body);
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
