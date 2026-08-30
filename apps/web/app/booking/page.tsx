"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Booking() {
  const router = useRouter();
  const [f, setF] = useState({
    resume_text: "",
    jd_text: "",
    company: "",
    position: "",
    seniority: "mid",
    lang: "zh",
  });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setF((s) => ({ ...s, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const r = await fetch("/api/interviews/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(f),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "准备面试失败");
      router.push(`/room/${d.interview_id}`);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="max-w-xl mx-auto p-8">
      <h1 className="text-2xl font-bold mb-1">预约模拟面试</h1>
      <p className="text-white/50 text-sm mb-6">填入简历、岗位描述与目标公司，AI 面试官会立即生成一场专属面试。</p>

      <form onSubmit={submit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          简历（文本粘贴）
          <textarea className="rounded-lg border border-white/10 bg-white/5 p-3" rows={5}
            value={f.resume_text} onChange={set("resume_text")} required />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          岗位 JD（文本）
          <textarea className="rounded-lg border border-white/10 bg-white/5 p-3" rows={4}
            value={f.jd_text} onChange={set("jd_text")} required />
        </label>
        <div className="grid grid-cols-2 gap-4">
          <label className="flex flex-col gap-1 text-sm">
            公司
            <input className="rounded-lg border border-white/10 bg-white/5 p-2" value={f.company} onChange={set("company")} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            岗位
            <input className="rounded-lg border border-white/10 bg-white/5 p-2" value={f.position} onChange={set("position")} />
          </label>
        </div>
        <label className="flex flex-col gap-1 text-sm">
          职级
          <select className="rounded-lg border border-white/10 bg-white/5 p-2" value={f.seniority} onChange={set("seniority")}>
            <option value="junior">junior</option><option value="mid">mid</option>
            <option value="senior">senior</option><option value="staff">staff</option>
          </select>
        </label>

        {err && <div className="text-red-400 text-sm">{err}</div>}
        <button disabled={busy} className="rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 p-3 font-semibold">
          {busy ? "生成面试中…" : "开始面试"}
        </button>
      </form>

      <p className="mt-6 text-xs text-white/40">
        支持简历、公司、岗位、JD、时间、补充信息、是否含手撕代码——此处先以核心三要素跑通垂直切片。
      </p>
    </main>
  );
}
