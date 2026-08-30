"use client";

import { useEffect, useRef, useState } from "react";

type DeviceState = "idle" | "requesting" | "streaming" | "error";

function DeviceCard({ type }: { type: "mic" | "camera" | "screen" }) {
  const [state, setState] = useState<DeviceState>("idle");
  const [err, setErr] = useState<string | null>(null);
  const [levels, setLevels] = useState<number[]>([]);
  const [recording, setRecording] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [playUrl, setPlayUrl] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const rafRef = useRef<number>(0);
  const ctxRef = useRef<AudioContext | null>(null);

  useEffect(() => () => { stop(); }, []);

  function cleanup() {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    setLevels([]);
  }

  async function start() {
    setState("requesting");
    setErr(null);
    cleanup();
    try {
      let stream: MediaStream;
      if (type === "mic") {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } else if (type === "camera") {
        stream = await navigator.mediaDevices.getUserMedia({ video: true });
      } else {
        stream = await (navigator.mediaDevices as any).getDisplayMedia({ video: true });
      }
      streamRef.current = stream;
      setState("streaming");

      if (type === "camera" || type === "screen") {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => {});
        }
      }

      if (type === "mic") {
        const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
        ctxRef.current = ctx;
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        ctx.createMediaStreamSource(stream).connect(analyser);
        const data = new Uint8Array(analyser.frequencyBinCount);
        const loop = () => {
          analyser.getByteFrequencyData(data);
          const avg = data.reduce((a, b) => a + b, 0) / data.length;
          setLevels((prev) => [...prev.slice(-39), Math.round(avg / 255 * 100)]);
          rafRef.current = requestAnimationFrame(loop);
        };
        loop();
      }

      // recorder (audio) for mic+screen; video for camera+screen
      const mime = type === "mic" ? "audio/webm" : "video/webm";
      if (MediaRecorder.isTypeSupported(mime)) {
        const rec = new MediaRecorder(stream, type === "mic" ? { mimeType: mime } : { mimeType: mime });
        rec.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
        rec.onstop = () => {
          const blob = new Blob(chunksRef.current, { type: mime });
          chunksRef.current = [];
          const url = URL.createObjectURL(blob);
          setPlayUrl(url);
        };
        recorderRef.current = rec;
      }
    } catch (ex) {
      setErr(String(ex));
      setState("error");
    }
  }

  function record() {
    const rec = recorderRef.current;
    if (!rec) return;
    if (recording) { rec.stop(); setRecording(false); }
    else { chunksRef.current = []; rec.start(); setRecording(true); }
  }

  function stop() {
    cleanup();
    if (recorderRef.current && recorderRef.current.state !== "inactive") recorderRef.current.stop();
    setRecording(false);
    setState("idle");
  }

  const titles = { mic: "麦克风", camera: "摄像头", screen: "屏幕共享" };
  const hints = {
    mic: "测试录音与回放，不接通面试官",
    camera: "测试摄像头画面",
    screen: "测试屏幕共享（AI 将看到你的画面）",
  };

  return (
    <div className="rounded-xl border border-white/10 p-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-medium">{titles[type]}</div>
          <div className="text-xs text-white/40">{hints[type]}</div>
        </div>
        {state === "streaming" ? (
          <button onClick={stop} className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-white/70">停止</button>
        ) : (
          <button onClick={start} disabled={state === "requesting"}
            className="rounded-lg bg-indigo-500 hover:bg-indigo-400 px-3 py-1.5 text-sm disabled:opacity-50">
            {state === "requesting" ? "请求中…" : "开始测试"}
          </button>
        )}
      </div>

      {state === "streaming" && (type === "camera" || type === "screen") && (
        <video ref={videoRef} muted playsInline className="mt-3 rounded-lg bg-black w-full max-h-56" />
      )}

      {state === "streaming" && type === "mic" && (
        <div className="mt-3 flex items-end gap-0.5 h-16">
          {(levels.length ? levels : Array(40).fill(0)).map((v, i) => (
            <div key={i} className="flex-1 rounded-sm bg-indigo-400/70" style={{ height: `${Math.max(4, v)}%` }} />
          ))}
        </div>
      )}

      {state === "streaming" && (
        <div className="mt-3 flex gap-3">
          <button onClick={record} className={`rounded-lg px-3 py-1.5 text-sm ${recording ? "bg-red-500/80" : "border border-white/10 text-white/70"}`}>
            {recording ? "停止录制" : "录制"}
          </button>
          {playUrl && (
            <a href={playUrl} download="probedesk-test.webm" className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-white/70">下载回放</a>
          )}
        </div>
      )}
      {playUrl && (
        <audio key={playUrl} controls src={playUrl} className="mt-3 w-full" onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} />
      )}

      {err && <div className="text-red-400 text-sm mt-3">{err}</div>}
    </div>
  );
}

export default function SelfTest() {
  return (
    <main className="max-w-3xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-1">功能测试</h1>
      <p className="text-white/50 text-sm mb-6">正式面试前自测麦克风、摄像头、屏幕共享。此处不接通面试官。</p>
      <div className="flex flex-col gap-4">
        <DeviceCard type="mic" />
        <DeviceCard type="camera" />
        <DeviceCard type="screen" />
      </div>
    </main>
  );
}
