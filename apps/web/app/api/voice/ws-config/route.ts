import { NextResponse } from "next/server";

/**
 * Returns the agent WebSocket base URL for the full-duplex voice client.
 *
 * The browser cannot read server-side env (AGENT_API_URL / AGENT_WS_URL), so
 * this tiny HTTP route is the single source of truth: the client fetches it at
 * runtime and appends `?interview_id=<id>` before opening the socket.
 *
 * WHY NOT A RAW WS PROXY HERE? Next.js App Router route handlers are plain
 * request/response functions — Next never hands them the HTTP upgrade, so they
 * cannot tunnel a WebSocket to the agent. The client therefore connects to the
 * agent directly; in production nginx performs the upgrade (see
 * deploy/nginx.conf, `location /ws/voice`).
 */

export const dynamic = "force-dynamic";

function toWsUrl(httpUrl: string): string {
  try {
    const u = new URL(httpUrl);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.pathname = "/ws/voice";
    u.search = "";
    return u.toString().replace(/\/+$/, "");
  } catch {
    return "ws://127.0.0.1:8000/ws/voice";
  }
}

export async function GET() {
  const explicit = process.env.AGENT_WS_URL?.trim();
  const url = explicit || toWsUrl(process.env.AGENT_API_URL || "http://127.0.0.1:8000");
  return NextResponse.json({ url, endpoint: "ws://<agent>/ws/voice?interview_id=<id>" });
}
