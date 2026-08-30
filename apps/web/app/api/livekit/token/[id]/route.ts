import { NextRequest, NextResponse } from "next/server";
import { AccessToken } from "livekit-server-sdk";

/** Issue a LiveKit participant token for the interview room.
 * The candidate joins as the publisher (publishes camera/mic); no AI bot is
 * needed for the self-view/recording flow. `grant` = the participant's identity. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.json().catch(() => ({}));
  const identity = String(body.identity || "candidate");

  const url = process.env.LIVEKIT_URL || "ws://127.0.0.1:7880";
  const key = process.env.LIVEKIT_API_KEY;
  const secret = process.env.LIVEKIT_API_SECRET;
  if (!key || !secret) {
    return NextResponse.json({ error: "livekit not configured" }, { status: 500 });
  }

  const roomName = `probedesk-${id}`;
  const at = new AccessToken(key, secret, {
    identity,
    name: "Candidate",
    ttl: "10m",
  });
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
