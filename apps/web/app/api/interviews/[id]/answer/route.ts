import { NextRequest, NextResponse } from "next/server";
import { postAnswer } from "@/lib/agent";

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.json().catch(() => ({ answer: "" }));
  try {
    const data = await postAnswer(id, String(body.answer ?? ""));
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
