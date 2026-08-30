"use client";

import { useEffect, useState } from "react";

export default function CodingPanel({ interviewId }: { interviewId: string }) {
  const [problem, setProblem] = useState<any>(null);
  const [questionText, setQuestionText] = useState<string>("");
  const [code, setCode] = useState("");
  const [verdict, setVerdict] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const d = await (await fetch(`/api/interviews/${interviewId}/problem`)).json();
        setProblem(d.problem);
        setQuestionText(d.question_text || "");
      } catch {
        setErr("无法加载题目");
      }
    })();
  }, [interviewId]);

  async function submit() {
    if (busy) return;
    setBusy(true);
    setVerdict(null);
    try {
      const d = await (await fetch("/api/coding/judge", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ interview_id: interviewId, code, language: "python" }),
      })).json();
      setVerdict(d);
    } catch {
      setErr("提交失败");
    } finally {
      setBusy(false);
    }
  }

  if (err) return <div className="text-red-400 text-sm">{err}</div>;

  return (
    <div className="rounded-2xl border border-white/10 p-4">
      <div className="text-sm text-white/50 mb-2">✍️ 手撕代码环节</div>
      {problem ? (
        <div className="mb-3">
          <div className="font-semibold">{problem.title} <span className="text-white/40 text-xs">({problem.difficulty})</span></div>
          <p className="text-sm text-white/70 whitespace-pre-wrap mt-1">{problem.description}</p>
          {problem.examples?.slice(0, 2).map((e: any, i: number) => (
            <pre key={i} className="bg-white/5 rounded p-2 text-xs mt-1 overflow-x-auto">输入: {e.input} → 输出: {e.output}</pre>
          ))}
        </div>
      ) : (
        questionText && <p className="text-sm text-white/70">{questionText}</p>
      )}

      <textarea
        className="w-full h-40 rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-sm"
        spellCheck={false}
        placeholder="在这里写你的代码…"
        value={code}
        onChange={(e) => setCode(e.target.value)}
      />
      <button onClick={submit} disabled={busy}
        className="mt-2 rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-4 py-2 text-sm font-semibold">
        {busy ? "面试官判断中…" : "提交给面试官"}
      </button>

      {verdict && (
        <div className="mt-3 rounded-xl border border-white/10 p-3 text-sm">
          <div className="font-semibold mb-1">
            面试官判：<span className={verdict.status === "correct" ? "text-emerald-400" : "text-amber-400"}>{verdict.status}</span>
            {typeof verdict.score === "number" && <span className="text-white/40"> · {verdict.score}/5</span>}
          </div>
          {verdict.speech && <p className="text-white/80">{verdict.speech}</p>}
          {verdict.next_hint && <p className="text-amber-300 text-xs mt-1">提示：{verdict.next_hint}</p>}
        </div>
      )}
    </div>
  );
}
