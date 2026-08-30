import { NextRequest, NextResponse } from "next/server";
import { getSessionToken } from "@/lib/auth";

const AGENT_BASE = process.env.AGENT_API_URL || "http://127.0.0.1:8000";

/** Server-side proxy for resume file decoding (base64 -> agent -> text).
 * The browser sends {data, filename}; we forward to the agent's /api/parse/resume.
 * The agent decodes PDF/DOCX/MD/TXT/XLSX offline and returns the extracted text. */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  if (!body?.data) return NextResponse.json({ error: "no file data" }, { status: 400 });
  const token = await getSessionToken();
  try {
    const res = await fetch(`${AGENT_BASE}/api/parse/resume`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ data: body.data, filename: body.filename || "" }),
    });
    const d = await res.json();
    if (!res.ok) return NextResponse.json({ error: d?.detail || d?.error || "decode failed" }, { status: res.status });
    return NextResponse.json(d);
  } catch (e: any) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
