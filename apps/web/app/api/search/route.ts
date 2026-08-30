import { NextRequest, NextResponse } from "next/server";
import { searchSources } from "@/lib/agent";

/** Proxy info search (search engines + social platforms). */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  try {
    return NextResponse.json(await searchSources(body));
  } catch (e: any) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
