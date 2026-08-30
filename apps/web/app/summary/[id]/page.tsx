"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

/** 本次面试总结文档：汇总全部问答、分项评分、缺失项与改进建议（Markdown）。 */
export default function InterviewSummary() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [md, setMd] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [overall, setOverall] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`/api/interviews/${id}/summary`);
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || d.detail || "加载失败");
        setMd(d.markdown);
        setOverall(d.overall);
      } catch (e: any) {
        setErr(String(e));
      }
    })();
  }, [id]);

  function download() {
    if (!md) return;
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `probedesk-面试总结-${id}.md`; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="max-w-3xl mx-auto p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold">本次面试总结文档</h1>
          <div className="text-xs text-white/40 mt-0.5">
            汇总全部问答、分项评分、缺失项与改进建议
            {overall != null && <span className="text-emerald-300"> · 综合 {overall}/100</span>}
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={download} disabled={!md}
            className="rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-4 py-2 text-sm font-semibold">
            下载 .md
          </button>
          <Link href={`/report/${id}`} className="rounded-lg border border-white/10 px-3 py-2 text-sm text-white/70">返回报告</Link>
        </div>
      </div>

      {err && <div className="rounded-xl border border-white/10 p-4 text-red-400 text-sm">无法加载总结：{err}</div>}
      {!md && !err && <div className="text-white/40 text-sm">正在生成…</div>}
      {md && (
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 text-sm leading-relaxed whitespace-pre-wrap">
          {md}
        </div>
      )}
    </main>
  );
}
