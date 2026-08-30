import { NextRequest, NextResponse } from "next/server";
import { startBooking } from "@/lib/agent";

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const data = await startBooking(id);
    return NextResponse.json(data, { status: 202 });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 400 });
  }
}
