import { NextRequest, NextResponse } from "next/server";
import { listJds, createJd } from "@/lib/agent";

export async function GET() {
  try {
    return NextResponse.json(await listJds());
  } catch (e: any) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  try {
    return NextResponse.json(await createJd(body), { status: 201 });
  } catch (e: any) {
    return NextResponse.json({ error: String(e) }, { status: 400 });
  }
}
