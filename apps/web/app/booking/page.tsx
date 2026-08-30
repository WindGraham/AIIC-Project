"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { Resume, JD } from "@/lib/agent";

const PERSONAS = [
  { value: "peer", label: "同级同事", desc: "平等友好，重在技术切磋、引导与鼓励" },
  { value: "high-peer", label: "资深同级", desc: "专业平等，重方法、复杂度与工程取舍" },
  { value: "manager", label: "主管", desc: "正式有压迫感，重全局判断与 owner-ship" },
];

const MODES = [
  { value: "duplex", label: "真实对话", desc: "麦克风常开、边说边答，AI 实时语音 (像打电话)" },
  { value: "ptt", label: "按住说话", desc: "按住麦克风说完再松手，更稳定、不易误触发" },
  { value: "text", label: "文字对话", desc: "打字一问一答，最稳定，适合快速练习" },
];

export default function Booking() {
  const router = useRouter();
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [jds, setJds] = useState<JD[]>([]);
  const [f, setF] = useState({
    name: "",
    resume_id: "",
    resume_text: "",
    jd_id: "",
    company: "",
    position: "",
    jd_text: "",
    scheduled_at: "",
    notes: "",
    has_coding: true,
    scenario: "algorithm",
    persona: "high-peer",
    mode: "duplex",
    asap: false,
  });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [r, j] = await Promise.all([fetch("/api/resumes"), fetch("/api/jds")]);
    if (r.ok) setResumes(await r.json());
    if (j.ok) setJds(await j.json());
  }, []);

  useEffect(() => {
    load().then(() => {
      // 每人预选"默认"简历与"默认"JD。
      const defResume = resumes.find((x) => x.is_default);
      setF((s) => ({ ...s, resume_id: defResume?.id || "", resume_text: defResume?.resume_text || s.resume_text }));
      const defJd = jds.find((x) => x.is_default) || jds[0];
      if (defJd) setF((s) => ({ ...s, jd_id: defJd.id, company: defJd.company, position: defJd.position, jd_text: defJd.jd_text }));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load]);

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setF((s) => ({ ...s, [k]: e.target.value }));

  function pickResume(id: string) {
    const r = resumes.find((x) => x.id === id);
    setF((s) => ({ ...s, resume_id: id, resume_text: r?.resume_text || s.resume_text }));
  }

  function pickJd(id: string) {
    const j = jds.find((x) => x.id === id);
    setF((s) => ({ ...s, jd_id: id, company: j?.company || "", position: j?.position || "", jd_text: j?.jd_text || "" }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (!f.resume_text.trim()) { setErr("请选择或粘贴一份简历"); return; }
    // 预约制：时间需至少在当前后 30 分钟；尽快开始则不受限。
    if (!f.asap) {
      if (!f.scheduled_at) { setErr("请选择预约时间，或勾选「尽快开始」"); return; }
      const d = new Date(f.scheduled_at);
      if (d.getTime() && d.getTime() < Date.now() - 60000) { setErr("预约时间不能早于当前时间"); return; }
    }
    setBusy(true);
    try {
      const payload = {
        ...f,
        scheduled_at: f.asap ? new Date().toISOString() : (f.scheduled_at ? new Date(f.scheduled_at).toISOString() : undefined),
        company: f.company || "目标公司",
        position: f.position || "后端开发工程师",
      };
      const r = await fetch("/api/interviews/book", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "预约失败");
      router.push("/interviews");
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="max-w-2xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-1">预约模拟面试</h1>
      <p className="text-white/50 text-sm mb-6">选择简历、公司/岗位/JD、时间与面试官人格。可提前进入房间，AI 面试官到点才加入。</p>

      <form onSubmit={submit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          面试名称
          <input className="rounded-lg border border-white/10 bg-white/5 p-2" value={f.name}
            onChange={set("name")} placeholder="如：字节后端模拟面" />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          简历
          <select className="rounded-lg border border-white/10 bg-white/5 p-2" value={f.resume_id}
            onChange={(e) => pickResume(e.target.value)}>
            <option value="">手动填写 / 使用下面的文本</option>
            {resumes.map((r) => <option key={r.id} value={r.id}>{r.name}（{r.skills.length} 技能）</option>)}
          </select>
        </label>
        {f.resume_id === "" && (
          <label className="flex flex-col gap-1 text-sm">
            简历文本（粘贴）
            <textarea className="rounded-lg border border-white/10 bg-white/5 p-3" rows={5}
              value={f.resume_text} onChange={set("resume_text")} />
          </label>
        )}

        <label className="flex flex-col gap-1 text-sm">
          岗位 JD（可复用 · 在「管理简历」页维护）
          <select className="rounded-lg border border-white/10 bg-white/5 p-2" value={f.jd_id}
            onChange={(e) => pickJd(e.target.value)}>
            <option value="">手动填写 公司/岗位/JD</option>
            {jds.map((j) => <option key={j.id} value={j.id}>{j.name}（{j.company} · {j.position}）</option>)}
          </select>
          <span className="text-xs text-white/40">选择后自动带入公司 / 岗位 / JD 文本，可再微调。</span>
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
          岗位 JD（文本）
          <textarea className="rounded-lg border border-white/10 bg-white/5 p-3" rows={4}
            value={f.jd_text} onChange={set("jd_text")} />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          预约时间
          <input type="datetime-local" className="rounded-lg border border-white/10 bg-white/5 p-2 disabled:opacity-40"
            value={f.scheduled_at} onChange={set("scheduled_at")} disabled={f.asap} />
          <span className="text-xs text-white/40">
            {f.asap ? "已选「尽快开始」，后台准备完毕即可答题。" : "预约制：最早为当前时间之后 30 分钟；时间未到 agent 不会回复。"}
          </span>
        </label>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.asap} onChange={(e) => setF((s) => ({ ...s, asap: e.target.checked }))} />
          ⚡ 尽快开始（后台准备完毕即可进入答题，不受预约时间限制）
        </label>

        <div className="grid grid-cols-2 gap-4">
          <label className="flex flex-col gap-1 text-sm">
            面试官人格
            <select className="rounded-lg border border-white/10 bg-white/5 p-2" value={f.persona}
              onChange={set("persona")}>
              {PERSONAS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
            <span className="text-xs text-white/40">{PERSONAS.find((p) => p.value === f.persona)?.desc}</span>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            场景
            <select className="rounded-lg border border-white/10 bg-white/5 p-2" value={f.scenario}
              onChange={set("scenario")}>
              <option value="algorithm">算法 / 研发（常规）</option>
              <option value="retest">保研复试</option>
            </select>
          </label>
        </div>

        <div className="flex flex-col gap-1 text-sm">
          <span>面试方案</span>
          <div className="grid grid-cols-3 gap-2">
            {MODES.map((m) => (
              <button type="button" key={m.value} onClick={() => setF((s) => ({ ...s, mode: m.value }))}
                className={`rounded-lg border p-3 text-left transition-colors ${
                  f.mode === m.value ? "border-indigo-400 bg-indigo-500/15" : "border-white/10 hover:border-white/30"
                }`}>
                <div className="font-medium text-sm">{m.label}</div>
                <div className="text-xs text-white/40 mt-1">{m.desc}</div>
              </button>
            ))}
          </div>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.has_coding} onChange={(e) => setF((s) => ({ ...s, has_coding: e.target.checked }))} />
          包含手撕代码环节
        </label>

        <label className="flex flex-col gap-1 text-sm">
          补充信息（可选）
          <textarea className="rounded-lg border border-white/10 bg-white/5 p-3" rows={2}
            value={f.notes} onChange={set("notes")} />
        </label>

        {err && <div className="text-red-400 text-sm">{err}</div>}
        <button disabled={busy} className="rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 p-3 font-semibold">
          {busy ? "提交中…" : "预约面试"}
        </button>
      </form>
    </main>
  );
}
