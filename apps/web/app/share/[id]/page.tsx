import Link from "next/link";
import { getReport, getTranscript } from "@/lib/agent";

export const dynamic = "force-dynamic";

export default async function Share({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let t: any, r: any;
  try {
    t = await getTranscript(id);
    r = await getReport(id);
  } catch {
    return (
      <main className="max-w-2xl mx-auto p-8">
        <h1 className="text-xl font-bold">分享已失效</h1>
        <p className="text-white/50 text-sm mt-2">该面试回顾不存在或已完成清理。</p>
        <Link href="/" className="inline-block mt-4 text-indigo-400">返回首页</Link>
      </main>
    );
  }

  return (
    <main className="max-w-2xl mx-auto p-8">
      <h1 className="text-2xl font-bold">面试回顾分享</h1>
      <p className="text-white/50 text-sm mt-1 mb-4">
        {t.meta?.company || ""} · {t.meta?.position || ""}（转写与报告为公开只读，供他人帮忙评价）
      </p>

      <div className="rounded-2xl border border-white/10 p-6 mb-6">
        <div className="text-5xl font-extrabold">{r.overall}<span className="text-lg text-white/40">/100</span></div>
        <p className="mt-2 text-white/70">{r.summary}</p>
      </div>

      <h2 className="text-lg font-semibold mb-3">面试转写</h2>
      <div className="flex flex-col gap-3 mb-8">
        {(t.items || []).map((it: any, i: number) => (
          <div key={i} className="rounded-xl border border-white/10 p-3">
            <div className="text-xs text-white/40 mb-1">{it.section} · Q</div>
            <p className="text-white/90 text-sm">{it.question}</p>
            <div className="text-xs text-white/40 mt-2 mb-1">A</div>
            <p className="text-white/75 text-sm whitespace-pre-wrap">{it.answer}</p>
          </div>
        ))}
        {!(t.items || []).length && <p className="text-white/40 text-sm">暂无转写（未作答）。</p>}
      </div>

      <h2 className="text-lg font-semibold mb-3">面试官想重点听的（缺失 → 建议）</h2>
      <div className="flex flex-col gap-3">
        {(r.interviewer_os?.missing_slots || []).map((m: any, i: number) => (
          <div key={i} className="rounded-xl border border-white/10 p-4">
            <div className="font-semibold">{m.slot}</div>
            <ul className="list-disc ml-5 mt-1 text-sm">
              {(m.what_i_want_to_hear || []).map((w: string, j: number) => <li key={j}>{w}</li>)}
            </ul>
            <div className="mt-2 text-emerald-300 text-sm">→ {m.one_line_advice}</div>
          </div>
        ))}
      </div>

      <p className="mt-6 text-xs text-white/40">面试官思考流程仅在报告/复盘呈现，全程面试中不实时展示。</p>
      <Link href="/" className="inline-block mt-3 text-indigo-400">返回首页</Link>
    </main>
  );
}
