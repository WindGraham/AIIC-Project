"use client";

import { useState } from "react";

/** "让 AI 看我的屏幕" — capture a display frame -> Gemini vision -> describe.
 * Demonstrates the AI reading a shared screen/video stream (downsampled to a
 * frame). Browser gate: getDisplayMedia must be triggered by a user gesture. */
export default function ScreenRead({ onRead }: { onRead?: (text: string) => void }) {
  const [desc, setDesc] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function capture() {
    setBusy(true);
    setDesc(null);
    try {
      const stream = await (navigator.mediaDevices as any).getDisplayMedia({ video: true, audio: false });
      const video = document.createElement("video");
      video.srcObject = stream;
      await new Promise<void>((r) => { video.onloadedmetadata = () => r(); });
      video.play();
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth || 1280;
      canvas.height = video.videoHeight || 720;
      canvas.getContext("2d")!.drawImage(video, 0, 0, canvas.width, canvas.height);
      const b64 = canvas.toDataURL("image/png").split(",")[1];
      stream.getTracks().forEach((t: MediaStreamTrack) => t.stop());
      const d = await (await fetch("/api/vision/analyze", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_b64: b64, prompt: "请读取并简要描述这个与面试相关的画面里最重要的内容。" }),
      })).json();
      const text = d.description || d.error || "(无描述)";
      setDesc(text);
      if (onRead) onRead(text);
    } catch (e) {
      setDesc("无法捕捉屏幕：" + String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl border border-white/10 p-4">
      <button onClick={capture} disabled={busy}
        className="rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-50 px-4 py-2 text-sm font-semibold">
        {busy ? "AI 读取中…" : "🖥️ 让面试官看我的屏幕"}
      </button>
      {desc && <p className="mt-2 text-sm text-white/80 whitespace-pre-wrap">🧠 面试官看到：{desc}</p>}
      <p className="mt-2 text-xs text-white/40">AI 具备读屏幕/视频流的能力（Gemini 视觉），此处以共享屏幕帧演示。</p>
    </div>
  );
}
