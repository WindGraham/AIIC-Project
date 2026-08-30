import { NextRequest, NextResponse } from "next/server";
import { getRecap } from "@/lib/agent";

export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    return NextResponse.json(await getRecap(id));
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
