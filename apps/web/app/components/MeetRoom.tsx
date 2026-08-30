"use client";

import { useEffect, useState } from "react";

/** Embed the livekit-meet interview room (full video grid + mic/camera + the
 * meet UI's recording/egress controls) inside ProbeDesk. This reuses the
 * already-running livekit-meet frontend rather than re-implementing a video room.
 * `recording_url` (if an egress produced a file) is surfaced via /recordings. */
export default function MeetRoom({ interviewId, onHeights }: { interviewId: string; onHeights?: (h: number) => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const d = await (await fetch(`/api/livekit/room/${interviewId}`)).json();
        setUrl(d.url);
      } catch (e) {
        setErr(String(e));
      }
    })();
  }, [interviewId]);

  if (err) return <div className="rounded-xl border border-white/10 p-4 text-red-400 text-sm">视频房间加载失败：{err}</div>;

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-white/5">
        <div className="text-sm text-white/60">🎥 视频面试间（LiveKit Meet）</div>
        <div className="text-xs text-white/40">语音 / 摄像头 / 录制 / 转写</div>
      </div>
      {url ? (
        <iframe
          src={url}
          title="ProbeDesk 视频面试间"
          className="w-full bg-black"
          style={{ height: 560, border: 0 }}
          allow="camera; microphone; display-capture; fullscreen"
          allowFullScreen
        />
      ) : (
        <div className="h-24 flex items-center justify-center text-white/40 text-sm">正在加载视频面试间…</div>
      )}
    </div>
  );
}
