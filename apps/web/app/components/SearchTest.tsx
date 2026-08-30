"use client";

import { useState } from "react";

/**
 * 功能测试 C：搜索能力测试。给一个岗位，去搜索引擎 + 社交平台(小红书/知乎/牛客)
 * 做信息检索，展示返回的结果（标题/来源/摘要/链接）。
 */
export default function SearchTest() {
  const [query, setQuery] = useState("字节跳动 后端开发工程师 面经");
  const [limit, setLimit] = useState(8);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<{ sources: any[]; query: string } | null>(null);

  async function run() {
    if (!query.trim() || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/search", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, limit }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || `搜索失败(${r.status})`);
      setResult({ sources: d.sources || [], query: d.query || query });
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl border border-white/10 p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm text-white/50">C. 搜索能力</div>
        <div className="text-xs text-white/40">岗位 → 搜索引擎 + 社交平台</div>
      </div>

      <div className="flex gap-2 mb-3">
        <input
          className="flex-1 rounded-lg border border-white/10 bg-white/5 p-2 text-sm"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="输入要查询的岗位/关键词"
        />
        <select className="rounded-lg border border-white/10 bg-white/5 px-2 text-sm" value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}>
          {[3, 6, 10].map((n) => <option key={n} value={n}>{n} 条</option>)}
        </select>
        <button onClick={run} disabled={busy}
          className="rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-4 py-2 text-sm font-semibold">
          {busy ? "搜索中…" : "🔍 搜索"}
        </button>
      </div>

      {err && <div className="text-red-400 text-xs mb-2">{err}</div>}
      {result && (
        <div className="text-xs text-white/40 mb-1">
          共 {result.sources.length} 条结果 · 关键词：{result.query}
        </div>
      )}
      <div className="max-h-60 overflow-auto rounded-lg border border-white/10 bg-black/20 p-3 flex flex-col gap-2">
        {!result && <div className="text-white/30 text-xs">输入岗位关键词，点搜索查看解析后的信息结果。</div>}
        {result?.sources.length === 0 && <div className="text-white/30 text-xs">没有搜到结果（可能平台未配置或超时）。</div>}
        {result?.sources.map((s, i) => (
          <div key={i} className="text-xs">
            <a href={s.url} target="_blank" rel="noreferrer" className="text-indigo-300 hover:underline font-medium">
              [{s.provider}] {s.title}
            </a>
            <div className="text-white/70 mt-0.5">{s.snippet}</div>
            <div className="text-white/30 text-[10px] break-all">{s.url}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
