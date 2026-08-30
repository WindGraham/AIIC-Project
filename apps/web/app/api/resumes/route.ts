import { NextRequest, NextResponse } from "next/server";
import { createResume, listResumes } from "@/lib/agent";

export async function GET() {
  try {
    return NextResponse.json(await listResumes());
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  try {
    const data = await createResume(body);
    return NextResponse.json(data, { status: 201 });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 400 });
  }
}
