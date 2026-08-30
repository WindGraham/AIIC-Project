import { NextRequest, NextResponse } from "next/server";
import { listBookings } from "@/lib/agent";

export async function GET() {
  try {
    return NextResponse.json(await listBookings());
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
