import { NextRequest, NextResponse } from "next/server";
import { voiceTts } from "@/lib/agent";

/** Proxy text->voice (TTS). The browser calls /api/voice/tts; we forward to the agent. */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  try {
    const data = await voiceTts(body);
    return NextResponse.json(data);
  } catch (e: any) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
