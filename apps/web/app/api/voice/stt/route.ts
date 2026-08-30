import { NextRequest, NextResponse } from "next/server";
import { voiceStt } from "@/lib/agent";

/** Proxy voice->text (STT). The browser calls /api/voice/stt; we forward to the agent. */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  try {
    const data = await voiceStt(body);
    return NextResponse.json(data);
  } catch (e: any) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
