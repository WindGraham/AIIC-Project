import { NextRequest, NextResponse } from "next/server";
import { AccessToken } from "livekit-server-sdk";

/** Issue a LiveKit participant token for the interview room (方案2: components-react).
 * The candidate (or agent) joins with publish/subscribe grants. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.json().catch(() => ({}));
  const identity = String(body.identity || "candidate");
  const name = String(body.name || "候选人");

  // Use the PUBLIC wss URL for the client (browser must reach it), falling back
  // to the internal ws URL only for server-side calls. Never hand the browser a
  // 127.0.0.1 URL or external clients can't join.
  const url = process.env.LIVEKIT_PUBLIC_URL || process.env.LIVEKIT_URL || "wss://voice.windgraham.art";
  const key = process.env.LIVEKIT_API_KEY;
  const secret = process.env.LIVEKIT_API_SECRET;
  if (!key || !secret) return NextResponse.json({ error: "livekit not configured" }, { status: 500 });

  const roomName = `probedesk-${id}`;
  const at = new AccessToken(key, secret, { identity, name, ttl: "60m" });
  at.addGrant({
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canSubscribe: true,
    canPublishData: true,
  });
  const token = await at.toJwt();
  return NextResponse.json({ token, room: roomName, url });
}
