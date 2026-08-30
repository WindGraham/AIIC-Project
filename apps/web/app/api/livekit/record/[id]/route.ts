import { NextRequest, NextResponse } from "next/server";
import { EgressClient, EncodedFileOutput, EncodedFileType, EncodingOptionsPreset } from "livekit-server-sdk";

/** LiveKit egress: start recording a room (RoomComposite) so the interview video
 * can be downloaded / shared. Egress writes to the mounted record dir; the file
 * is served through a static path we map to a public URL. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const url = process.env.LIVEKIT_URL || "ws://127.0.0.1:7880";
  const key = process.env.LIVEKIT_API_KEY;
  const secret = process.env.LIVEKIT_API_SECRET;
  if (!key || !secret) return NextResponse.json({ error: "livekit not configured" }, { status: 500 });

  const roomName = `probedesk-${id}`;
  try {
    const egressClient = new EgressClient(url, key, secret);
    const eg = await egressClient.startRoomCompositeEgress(roomName, {
      file: new EncodedFileOutput({ filepath: `/data/livekit/recordings/${id}.mp4`, fileType: EncodedFileType.MP4 }),
    }, undefined, EncodingOptionsPreset.H264_720P_30);
    return NextResponse.json({ egress_id: eg.egressId, status: "started", room: roomName, recording_url: `/recordings/${id}.mp4` });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const url = process.env.LIVEKIT_URL || "ws://127.0.0.1:7880";
  const key = process.env.LIVEKIT_API_KEY;
  const secret = process.env.LIVEKIT_API_SECRET;
  try {
    const egressClient = new EgressClient(url, key, secret);
    // list active egress for this room and stop them
    const all = await egressClient.listEgress({ roomName: `probedesk-${id}` });
    for (const e of all) await egressClient.stopEgress(e.egressId);
    return NextResponse.json({ ok: true, stopped: all.length });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
