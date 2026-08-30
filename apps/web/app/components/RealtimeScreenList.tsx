"use client";

import { useEffect, useRef, useState } from "react";
import { getLiveKitRoom } from "@/lib/livekit-room";

/**
 * 功能测试 B：开摄像头/共享屏 → 实时流读屏 → 右侧列表不断更新每一帧内容。
 * 直接从 LiveKit 房间的 localParticipant 取当前视频帧，每 2s 一帧(原图)→ Kimi 读屏，
 * 结果追加进滚动列表（时间戳 + 内容），验证"实时视频流 → 文字旁注"链路。
 */
export default function RealtimeScreenList() {
  const [items, setItems] = useState<{ ts: string; text: string }[]>([]);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const roomCardRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const room = getLiveKitRoom();
    if (!room) return;
    const iv = window.setInterval(() => {
      const pubs = room.localParticipant.getTrackPublications();
      const hasVideo = pubs.some((p) => p.track?.kind === "video");
      const on = hasVideo;
      setRunning(on);
    }, 1000);
    return () => window.clearInterval(iv);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let last = new Date(0);
    async function tick() {
      const room = getLiveKitRoom();
      if (!room || cancelled) return;
      const pubs = room.localParticipant.getTrackPublications();
      const scr = pubs.find((p) => p.track?.kind === "video" && (p.source as string) === "screen_share");
      const src = scr?.track?.mediaStreamTrack || pubs.find((p) => p.track?.kind === "video")?.track?.mediaStreamTrack;
      if (!src) return;
      const v = document.createElement("video");
      v.srcObject = new MediaStream([src]);
      v.autoplay = true; v.muted = true; v.playsInline = true;
      await v.play().catch(() => {});
      await new Promise((r) => setTimeout(r, 300));
      if (cancelled || v.videoWidth === 0) return;
      if (Date.now() - last.getTime() < 2000) return;
      last = new Date();
      const canvas = document.createElement("canvas");
      canvas.width = v.videoWidth; canvas.height = v.videoHeight;
      canvas.getContext("2d")!.drawImage(v, 0, 0, canvas.width, canvas.height);
      const b64 = canvas.toDataURL("image/jpeg", 0.8).split(",")[1];
      try {
        const d = await (
          await fetch("/api/vision/analyze", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ image_b64: b64, mime: "image/jpeg", prompt: "这是屏幕实时画面的一帧。用一句中文简述画面中与面试相关的最重要内容，不超过30字。" }),
          })
        ).json();
        const text: string = d?.description || "";
        if (text && !text.startsWith("(reading failed")) {
          setItems((prev) => [...prev, { ts: new Date().toLocaleTimeString(), text }].slice(-40));
          if (roomCardRef.current) roomCardRef.current.scrollTop = roomCardRef.current.scrollHeight;
        }
      } catch { /* next tick */ }
    }
    const iv = window.setInterval(tick, 1500);
    return () => { cancelled = true; window.clearInterval(iv); };
  }, []);

  return (
    <div className="rounded-2xl border border-white/10 p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm text-white/50">
          B. 实时流读屏
          <span className={`ml-2 rounded-full px-2 py-0.5 text-xs ${running ? "bg-emerald-500/20 text-emerald-300" : "bg-white/5 text-white/40"}`}>
            {running ? "摄像头/共享已开启" : "未开启摄像头/共享"}
          </span>
        </div>
        <div className="text-xs text-white/40">每一帧内容（Kimi 读屏）</div>
      </div>
      <p className="text-xs text-white/40 mb-2">打开摄像头或共享屏后，下方列表会不断滚动更新每一帧读出的内容。</p>
      <div ref={roomCardRef} className="max-h-56 overflow-auto rounded-lg border border-white/10 bg-black/20 p-3 flex flex-col gap-1">
        {items.length === 0 && <div className="text-white/30 text-xs">{running ? "正在读取画面…" : "请先打开摄像头或共享屏幕。"}</div>}
        {items.map((it, i) => (
          <div key={i} className="text-xs flex gap-2">
            <span className="text-white/30 shrink-0">{it.ts}</span>
            <span className="text-white/80">{it.text}</span>
          </div>
        ))}
      </div>
      {err && <div className="text-red-400 text-xs mt-2">{err}</div>}
    </div>
  );
}
