"use client";

import { useEffect, useRef, useState } from "react";
import { Room, RoomEvent, LocalVideoTrack, createLocalTracks, RoomEvent as RE } from "livekit-client";

/** B1/B4: candidate self-view + interview recording via LiveKit.
 * - Joins a LiveKit room for the interview (publishes camera+mic).
 * - Exposes a "开始录制" button that starts egress (room-composite) so the video
 *   is saved and available at /recordings/{id}.mp4 for /share. */
export default function LiveKitRoom({ interviewId }: { interviewId: string }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const roomRef = useRef<Room | null>(null);
  const [status, setStatus] = useState<"idle" | "connecting" | "connected" | "error">("idle");
  const [recording, setRecording] = useState(false);
  const [recordUrl, setRecordUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function join() {
    setStatus("connecting");
    setErr(null);
    try {
      const r = await fetch(`/api/livekit/token/${interviewId}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identity: `candidate-${Math.random().toString(36).slice(2, 8)}` }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "获取 token 失败");
      const room = new Room({ adaptiveStream: true });
      roomRef.current = room;
      room.on(RE.Disconnected, () => setStatus("idle"));
      room.on(RE.Connected, () => setStatus("connected"));
      await room.connect(d.url, d.token);
      // publish camera + mic (individual tracks)
      try {
        const tracks = await createLocalTracks({ video: { deviceId: "default" }, audio: true });
        const videoTrack = tracks.find((t) => t.kind === "video");
        for (const t of tracks) {
          try { await room.localParticipant.publishTrack(t); } catch {}
        }
        if (videoRef.current && videoTrack) {
          videoRef.current.srcObject = new MediaStream([videoTrack.mediaStreamTrack as MediaStreamTrack]);
          videoRef.current.play().catch(() => {});
        }
      } catch {}
    } catch (e) {
      setErr(String(e));
      setStatus("error");
    }
  }

  async function toggleRecord() {
    if (recording) {
      await fetch(`/api/livekit/record/${interviewId}`, { method: "DELETE" }).catch(() => {});
      setRecording(false);
    } else {
      const r = await fetch(`/api/livekit/record/${interviewId}`, { method: "POST" });
      const d = await r.json();
      if (!r.ok) { setErr(d.error || "启动录制失败"); return; }
      setRecording(true);
      setRecordUrl(d.recording_url || `/recordings/${interviewId}.mp4`);
    }
  }

  useEffect(() => () => { roomRef.current?.disconnect(); }, []);

  return (
    <div className="rounded-xl border border-white/10 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm text-white/50">🎥 视频面试间（LiveKit）</div>
        <div className="flex gap-2">
          {status !== "connected" ? (
            <button onClick={join} disabled={status === "connecting"}
              className="rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-3 py-1.5 text-sm">
              {status === "connecting" ? "连接中…" : "连接视频"}
            </button>
          ) : (
            <button onClick={toggleRecord}
              className={`rounded-lg px-3 py-1.5 text-sm ${recording ? "bg-red-500/80 text-white" : "border border-white/10 text-white/70"}`}>
              {recording ? "停止录制" : "开始录制"}
            </button>
          )}
        </div>
      </div>
      {status === "connected" && (
        <video ref={videoRef} muted playsInline autoPlay className="w-full rounded-lg bg-black max-h-64" />
      )}
      {recordUrl && recording && (
        <div className="text-xs text-emerald-300 mt-2">录制中… 结束后可在报告/分享页下载。</div>
      )}
      {err && <div className="text-red-400 text-sm mt-2">{err}</div>}
    </div>
  );
}
