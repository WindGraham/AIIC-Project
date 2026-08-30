"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

type HistoryItem = {
  id: string;
  interview_id: string;
  position: string;
  company: string;
  persona: string;
  overall: number;
  items: { competency: string; score: number }[];
  missing: { slot: string; why_it_matters: string; one_line_advice: string }[];
  created_at: string;
};

function pct(v: number) { return Math.round(v * 20); }
const LEVELS: Record<string, string> = { peer: "同级", "high-peer": "资深同级", manager: "主管" };

export default function History() {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    const r = await fetch("/api/interviews/history");
    if (r.ok) setItems(await r.json());
    else setErr("加载失败");
  }, []);
  useEffect(() => { load(); }, [load]);

  // newest -> oldest for the trend
  const newest = items[0] || null;
  const overallTrend = [0, ...items].slice(0, 12); // oldest first-ish for chart; we reverse
  const trend = [...items].reverse().slice(-10);

  // aggregate competency averages across all interviews
  const comp = new Map<string, { sum: number; n: number }>();
  for (const it of items) for (const c of it.items) {
    const cur = comp.get(c.competency) || { sum: 0, n: 0 };
    cur.sum += c.score; cur.n += 1; comp.set(c.competency, cur);
  }
  const comps = [...comp.entries()].map(([n, v]) => ({ name: n, avg: v.sum / v.n })).sort((a, b) => a.avg - b.avg);

  return (
    <main className="max-w-4xl mx-auto p-6">
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-2xl font-bold">学习曲线 · 跨场记忆</h1>
        <Link href="/booking" className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-semibold">预约下一场</Link>
      </div>
      <p className="text-white/50 text-sm mb-6">跨多场记录你的进步曲线与薄弱项，下一场面试官会针对短板出题。</p>
      {err && <div className="text-red-400 text-sm mb-4">{err}</div>}

      {items.length === 0 && <div className="text-white/40 text-sm">还没有面试记录。先完成一场面试，这里会展示你的进步曲线。</div>}

      {items.length > 0 && (
        <>
          {/* Trend chart */}
          <section className="rounded-xl border border-white/10 p-5 mb-6">
            <div className="font-semibold mb-3">综合得分趋势 ({items.length} 场)</div>
            <div className="flex items-end gap-2 h-32">
              {trend.map((t) => (
                <div key={t.id} className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-[10px] text-white/40">{Math.round(t.overall)}</span>
                  <div className="w-full rounded-t bg-indigo-500/70" style={{ height: `${Math.max(4, t.overall)}%` }} />
                  <span className="text-[10px] text-white/40 truncate w-full text-center">{t.position || t.company}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Weak competencies */}
          <section className="rounded-xl border border-white/10 p-5 mb-6">
            <div className="font-semibold mb-3">薄弱项（按平均分排序）</div>
            {comps.length === 0 && <div className="text-white/40 text-sm">暂无评分项。</div>}
            <div className="flex flex-col gap-2">
              {comps.slice(0, 6).map((c) => (
                <div key={c.name} className="flex items-center gap-3">
                  <span className="w-40 text-sm text-white/70 truncate">{c.name}</span>
                  <div className="flex-1 h-2 rounded-full bg-white/10">
                    <div className="h-2 rounded-full bg-yellow-400/70" style={{ width: `${pct(c.avg)}%` }} />
                  </div>
                  <span className="text-sm text-white/50 w-10 text-right">{c.avg.toFixed(1)}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Most recent missing slots -> re-practice */}
          {newest && newest.missing?.length > 0 && (
            <section className="rounded-xl border border-white/10 p-5 mb-6">
              <div className="font-semibold mb-2">最近一场 · 建议重练</div>
              <div className="flex flex-col gap-2">
                {newest.missing.slice(0, 4).map((m, i) => (
                  <div key={i} className="rounded-lg bg-white/5 p-3 text-sm">
                    <div className="text-white">{m.slot}</div>
                    <div className="text-white/50 text-xs mt-1">{m.why_it_matters}</div>
                    <div className="text-indigo-300 text-xs mt-1">建议：{m.one_line_advice}</div>
                  </div>
                ))}
              </div>
              <div className="mt-3 text-xs text-white/40">
                面试官人格：{LEVELS[newest.persona] || newest.persona} · {newest.company} · {newest.position}
              </div>
            </section>
          )}
        </>
      )}
    </main>
  );
}
