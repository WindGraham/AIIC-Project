"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

type Turn = { role: "ai" | "cand"; text: string };

export default function Room() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [q, setQ] = useState<string>("加载中…");
  const [done, setDone] = useState(false);
  const [convo, setConvo] = useState<Turn[]>([]);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const d = await (await fetch(`/api/interviews/${id}/next`)).json();
        setQ(d.question);
        if (d.done) setDone(true);
        setConvo((c) => (d.question ? [...c, { role: "ai", text: d.question }] : c));
      } catch {
        setQ("无法加载面试。");
      }
    })();
  }, [id]);

  async function send() {
    if (!answer.trim() || busy) return;
    const a = answer;
    setAnswer("");
    setConvo((c) => [...c, { role: "cand", text: a }]);
    setBusy(true);
    try {
      const d = await (await fetch(`/api/interviews/${id}/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer: a }),
      })).json();
      if (d.next_question) {
        setConvo((c) => [...c, { role: "ai", text: d.next_question }]);
        setQ(d.next_question);
      } else {
        setDone(true);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="max-w-2xl mx-auto p-8 flex flex-col min-h-screen">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold">面试房间</h1>
        {done && (
          <Link href={`/report/${id}`} className="rounded-lg bg-emerald-500 hover:bg-emerald-400 px-4 py-2 text-sm font-semibold">
            查看面试报告
          </Link>
        )}
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

      <div className="flex gap-2">
        <textarea
          className="flex-1 rounded-lg border border-white/10 bg-white/5 p-3"
          rows={2}
          placeholder={done ? "面试已结束" : "输入你的回答…"}
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
          disabled={done}
        />
        <button onClick={send} disabled={done || busy || !answer.trim()}
          className="rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-5 font-semibold">
          发送
        </button>
      </div>
    </main>
  );
}
