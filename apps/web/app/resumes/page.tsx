"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Resume } from "@/lib/agent";

export default function Resumes() {
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [skills, setSkills] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [parsing, setParsing] = useState(false);

  const load = useCallback(async () => {
    const r = await fetch("/api/resumes");
    if (r.ok) setResumes(await r.json());
  }, []);

  useEffect(() => { load(); }, [load]);

  const sel = resumes.find((r) => r.id === selected) || null;

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setErr(null);
    setParsing(true);
    try {
      const buf = await file.arrayBuffer();
      const bytes = new Uint8Array(buf);
      let bin = "";
      const chunk = 0x8000;
      for (let i = 0; i < bytes.length; i += chunk) {
        bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
      }
      const data = btoa(bin);
      const r = await fetch("/api/resumes/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data, filename: file.name }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "解码失败");
      if (!d.text?.trim()) throw new Error("未从文件中提取到文本");
      setText(d.text);
      if (!name) setName(file.name.replace(/\.[^.]+$/, "") || "我的简历");
      setSkills((s) => s || "");
    } catch (ex) {
      setErr("文件解码失败：" + String(ex));
    } finally {
      setParsing(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function create() {
    setErr(null);
    if (!text.trim()) { setErr("请先粘贴简历内容"); return; }
    setBusy(true);
    try {
      const r = await fetch("/api/resumes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name || "我的简历",
          resume_text: text,
          skills: skills.split(/[,，;；\s]+/).map((s) => s.trim()).filter(Boolean),
          is_default: resumes.length === 0,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "保存失败");
      setText(""); setName(""); setSkills("");
      setSelected(d.id);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function del(id: string) {
    await fetch(`/api/resumes/${id}`, { method: "DELETE" });
    setSelected(null);
    await load();
  }

  async function makeDefault(id: string) {
    await fetch(`/api/resumes/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_default: true }),
    });
    await load();
  }

  return (
    <main className="max-w-6xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-1">管理简历</h1>
      <p className="text-white/50 text-sm mb-6">多份简历，设置默认，粘贴文本即可抽取技能画像。</p>

      <div className="grid md:grid-cols-2 gap-6">
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm">
            列表
          </label>
          <div className="flex flex-col gap-2">
            {resumes.length === 0 && <div className="text-white/40 text-sm">还没有简历，先在右侧新建一份。</div>}
            {resumes.map((r) => (
              <div key={r.id} className={`rounded-xl border p-3 cursor-pointer ${selected === r.id ? "border-indigo-400 bg-white/5" : "border-white/10"}`}
                onClick={() => setSelected(r.id)}>
                <div className="flex items-center justify-between">
                  <div className="font-medium">{r.name}</div>
                  <div className="text-xs text-white/40">{r.resume_text.length} 字 · {r.skills.length} 技能</div>
                </div>
                <div className="text-xs text-white/40 mt-1">
                  {r.skills.length ? r.skills.join(" · ") : "未抽取技能"}
                </div>
                {r.is_default && <div className="text-xs text-indigo-400 mt-1">默认</div>}
                <div className="flex gap-3 mt-2" onClick={(e) => e.stopPropagation()}>
                  {!r.is_default && <button className="text-xs text-white/60 hover:text-white" onClick={() => makeDefault(r.id)}>设为默认</button>}
                  <button className="text-xs text-red-400/80 hover:text-red-400" onClick={() => del(r.id)}>删除</button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm">
            简历名称
            <input className="rounded-lg border border-white/10 bg-white/5 p-2" value={name}
              onChange={(e) => setName(e.target.value)} placeholder="如：我的后端简历" />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            简历内容（上传文件自动解码，或直接粘贴文本）
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => fileRef.current?.click()} disabled={parsing}
                className="rounded-lg border border-white/10 hover:border-white/30 bg-white/5 px-3 py-2 text-sm text-white/80">
                {parsing ? "解码中…" : "📄 上传文件"}
              </button>
              <input ref={fileRef} type="file" className="hidden"
                accept=".pdf,.docx,.md,.txt,.xlsx,.xls,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={onFile} />
              <span className="text-xs text-white/40">PDF / Word / Markdown / TXT / Excel</span>
            </div>
            <textarea className="rounded-lg border border-white/10 bg-white/5 p-3 min-h-36" rows={8}
              value={text} onChange={(e) => setText(e.target.value)} placeholder="上传后自动填入，或直接粘贴/手写" />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            技能（逗号分隔，可选）
            <input className="rounded-lg border border-white/10 bg-white/5 p-2" value={skills}
              onChange={(e) => setSkills(e.target.value)} placeholder="Python, Go, MySQL" />
          </label>
          {err && <div className="text-red-400 text-sm">{err}</div>}
          <button onClick={create} disabled={busy} className="rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 p-3 font-semibold">
            {busy ? "保存中…" : "保存简历"}
          </button>

          {sel && (
            <div className="rounded-xl border border-white/10 p-3 text-sm text-white/60">
              <div className="font-medium text-white mb-1">简历预览 · {sel.name}</div>
              <p className="whitespace-pre-wrap max-h-40 overflow-auto">{sel.resume_text}</p>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
