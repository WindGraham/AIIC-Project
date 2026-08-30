import { NextRequest, NextResponse } from "next/server";
import { jumpToCode } from "@/lib/agent";

export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    return NextResponse.json(await jumpToCode(id));
  } catch (e: any) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
