import Link from "next/link";
import { health } from "@/lib/agent";

export const dynamic = "force-dynamic";

const FEATURES = [
  { href: "/booking", title: "预约面试", desc: "选简历、公司/岗位/JD、时间与面试官人格，可提前进房。" },
  { href: "/interviews", title: "面试列表", desc: "查看所有面试、距开始倒计时，随时提前进入。" },
  { href: "/resumes", title: "管理简历", desc: "多份简历、设默认、抽取技能画像。" },
  { href: "/self-test", title: "功能测试", desc: "自测麦克风/摄像头/屏幕共享，不接通面试官。" },
];

export default async function Home() {
  const h = await health();
  const search = (h.search as Record<string, boolean>) || {};
  return (
    <main className="max-w-5xl mx-auto p-6">
      <section className="py-10">
        <h1 className="text-4xl font-bold">ProbeDesk · AI 面试官</h1>
        <p className="text-white/60 mt-2 text-lg">AI 模拟面试平台（CS 算法 / 研发岗）——预约、面试、报告闭环。</p>
      </section>

      <section className="grid sm:grid-cols-2 gap-4">
        {FEATURES.map((f) => (
          <Link key={f.href} href={f.href} className="group rounded-xl border border-white/10 p-5 hover:border-indigo-400/60 transition">
            <div className="font-semibold">{f.title}</div>
            <div className="text-sm text-white/50 mt-1">{f.desc}</div>
          </Link>
        ))}
      </section>

      <section className="mt-10 rounded-xl border border-white/10 p-5 text-sm">
        <div className="flex items-center justify-between">
          <div className="font-semibold">系统状态</div>
          <span className={`text-xs px-2 py-0.5 rounded-full ${h.status === "ok" ? "bg-green-500/20 text-green-400" : "bg-yellow-500/20 text-yellow-400"}`}>
            {h.status === "ok" ? "在线" : "降级"}
          </span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
          {[
            ["LLM", (h.llm as any)?.configured],
            ["视觉", (h.vision as any)?.configured],
            ["语音识别", (h.stt as any)?.configured],
            ["语音合成", (h.tts as any)?.configured],
            ["LiveKit", (h.livekit as any)?.configured],
            ["小红书搜索", search.xhs],
            ["知乎搜索", search.zhihu],
          ].map(([k, v]) => (
            <div key={String(k)} className="rounded-lg border border-white/10 p-3">
              <div className="text-white/40">{k}</div>
              <div className={`mt-1 ${v ? "text-green-400" : "text-yellow-400"}`}>{v ? "已配置" : "未配置"}</div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
