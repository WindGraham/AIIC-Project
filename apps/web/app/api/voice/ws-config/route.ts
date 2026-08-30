import { NextRequest, NextResponse } from "next/server";

/**
 * Returns the agent WebSocket base URL for the full-duplex voice client.
 *
 * The browser cannot read server-side env (AGENT_API_URL / AGENT_WS_URL), so this
 * route is the single source of truth. The client fetches it at runtime and appends
 * `?interview_id=<id>` before opening the socket.
 *
 * IMPORTANT: the returned URL must be *browser-reachable* — never 127.0.0.1. We
 * build it from the request's Host so the socket goes to the same public host the
 * page is served from (nginx upgrades /ws/voice -> agent), e.g. wss://mock.windgraham.art/ws/voice.
 *
 * WHY NOT A RAW WS PROXY HERE? Next.js App Router route handlers are plain
 * request/response functions — Next never hands them the HTTP upgrade, so they cannot
 * tunnel a WebSocket to the agent. The client therefore connects to the agent
 * directly; nginx performs the upgrade (see deploy/nginx.conf, `location /ws/voice`).
 */

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  // 1) Explicit build-time override.
  const explicit = process.env.NEXT_PUBLIC_AGENT_WS_URL?.trim() || process.env.AGENT_WS_URL?.trim();
  if (explicit) return NextResponse.json({ url: explicit.replace(/\/$/, ""), endpoint: "wss://<host>/ws/voice?interview_id=<id>" });

  // 2) Same-origin, derived from the browser's request host (browser-reachable public URL).
  const host = req.headers.get("host") || req.nextUrl.host || "mock.windgraham.art";
  const proto = req.nextUrl.protocol.startsWith("https") ? "wss" : "ws";
  const url = `${proto}://${host}/ws/voice`;
  return NextResponse.json({ url, endpoint: "wss://<host>/ws/voice?interview_id=<id>" });
}
