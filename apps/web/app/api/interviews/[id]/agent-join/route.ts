import { NextRequest, NextResponse } from "next/server";
import { agentJoin } from "@/lib/agent";

/** POST /api/interviews/[id]/agent-join
 * Proxies the agent's agent-join (ensure room + mint agent token + best-effort
 * recording). The agent returns a browser-reachable URL (default
 * wss://voice.windgraham.art) — keep it so the browser can actually connect. */
export async function POST(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const data = await agentJoin(id);
    if (!data?.url) data.url = "wss://voice.windgraham.art";
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
