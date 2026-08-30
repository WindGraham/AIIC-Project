import { NextRequest, NextResponse } from "next/server";
import { agentStatus } from "@/lib/agent";

/** GET /api/interviews/[id]/agent-status
 * Proxies the agent's room status (participants + tracks + agent presence). */
export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    return NextResponse.json(await agentStatus(id));
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
