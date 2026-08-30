"use client";

import { useEffect, useRef, useState } from "react";
import {
  joinAsAgent,
  leaveAgent,
  setScreenReadHandler,
  type ScreenReadHandler,
} from "@/lib/agentPresence";

/** AgentPresence — the "AI 面试官" participant in the LiveKit room.
 *
 * Joins with the agent JWT (minted by /agent-join), then (implementation in
 * lib/agentPresence.ts):
 *  - publishes an "AI 面试官" video tile            → VIDEO-visible in the room
 *  - publishes the TTS voice bus as a mic track      → AUDIBLE in room + recording
 *  - subscribes to the candidate's screen-share track, downsamples frames and
 *    POSTs them to /api/vision/analyze (Gemini)      → agent SEES the screen
 *
 * Runs in the candidate's browser as the interviewer's presence; the question /
 * answer loop still goes through the existing AI API (voice/answer).
 */
export default function AgentPresence({
  interviewId,
  active,
  onRead,
}: {
  interviewId: string;
  active?: boolean;
  onRead?: ScreenReadHandler;
}) {
  const [status, setStatus] = useState<"idle" | "joining" | "live" | "error">("idle");
  const [err, setErr] = useState<string | null>(null);
  const onReadRef = useRef(onRead);
  onReadRef.current = onRead;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setScreenReadHandler((text) => onReadRef.current?.(text));
    setStatus("joining");
    setErr(null);
    (async () => {
      const ok = await joinAsAgent(interviewId);
      if (!cancelled) setStatus(ok ? "live" : "error");
    })();
    return () => {
      cancelled = true;
      setScreenReadHandler(null);
      leaveAgent();
    };
  }, [interviewId, active]);

  return (
    <div
      className={`flex items-center gap-2 text-sm ${
        status === "live" ? "text-emerald-300" : "text-white/40"
      }`}
    >
      <span className="text-lg">🤖</span>
      {status === "live"
        ? "AI 面试官在房间里（视频 + 语音 + 看屏）"
        : status === "joining"
          ? "AI 面试官入场中…"
          : status === "error"
            ? "AI 面试官入场失败"
            : "AI 面试官未入场"}
      {err && <span className="text-red-400 text-xs">{err}</span>}
    </div>
  );
}
