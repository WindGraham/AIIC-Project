"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { createFullDuplex, type FullDuplexHandle } from "@/lib/fullDuplexVoice";
import CodingPanel from "@/app/components/CodingPanel";
import ScreenRead from "@/app/components/ScreenRead";
import InterviewRoom from "@/app/components/InterviewRoom";
import AgentPresence from "@/app/components/AgentPresence";

type Turn = { role: "ai" | "cand"; text: string };
type MicState = "off" | "connecting" | "live" | "error";

const MIC_LABEL: Record<MicState, string> = {
  off: "🔇 语音未启动",
  connecting: "⏳ 连接语音…",
  live: "🎙️ 聆听中，直接说话",
  error: "🔇 语音不可用",
};

export default function Room() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [q, setQ] = useState<string>("加载中…");
  const [done, setDone] = useState(false);
  const [convo, setConvo] = useState<Turn[]>([]);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [section, setSection] = useState<string | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);
  // full-duplex voice state
  const [live, setLive] = useState(false); // interview question loaded → start voice
  const [mic, setMic] = useState<MicState>("off");
  const [partial, setPartial] = useState("");
  const fdRef = useRef<FullDuplexHandle | null>(null);
  const lastAiRef = useRef<string>("");

  const addTurn = (role: "ai" | "cand", text: string) => {
    if (role === "ai") lastAiRef.current = text;
    setConvo((c) => [...c, { role, text }]);
  };

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
        // The AI's voice is driven by the FULL-DUPLEX channel (createFullDuplex);
        // the agent announces the first question there. We do NOT speak here a
        // second time (avoids triple audio) — only set the interview live.
        if (!d.done) setLive(true); // interview is live → open the continuous voice channel
      } catch {
        setQ("无法加载面试。");
      }
    })();
  }, [id]);

  // full-duplex voice: continuous listen + agent speak-back (phone-call style)
  useEffect(() => {
    if (!live || done) return;
    let cancelled = false;
    fdRef.current = createFullDuplex(id, {
      onPartial: (t) => { if (!cancelled) setPartial(t); },
      onFinal: (t) => {
        if (cancelled) return;
        setPartial("");
        const txt = t.trim();
        if (txt) addTurn("cand", txt);
      },
      onSpoken: (t) => {
        if (cancelled) return;
        const txt = t.trim();
        if (!txt || txt === lastAiRef.current) return; // dedupe agent's first-line announce
        addTurn("ai", txt);
        setQ(txt);
      },
      onAudio: () => { /* engine queues chunks; gapless playback is internal */ },
      onDone: () => { if (!cancelled) setDone(true); },
      onStatus: (s) => {
        if (cancelled) return;
        setMic(s === "live" ? "live" : s === "starting" ? "connecting" : s === "error" ? "error" : "off");
      },
    });
    fdRef.current.start().catch(() => { /* mic denied / agent down → text path still works */ });
    return () => {
      cancelled = true;
      try { fdRef.current?.stop(); } catch {}
      fdRef.current = null;
    };
  }, [id, live]);

  // stop the voice channel once the interview is over
  useEffect(() => {
    if (done) {
      try { fdRef.current?.stop(); } catch {}
      setPartial("");
    }
  }, [done]);

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

      <div className="mb-3">
        <AgentPresence
          interviewId={id}
          active={!done && q !== "加载中…" && q !== "AI 面试官正在准备面试…"}
          onRead={(text) => addTurn("ai", "【看屏幕】" + text.slice(0, 220))}
        />
      </div>

      {!done && (
        <div className="mb-4">
          <ScreenRead onRead={(text) => addTurn("ai", "【看屏幕】" + text.slice(0, 220))} />
        </div>
      )}

      {!done && (
        <div className="mb-4">
          <InterviewRoom interviewId={id} />
        </div>
      )}

      {!done && partial && (
        <div className="mb-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm">
          <span className="text-white/40">你正在说：</span>
          <span className="text-white/85">{partial}</span>
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
        <div
          title={mic === "error" ? "语音通道不可用：可继续打字回答" : "全双工语音：麦克风常开，直接说话"}
          className={`flex flex-col items-center justify-center gap-1 rounded-lg border px-4 min-w-[9.5rem] ${
            mic === "live" ? "border-emerald-500/40 bg-emerald-500/10" : mic === "error" ? "border-red-500/40 bg-red-500/10" : "border-white/10 bg-white/5"
          }`}
        >
          <span className={`text-sm font-medium ${mic === "live" ? "text-emerald-400" : mic === "error" ? "text-red-400" : "text-white/60"}`}>
            {MIC_LABEL[mic]}
          </span>
          <span className="text-[10px] text-white/30">{mic === "live" ? "免按键 · 可随时打断" : "打字回答仍可用"}</span>
        </div>
      </div>
      <p className="mt-2 text-xs text-white/40">全双工语音：麦克风常开，直接说话即可，AI 自动应答（说话可打断 AI）；也可在输入框打字回答。</p>
    </main>
  );
}
