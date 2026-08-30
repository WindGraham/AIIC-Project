import { NextRequest, NextResponse } from "next/server";
import { prepareInterview } from "@/lib/agent";

export async function POST(req: NextRequest) {
  const body = await req.json();
  try {
    const data = await prepareInterview(body);
    return NextResponse.json(data, { status: 201 });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
