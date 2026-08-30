import Link from "next/link";
import { getReport } from "@/lib/agent";
import ShareBar from "@/app/components/ShareBar";

export const dynamic = "force-dynamic";

export default async function Report({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let r: any;
  try {
    r = await getReport(id);
  } catch {
    return (
      <main className="max-w-2xl mx-auto p-8">
        <h1 className="text-xl font-bold">报告暂不可用</h1>
        <p className="text-white/50 text-sm mt-2">先完成面试，或稍后重试。</p>
        <Link href="/" className="mt-4 inline-block text-indigo-400">返回首页</Link>
      </main>
    );
  }
  return (
    <main className="max-w-2xl mx-auto p-8">
      <h1 className="text-2xl font-bold mb-1">面试报告</h1>
      <p className="text-white/50 text-sm mb-6">综合得分与可执行的改进建议。</p>

      <div className="rounded-2xl border border-white/10 p-6 mb-6">
        <div className="text-5xl font-extrabold">{r.overall}<span className="text-lg text-white/40">/100</span></div>
        <p className="mt-2 text-white/70">{r.summary}</p>
      </div>

      <h2 className="text-lg font-semibold mb-3">分项得分</h2>
      <ul className="grid grid-cols-1 gap-2 mb-6">
        {(r.items || []).map((s: any, i: number) => (
          <li key={i} className="flex items-center justify-between rounded-xl border border-white/10 p-3">
            <span>{s.competency}</span>
            <span className="text-white/60 text-sm">{s.evidence || s.level}</span>
            <span className="font-semibold">{s.score}</span>
          </li>
        ))}
      </ul>

      <h2 className="text-lg font-semibold mb-3">面试官想重点听的（缺失 → 可执行建议）</h2>
      <div className="flex flex-col gap-3">
        {(r.interviewer_os?.missing_slots || []).map((m: any, i: number) => (
          <details key={i} className="rounded-xl border border-white/10 p-4">
            <summary className="font-semibold">{m.slot}</summary>
            <p className="text-white/70 text-sm mt-2">{m.evidence}</p>
            <p className="text-white/50 text-xs mt-1">为什么面试官在意：{m.why_it_matters}</p>
            <div className="mt-2 text-sm">
              <span className="text-white/40">我想听到：</span>
              <ul className="list-disc ml-5">
                {(m.what_i_want_to_hear || []).map((w: string, j: number) => (
                  <li key={j}>{w}</li>
                ))}
              </ul>
            </div>
            <div className="mt-3 text-emerald-300 text-sm">→ {m.one_line_advice}</div>
          </details>
        ))}
      </div>

      <p className="mt-6 text-xs text-white/40">
        面试官思考流程（interviewer_os）仅在报告呈现，全程面试中不实时展示。
      </p>
      <ShareBar interviewId={id} />
      <Link href="/" className="mt-3 inline-block text-indigo-400">返回首页</Link>
    </main>
  );
}
