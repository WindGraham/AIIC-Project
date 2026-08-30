import { NextRequest, NextResponse } from "next/server";
import { bookInterview } from "@/lib/agent";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  try {
    const data = await bookInterview(body);
    return NextResponse.json(data, { status: 201 });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 400 });
  }
}
