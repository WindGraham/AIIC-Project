"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Login() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const r = await fetch(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "操作失败");
      router.push("/");
      router.refresh();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="max-w-sm mx-auto p-8 mt-16">
      <h1 className="text-2xl font-bold mb-1">ProbeDesk</h1>
      <p className="text-white/50 text-sm mb-6">{mode === "login" ? "登录你的账号" : "创建新账号"}</p>

      <form onSubmit={submit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          用户名
          <input className="rounded-lg border border-white/10 bg-white/5 p-2" value={username}
            onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          密码
          <input type="password" className="rounded-lg border border-white/10 bg-white/5 p-2" value={password}
            onChange={(e) => setPassword(e.target.value)} required />
        </label>

        {err && <div className="text-red-400 text-sm">{err}</div>}
        <button disabled={busy} className="rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 p-3 font-semibold">
          {busy ? "处理中…" : mode === "login" ? "登录" : "注册并登录"}
        </button>
      </form>

      <p className="mt-6 text-sm text-white/50">
        {mode === "login" ? "还没有账号？" : "已有账号？"}{" "}
        <button className="text-indigo-400" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "去注册" : "去登录"}
        </button>
      </p>
    </main>
  );
}
