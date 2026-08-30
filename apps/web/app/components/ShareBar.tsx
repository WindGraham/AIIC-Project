"use client";

import { useState } from "react";

/** Share bar for the report page: copy share link, download transcript, play audio recap. */
export default function ShareBar({ interviewId }: { interviewId: string }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function copyLink() {
    const url = `${location.origin}/share/${interviewId}`;
    try {
      await navigator.clipboard.writeText(url);
      setMsg("分享链接已复制：" + url);
    } catch {
      setMsg("分享链接：" + url);
    }
  }

  async function downloadTranscript() {
    setBusy(true);
    setMsg(null);
    try {
      const d = await (await fetch(`/api/interviews/${interviewId}/transcript`)).json();
      const blob = new Blob([d.text || ""], { type: "text/plain;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "面试转写.txt";
      a.click();
      URL.revokeObjectURL(a.href);
      setMsg("文字稿已下载。");
    } catch {
      setMsg("转写下载失败。");
    } finally {
      setBusy(false);
    }
  }

  async function playRecap() {
    setBusy(true);
    setMsg(null);
    try {
      const d = await (await fetch(`/api/interviews/${interviewId}/recap`)).json();
      if (d.audio_b64) {
        const audio = new Audio(`data:audio/mp3;base64,${d.audio_b64}`);
        await audio.play();
        setMsg("语音回顾播放中…（" + (d.text || "").slice(0, 60) + "…）");
      }
    } catch {
      setMsg("语音回顾生成失败。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap gap-2 mt-4">
      <button onClick={copyLink} className="rounded-lg bg-white/10 hover:bg-white/20 px-4 py-2 text-sm">🔗 复制分享链接</button>
      <button onClick={downloadTranscript} disabled={busy} className="rounded-lg bg-white/10 hover:bg-white/20 px-4 py-2 text-sm">📄 下载文字稿</button>
      <button onClick={playRecap} disabled={busy} className="rounded-lg bg-white/10 hover:bg-white/20 px-4 py-2 text-sm">🔊 语音回顾(录制)</button>
      {msg && <p className="text-xs text-white/60 w-full mt-1">{msg}</p>}
    </div>
  );
}
