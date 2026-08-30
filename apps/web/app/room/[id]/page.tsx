"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { createFullDuplex } from "@/lib/fullDuplexVoice";
import { createPtt } from "@/lib/pttVoice";
import CodingPanel from "@/app/components/CodingPanel";
import ScreenRead from "@/app/components/ScreenRead";
import InterviewRoom from "@/app/components/InterviewRoom";
import AgentPresence from "@/app/components/AgentPresence";

type Mode = "text" | "ptt" | "duplex";
type Turn = { role: "ai" | "cand"; text: string };
type MicState = "off" | "connecting" | "live" | "error";

const MODE_LABEL: Record<Mode, string> = {
  duplex: "真实对话（打电话式）",
  ptt: "按住说话",
  text: "文字对话",
};

// ---------------------------------------------------------------------------
// Mode-specific voice client (duplex vs PTT). Dispatches on the mode prop.
// ---------------------------------------------------------------------------
interface VoiceEngineHandle {
  start?(): Promise<void>;
  stop?(): void;
  press?(): Promise<boolean>;
  release?(): Promise<void>;
}
function useVoiceEngine(
  mode: Mode,
  interviewId: string,
  handlers: {
    onFinal: (t: string) => void;
    onSpoken: (t: string, section?: string, phase?: string) => void;
    onDone: () => void;
    onStatus: (s: MicState) => void;
  },
) {
  const duplexRef = useRef<VoiceEngineHandle | null>(null);
  const pttRef = useRef<VoiceEngineHandle | null>(null);
  const [pttStatus, setPttStatus] = useState<"idle" | "recording" | "processing" | "playing" | "error">("idle");

  // start the chosen engine when the interview is live
  useEffect(() => {
    if (mode !== "duplex") return;
    let cancelled = false;
    const engine = createFullDuplex(interviewId, {
      onPartial: () => {},
      onFinal: (t) => { if (!cancelled) handlers.onFinal(t); },
      onSpoken: (t, section, phase) => { if (!cancelled) handlers.onSpoken(t, section, phase); },
      onAudio: () => {},
      onDone: () => { if (!cancelled) handlers.onDone(); },
      onStatus: (s) => {
        if (cancelled) return;
        handlers.onStatus(s === "live" ? "live" : s === "starting" ? "connecting" : s === "error" ? "error" : "off");
      },
    });
    duplexRef.current = engine;
    engine.start().catch(() => handlers.onStatus("error"));
    return () => { cancelled = true; try { engine.stop(); } catch {} duplexRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, interviewId]);

  useEffect(() => {
    if (mode !== "ptt") return;
    const engine = createPtt(interviewId, {
      onRecording: () => {},
      onSpoken: (t) => handlers.onSpoken(t),
      onDone: () => handlers.onDone(),
      onError: (m) => console.warn("ptt:", m),
      onStatus: (s) => {
        setPttStatus(s);
        handlers.onStatus(s === "recording" ? "connecting" : s === "error" ? "error" : "off");
      },
    });
    pttRef.current = engine;
    return () => { pttRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, interviewId]);

  const engine: VoiceEngineHandle | null = mode === "duplex" ? duplexRef.current : mode === "ptt" ? pttRef.current : null;

  return {
    engine,
    pttStatus,
    stop: () => { try { duplexRef.current?.stop?.(); } catch {} },
  };
}

export default function Room() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const search = useSearchParams();
  const modeParam = (search.get("mode") as Mode) || "duplex";
  const mode: Mode = ["text", "ptt", "duplex"].includes(modeParam) ? modeParam : "duplex";

  const [q, setQ] = useState<string>("加载中…");
  const [done, setDone] = useState(false);
  const [convo, setConvo] = useState<Turn[]>([]);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [section, setSection] = useState<string | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);
  const [live, setLive] = useState(false); // interview question loaded → enable interaction
  const [mic, setMic] = useState<MicState>("off");
  const [partial, setPartial] = useState("");
  const lastAiRef = useRef<string>("");
  const [pttTouch, setPttTouch] = useState(false);

  const addTurn = (role: "ai" | "cand", text: string) => {
    if (role === "ai") lastAiRef.current = text;
    setConvo((c) => [...c, { role, text }]);
  };

  // voice engine handlers (shared between duplex + ptt)
  const voiceHandlersRef = useRef({
    onFinal: (t: string) => { setPartial(""); const x = t.trim(); if (x) addTurn("cand", x); },
    onSpoken: (t: string, section?: string, phase?: string) => {
      const x = t.trim();
      if (!x || x === lastAiRef.current) return; // dedupe agent's opening line
      addTurn("ai", x);
      setQ(x);
      if (section) setSection(section);
    },
    onDone: () => setDone(true),
    onStatus: (s: MicState) => setMic(s),
  });

  const voice = useVoiceEngine(mode, id, {
    onFinal: (t) => voiceHandlersRef.current.onFinal(t),
    onSpoken: (t, section, phase) => voiceHandlersRef.current.onSpoken(t, section, phase),
    onDone: () => voiceHandlersRef.current.onDone(),
    onStatus: (s) => voiceHandlersRef.current.onStatus(s),
  });

  // on mount: load the next question (text) — the voice engine announces it for
  // voice modes; text mode shows it directly.
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
        if (!d.done) setLive(true);
      } catch {
        setQ("无法加载面试。");
      }
    })();
  }, [id]);

  // stop voice when done
  useEffect(() => {
    if (done) { try { voice.engine?.stop?.(); } catch {} setPartial(""); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done]);

  // ---------- text send ----------
  async function send() {
    if (!answer.trim() || busy) return;
    const a = answer;
    setAnswer("");
    addTurn("cand", a);
    setBusy(true);
    try {
      const d = await fetch(`/api/interviews/${id}/answer`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer: a }),
      }).then((r) => r.json());
      if (d.next_question) { addTurn("ai", d.next_question); setQ(d.next_question); }
      else setDone(true);
      setSection(d.section);
    } finally { setBusy(false); }
  }

  // ---------- PTT press/release ----------
  async function pttDown() {
    setPttTouch(true);
    const ok = await voice.engine?.press?.();
    if (ok === false) setMic("error");
  }
  function pttUp() {
    setPttTouch(false);
    voice.engine?.release?.();
  }

  function downloadTranscript() {
    const text = convo.map((t) => `${t.role === "ai" ? "面试官" : "我"}: ${t.text}`).join("\n\n");
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `probedesk-transcript-${id}.txt`; a.click();
    URL.revokeObjectURL(url);
  }

  const micLabel =
    mode === "text" ? null
      : mode === "ptt"
        ? pttTouch ? "🎙️ 松开发送" : mic === "error" ? "🔇 语音不可用" : "按住说话"
        : mic === "off" ? "🔇 语音未启动" : mic === "connecting" ? "⏳ 连接语音…" : mic === "live" ? "🎙️ 聆听中，直接说话" : "🔇 语音不可用";

  return (
    <main className="max-w-2xl mx-auto p-8 flex flex-col min-h-screen">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold">面试房间</h1>
          <div className="text-xs text-white/40 mt-0.5">方案：{MODE_LABEL[mode]}</div>
        </div>
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

      {(section === "coding" || section === "wrap") && !done && (
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

      {/* 视频房间：全部模式共用（摄像头/麦克风/屏幕共享/看屏），AI 头像经 AgentPresence 加入 */}
      <div className="mb-4">
        <InterviewRoom interviewId={id} />
      </div>

      {!done && partial && (
        <div className="mb-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm">
          <span className="text-white/40">你正在说：</span>
          <span className="text-white/85">{partial}</span>
        </div>
      )}

      {/* Input: mode-aware */}
      {!done && mode === "ptt" && (
        <div className="mb-3 flex items-center gap-2">
          <button
            onPointerDown={pttDown}
            onPointerUp={pttUp}
            onPointerLeave={pttUp}
            onContextMenu={(e) => e.preventDefault()}
            className={`flex-1 select-none rounded-lg border px-5 py-3 font-semibold transition-colors ${
              pttTouch ? "bg-emerald-500/30 border-emerald-400/50 text-emerald-200" : "border-white/10 bg-white/5 hover:bg-white/10 text-white/70"
            }`}
          >
            {pttTouch ? "🎙️ 松开即发送" : "🎙️ 按住说话"}
          </button>
          <div className="text-xs text-white/40 text-center w-40">
            {voice.pttStatus === "processing" ? "AI 思考中…" : "按住说话，松开发送；也可打字"}
          </div>
        </div>
      )}

      <div className="flex gap-2 items-stretch">
        <textarea
          className="flex-1 rounded-lg border border-white/10 bg-white/5 p-3"
          rows={2}
          placeholder={done ? "面试已结束" : mode === "text" ? "输入你的回答(Enter 发送)…" : "打字回答(可选)…"}
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
          disabled={done}
        />
        <button onClick={send} disabled={done || busy || !answer.trim()}
          className="rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-5 font-semibold">发送</button>
        {mode === "duplex" && (
          <div
            title={mic === "error" ? "语音通道不可用：可继续打字回答" : "全双工语音：麦克风常开，直接说话"}
            className={`flex flex-col items-center justify-center gap-1 rounded-lg border px-4 min-w-[9.5rem] ${
              mic === "live" ? "border-emerald-500/40 bg-emerald-500/10" : mic === "error" ? "border-red-500/40 bg-red-500/10" : "border-white/10 bg-white/5"
            }`}
          >
            <span className={`text-sm font-medium ${mic === "live" ? "text-emerald-400" : mic === "error" ? "text-red-400" : "text-white/60"}`}>
              {micLabel}
            </span>
            <span className="text-[10px] text-white/30">{mic === "live" ? "免按键 · 可随时打断" : "打字回答仍可用"}</span>
          </div>
        )}
      </div>
      <p className="mt-2 text-xs text-white/40">
        {mode === "text"
          ? "文字对话：在输入框打字，Enter 发送。"
          : mode === "ptt"
            ? "按住说话：按住按钮说话，松开自动识别并让 AI 应答；打字作为备用。"
            : "真实对话：麦克风常开，直接说话即可，AI 自动应答（说话可打断 AI）；也可在输入框打字回答。"}
      </p>
    </main>
  );
}
