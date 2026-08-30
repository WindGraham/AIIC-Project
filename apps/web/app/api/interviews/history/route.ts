import { NextRequest, NextResponse } from "next/server";
import { getHistory } from "@/lib/agent";

export async function GET() {
  try {
    return NextResponse.json(await getHistory());
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
