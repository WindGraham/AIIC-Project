"use client";

import { useRef, useState } from "react";
import { createRecorder } from "@/lib/voice";

/**
 * 功能测试 A：语音气泡 → 转文字(STT) → 再把文字转成 TTS 语音回放。
 * 按住说话 → /api/voice/stt 转文字 → 显示文字气泡 → 点播放 → /api/voice/tts 合成语音。
 */
export default function VoiceTextTts() {
  const [recording, setRecording] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ttsB64, setTtsB64] = useState<string | null>(null);
  const recorderRef = useRef<ReturnType<typeof createRecorder> | null>(null);

  async function capture() {
    if (!recorderRef.current) recorderRef.current = createRecorder();
    try {
      await recorderRef.current.start();
      setRecording(true);
      setErr(null);
    } catch (e: any) {
      setErr("麦克风不可用：" + (e?.message || String(e)));
    }
  }

  async function release() {
    if (!recorderRef.current || !recording) return;
    setRecording(false);
    setBusy(true);
    setErr(null);
    try {
      const wav = await recorderRef.current.stop();
      recorderRef.current = null;
      const stt = await (
        await fetch("/api/voice/stt", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ audio_b64: wav, format: "wav" }),
        })
      ).json();
      const t: string = stt?.text || "";
      setText(t);
      if (t) {
        // 把文字转回 TTS 语音
        const tts = await (
          await fetch("/api/voice/tts", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: t }),
          })
        ).json();
        setTtsB64(tts?.audio_b64 || null);
      } else {
        setErr("没有识别到语音，请重试。");
      }
    } catch (e: any) {
      setErr("转换失败：" + (e?.message || String(e)));
    } finally {
      setBusy(false);
    }
  }

  function playTts() {
    if (!ttsB64) return;
    const a = new Audio(`data:audio/mp3;base64,${ttsB64}`);
    a.play().catch(() => {});
  }

  return (
    <div className="rounded-2xl border border-white/10 p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm text-white/50">A. 语音气泡 → 文字 → TTS 语音</div>
        <div className="text-xs text-white/40">按住说话</div>
      </div>

      <div className="flex items-center gap-3">
        <button
          onPointerDown={capture}
          onPointerUp={release}
          onPointerLeave={release}
          onContextMenu={(e) => e.preventDefault()}
          disabled={busy}
          className={`select-none rounded-lg border px-6 py-3 font-semibold transition-colors ${
            recording ? "bg-emerald-500/30 border-emerald-400/50 text-emerald-200" : "border-white/10 bg-white/5 hover:bg-white/10 text-white/70"
          }`}
        >
          {recording ? "松开即发送" : busy ? "转换中…" : "🎙️ 按住说话"}
        </button>
        {text && (
          <div className="flex items-center gap-2 rounded-xl bg-indigo-600 px-3 py-2 text-sm">
            <span>💬</span><span className="text-white/90">{text}</span>
          </div>
        )}
      </div>

      {ttsB64 && (
        <div className="mt-3 flex items-center gap-2">
          <button onClick={playTts} className="rounded-lg border border-white/10 hover:border-white/30 px-3 py-1.5 text-sm text-white/80">
            🔊 播放 TTS 语音
          </button>
          <span className="text-xs text-white/40">已把识别文字再合成为语音</span>
        </div>
      )}

      {err && <div className="text-red-400 text-xs mt-2">{err}</div>}
      <p className="text-xs text-white/40 mt-2">流程：录音 → STT 转文字 → 文字气泡 → TTS 合成语音回放。</p>
    </div>
  );
}
