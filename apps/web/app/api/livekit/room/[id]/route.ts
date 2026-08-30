import { NextRequest, NextResponse } from "next/server";

/** Returns the livekit-meet embed URL for an interview room. The meet frontend
 * (voice.windgraham.art) owns the video/recording(egress)/transcription UI. A
 * per-interview room name avoids collisions; the room password is validated
 * server-side by meet's /api/connection-details. */
export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const safe = (id || "").replace(/[^a-zA-Z0-9_-]/g, "") || "interview";
  const meetUrl = process.env.MEET_URL || "https://voice.windgraham.art";
  const password = process.env.MEET_PASSWORD || "";
  const room = `probedesk-${safe}`;
  const embedUrl = `${meetUrl}/rooms/${encodeURIComponent(room)}?participantName=${encodeURIComponent("候选人")}` +
    (password ? `&password=${encodeURIComponent(password)}` : "");
  return NextResponse.json({ url: embedUrl, room, meetUrl });
}
