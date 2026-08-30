import { health } from "@/lib/agent";

export const dynamic = "force-dynamic";

export default async function Home() {
  const h = await health();
  return (
    <main className="min-h-screen flex flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-3xl font-bold">ProbeDesk · AI 面试官</h1>
      <p className="text-white/60">AI 模拟面试平台（CS 算法 / 研发岗）</p>

      <div className="grid grid-cols-2 gap-4 text-sm max-w-xl w-full">
        {Object.entries(h).map(([k, v]) => (
          <div key={k} className="rounded-xl border border-white/10 p-4">
            <div className="text-white/40">{k}</div>
            <pre className="mt-2 whitespace-pre-wrap">{JSON.stringify(v, null, 2)}</pre>
          </div>
        ))}
      </div>
    </main>
  );
}
