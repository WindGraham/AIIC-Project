"use client";

import { useState } from "react";

/**
 * 功能测试 D：LLM 接口测试。发一段文本给 LLM，看是否返回（展示模型回答 + 耗时）。
 */
export default function LlmPing() {
  const [text, setText] = useState("你好，请用一句话介绍一下你自己。");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<{ reply: string; model: string; ms: number } | null>(null);

  async function run() {
    if (!text.trim() || busy) return;
    setBusy(true);
    setErr(null);
    const t0 = performance.now();
    try {
      const r = await fetch("/api/llm/ping", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || d.detail || `接口错误(${r.status})`);
      setResult({ reply: d.reply || "", model: d.model || "", ms: Math.round(performance.now() - t0) });
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl border border-white/10 p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm text-white/50">D. LLM 接口</div>
        <div className="text-xs text-white/40">发文本 → 看是否返回</div>
      </div>

      <div className="flex gap-2 mb-3">
        <input
          className="flex-1 rounded-lg border border-white/10 bg-white/5 p-2 text-sm"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="输入要发给 LLM 的文本"
        />
        <button onClick={run} disabled={busy}
          className="rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-4 py-2 text-sm font-semibold">
          {busy ? "调用中…" : "🤖 发送"}
        </button>
      </div>

      {err && <div className="text-red-400 text-xs mb-2">{err}</div>}
      {result && (
        <div className="rounded-lg border border-white/10 bg-white/5 p-3 text-sm">
          <div className="text-xs text-white/40 mb-1">
            模型：{result.model} · 耗时 {result.ms}ms
          </div>
          <div className="text-white/85 whitespace-pre-wrap">{result.reply}</div>
        </div>
      )}
      {!result && !err && <div className="text-white/30 text-xs">点击「发送」，验证 LLM 文本接口是否有返回。</div>}
    </div>
  );
}
