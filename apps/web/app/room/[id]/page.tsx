"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { createRecorder, playAudioBase64 } from "@/lib/voice";
import CodingPanel from "@/app/components/CodingPanel";
import ScreenRead from "@/app/components/ScreenRead";

type Turn = { role: "ai" | "cand"; text: string };

export default function Room() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [q, setQ] = useState<string>("加载中…");
  const [done, setDone] = useState(false);
  const [convo, setConvo] = useState<Turn[]>([]);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [section, setSection] = useState<string | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);
  const recRef = useRef<{ start(): Promise<void>; stop(): Promise<string> } | null>(null);

  const addTurn = (role: "ai" | "cand", text: string) => setConvo((c) => [...c, { role, text }]);

  // on mount: load the first question (text) + speak it (voice start).
  // If /start returned a "preparing" state, poll /next until the context is built.
  useEffect(() => {
    (async () => {
      setQ("AI 面试官正在准备面试…");
      try {
        let d = null;
        for (let i = 0; i < 60; i++) {
          const r = await fetch(`/api/interviews/${id}/next`);
          if (r.status === 404) { setQ("无法加载面试。"); return; }
          d = await r.json();
          if (d.status === "preparing") { await new Promise((res) => setTimeout(res, 2000)); continue; }
          break;
        }
        if (!d || d.status === "preparing") { setQ("面试准备超时，请稍后重试。"); return; }
        setQ(d.question);
        setSection(d.section);
        if (d.question) addTurn("ai", d.question);
        if (d.done) setDone(true);
        // speak the current question
        try {
          const v = await (await fetch("/api/voice/answer", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ interview_id: id, audio_b64: "" }),
          })).json();
          if (v.audio_b64) await playAudioBase64(v.audio_b64);
        } catch {}
      } catch {
        setQ("无法加载面试。");
      }
    })();
  }, [id]);

  async function send() {
    if (!answer.trim() || busy) return;
    const a = answer;
    setAnswer("");
    addTurn("cand", a);
    setBusy(true);
    try {
      const d = await (await fetch(`/api/interviews/${id}/answer`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer: a }),
      })).json();
      if (d.next_question) { addTurn("ai", d.next_question); setQ(d.next_question); }
      else setDone(true);
      setSection(d.section);
    } finally { setBusy(false); }
  }

  async function onPttStart() {
    if (busy || done) return;
    setRecording(true);
    recRef.current = createRecorder();
    await recRef.current.start();
  }

  async function onPttEnd() {
    if (!recRef.current) return;
    setBusy(true);
    const audio = await recRef.current.stop();
    setRecording(false);
    try {
      const d = await (await fetch("/api/voice/answer", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ interview_id: id, audio_b64: audio, format: "wav" }),
      })).json();
      if (d.text) addTurn("cand", d.text);
      if (d.next_question) { addTurn("ai", d.next_question); setQ(d.next_question); }
      else setDone(true);
      setSection(d.section);
      if (d.audio_b64) await playAudioBase64(d.audio_b64);
    } finally { setBusy(false); recRef.current = null; }
  }

  function downloadTranscript() {
    const text = convo.map((t) => `${t.role === "ai" ? "面试官" : "我"}: ${t.text}`).join("\n\n");
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `probedesk-transcript-${id}.txt`; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="max-w-2xl mx-auto p-8 flex flex-col min-h-screen">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold">面试房间</h1>
        <div className="flex gap-2">
          <button onClick={() => setShowTranscript((v) => !v)}
            className="rounded-lg border border-white/10 hover:border-white/30 px-3 py-2 text-sm text-white/70">
            {showTranscript ? "隐藏转写" : "实时转写"}
          </button>
          {convo.length > 0 && (
            <button onClick={downloadTranscript}
              className="rounded-lg border border-white/10 hover:border-white/30 px-3 py-2 text-sm text-white/70">
              下载转写
            </button>
          )}
          {done && (
            <Link href={`/report/${id}`} className="rounded-lg bg-emerald-500 hover:bg-emerald-400 px-4 py-2 text-sm font-semibold">
              查看面试报告
            </Link>
          )}
        </div>
      </div>

      <div className="flex-1 flex flex-col gap-3 overflow-y-auto mb-4">
        {convo.map((t, i) => (
          <div key={i} className={`p-3 rounded-xl max-w-[80%] ${t.role === "ai" ? "bg-white/10 self-start" : "bg-indigo-600 self-end"}`}>
            <span className="block text-[10px] uppercase text-white/40 mb-1">{t.role === "ai" ? "面试官" : "我"}</span>
            {t.text}
          </div>
        ))}
        {done && <div className="text-center text-white/40 text-sm mt-4">面试结束，可查看报告。</div>}
      </div>

      {showTranscript && (
        <div className="mb-4 rounded-xl border border-white/10 p-3 max-h-48 overflow-auto bg-black/20">
          <div className="text-xs text-white/40 mb-2">📝 实时转写（面试官思考流程不展示）</div>
          {convo.length === 0 && <div className="text-white/30 text-sm">还没有对话，开始回答后会实时显示转写。</div>}
          {convo.map((t, i) => (
            <div key={i} className="text-sm mb-1">
              <span className={`${t.role === "ai" ? "text-indigo-300" : "text-white/70"} font-medium`}>
                {t.role === "ai" ? "面试官" : "我"}:
              </span>{" "}
              <span className="text-white/80">{t.text}</span>
            </div>
          ))}
        </div>
      )}

      {section === "coding" && !done && (
        <div className="mb-4">
          <CodingPanel interviewId={id} />
        </div>
      )}

      {!done && (
        <div className="mb-4">
          <ScreenRead onRead={(text) => addTurn("ai", "【看屏幕】" + text.slice(0, 220))} />
        </div>
      )}

      <div className="flex gap-2 items-stretch">
        <textarea
          className="flex-1 rounded-lg border border-white/10 bg-white/5 p-3"
          rows={2}
          placeholder={done ? "面试已结束" : "输入你的回答…"}
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
          disabled={done}
        />
        <button onClick={send} disabled={done || busy || !answer.trim()}
          className="rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-5 font-semibold">发送</button>
        <button
          onPointerDown={onPttStart}
          onPointerUp={onPttEnd}
          onPointerLeave={() => recording && onPttEnd()}
          disabled={done || busy}
          className={`rounded-lg px-5 font-semibold ${recording ? "bg-red-500 text-white" : "bg-white/10 hover:bg-white/20"}`}
        >
          {recording ? "录音中…" : "🎤按住说话"}
        </button>
      </div>
      <p className="mt-2 text-xs text-white/40">按住说话用语音回答；也可在输入框打字。</p>
    </main>
  );
}
