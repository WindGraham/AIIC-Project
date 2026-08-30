"use client";

import { useCallback, useEffect, useState } from "react";
import type { JD } from "@/lib/agent";

/** 岗位 JD / 公司 管理：可提前设置多份，设默认，预约时选择。 */
export default function JdManager() {
  const [jds, setJds] = useState<JD[]>([]);
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [position, setPosition] = useState("");
  const [jdText, setJdText] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const r = await fetch("/api/jds");
    if (r.ok) setJds(await r.json());
  }, []);
  useEffect(() => { load(); }, [load]);

  const sel = jds.find((j) => j.id === editing) || null;

  async function save() {
    setErr(null);
    if (!jdText.trim()) { setErr("请填写 JD 内容"); return; }
    setBusy(true);
    try {
      const body = { name: name || `${position || "岗位"}JD`, company, position, jd_text: jdText, is_default: jds.length === 0 };
      const r = editing
        ? await fetch(`/api/jds/${editing}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        : await fetch("/api/jds", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "保存失败");
      setName(""); setCompany(""); setPosition(""); setJdText(""); setEditing(null);
      await load();
    } catch (e: any) { setErr(String(e)); } finally { setBusy(false); }
  }

  async function makeDefault(id: string) {
    const j = jds.find((x) => x.id === id);
    if (!j) return;
    await fetch(`/api/jds/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...j, is_default: true }) });
    await load();
  }

  async function del(id: string) {
    await fetch(`/api/jds/${id}`, { method: "DELETE" });
    if (editing === id) setEditing(null);
    await load();
  }

  function pick(j: JD) {
    setEditing(j.id); setName(j.name); setCompany(j.company); setPosition(j.position); setJdText(j.jd_text);
  }

  return (
    <div className="rounded-2xl border border-white/10 p-4">
      <div className="text-sm text-white/60 mb-2">🏢 岗位 JD / 公司管理</div>
      <div className="grid grid-cols-2 gap-3">
        {/* 列表 */}
        <div className="flex flex-col gap-2">
          {jds.length === 0 && <div className="text-white/40 text-sm">还没有岗位 JD，先在右侧添加一份（新用户已默认一份）。</div>}
          {jds.map((j) => (
            <div key={j.id} className={`rounded-lg border p-3 cursor-pointer ${editing === j.id ? "border-indigo-400 bg-white/5" : "border-white/10"}`}
              onClick={() => pick(j)}>
              <div className="flex items-center justify-between">
                <div className="font-medium">{j.name}</div>
                <div className="text-xs text-white/40">{j.company} · {j.position}</div>
              </div>
              {j.is_default && <div className="text-xs text-indigo-400 mt-1">默认</div>}
            </div>
          ))}
        </div>
        {/* 表单 */}
        <div className="flex flex-col gap-2">
          <input className="rounded-lg border border-white/10 bg-white/5 p-2 text-sm" placeholder="名称（默认用岗位名）" value={name} onChange={(e) => setName(e.target.value)} />
          <input className="rounded-lg border border-white/10 bg-white/5 p-2 text-sm" placeholder="公司" value={company} onChange={(e) => setCompany(e.target.value)} />
          <input className="rounded-lg border border-white/10 bg-white/5 p-2 text-sm" placeholder="岗位" value={position} onChange={(e) => setPosition(e.target.value)} />
          <textarea className="rounded-lg border border-white/10 bg-white/5 p-2 text-sm min-h-32" placeholder="JD 内容…" value={jdText} onChange={(e) => setJdText(e.target.value)} />
          {err && <div className="text-red-400 text-xs">{err}</div>}
          <div className="flex gap-2">
            <button onClick={save} disabled={busy} className="rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-4 py-2 text-sm font-semibold">
              {editing ? "更新 JD" : "添加 JD"}
            </button>
            {editing && <button onClick={() => { setEditing(null); setName(""); setCompany(""); setPosition(""); setJdText(""); }} className="rounded-lg border border-white/10 px-3 py-2 text-sm text-white/70">取消</button>}
          </div>
          {sel && (
            <div className="flex gap-2">
              {!sel.is_default && <button onClick={() => makeDefault(sel.id)} className="text-xs text-indigo-300 hover:underline">设为默认</button>}
              <button onClick={() => del(sel.id)} className="text-xs text-red-400/80 hover:text-red-400">删除</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
