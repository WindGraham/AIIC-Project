"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { Booking } from "@/lib/agent";

const STATUS: Record<string, { label: string; cls: string }> = {
  scheduled: { label: "待开始", cls: "text-yellow-400" },
  available: { label: "可进入", cls: "text-green-400" },
  live: { label: "进行中", cls: "text-indigo-400" },
  completed: { label: "已结束", cls: "text-white/40" },
};

function fmt(secs: number) {
  if (secs <= 0) return "已到开始时间";
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (d > 0) return `${d}天${h}时`;
  if (h > 0) return `${h}时${m}分`;
  if (m > 0) return `${m}分${s}秒`;
  return `${s}秒`;
}

export default function Interviews() {
  const router = useRouter();
  const [items, setItems] = useState<Booking[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());

  const load = useCallback(async () => {
    const r = await fetch("/api/interviews");
    if (r.ok) setItems(await r.json());
    else setErr("加载失败");
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, [load]);

  // recompute seconds relative to client clock
  const enriched = items.map((b) => {
    const t = b.scheduled_at ? new Date(b.scheduled_at).getTime() : 0;
    const secs = t ? Math.floor((t - now) / 1000) : 0;
    const status = secs <= 0 ? "available" : "scheduled";
    return { ...b, seconds_until_start: Math.max(0, secs), status };
  });

  async function enter(b: Booking) {
    // Always /start so the interview context (plan) exists; the room then polls
    // /next which reports "preparing" until the plan is built.
    const r = await fetch(`/api/interviews/${b.id}/start`, { method: "POST" });
    const d = await r.json();
    if (!r.ok) { alert(d.error || "进入失败"); return; }
    router.push(`/room/${d.interview_id}?mode=${encodeURIComponent(b.mode || "duplex")}`);
  }

  return (
    <main className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-1">面试列表</h1>
      <p className="text-white/50 text-sm mb-6">随时可提前进入房间，AI 面试官到点才加入。</p>

      {err && <div className="text-red-400 text-sm mb-4">{err}</div>}
      {enriched.length === 0 && <div className="text-white/40 text-sm">还没有预约，去「预约面试」创建一场。</div>}

      <div className="flex flex-col gap-3">
        {enriched.map((b) => {
          const st = STATUS[String(b.status)] || STATUS.scheduled;
          return (
            <div key={b.id} className="rounded-xl border border-white/10 p-4 flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="font-medium truncate">{b.name || `${b.company} · ${b.position}`}</div>
                <div className="text-xs text-white/40 mt-1">
                  {b.company} · {b.position} · {b.scenario === "retest" ? "保研复试" : "算法/研发"} · 人格：{
                    { peer: "同级", "high-peer": "资深同级", manager: "主管" }[b.persona] || b.persona}
                  {" · "}{{ text: "文字对话", ptt: "按住说话", duplex: "真实对话" }[b.mode] || b.mode}
                </div>
                <div className={`text-sm mt-1 ${st.cls}`}>{st.label} · 距开始 {fmt(b.seconds_until_start || 0)}</div>
                {b.has_coding && <div className="text-xs text-white/40 mt-1">含手撕代码</div>}
              </div>
              <button onClick={() => enter(b)}
                className={`shrink-0 rounded-lg p-2.5 font-semibold ${b.status === "available" ? "bg-indigo-500 hover:bg-indigo-400" : "border border-white/10 hover:border-white/30"}`}>
                {b.status === "available" ? "进入面试" : "提前进入"}
              </button>
            </div>
          );
        })}
      </div>
    </main>
  );
}
