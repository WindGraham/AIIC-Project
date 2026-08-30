import type { Metadata } from "next";
import { getMe } from "@/lib/agent";
import Nav from "./components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "ProbeDesk · AI 面试官",
  description: "LiveKit 驱动的 AI 模拟面试官平台（CS 算法 / 研发岗）",
};

export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const me = await getMe();
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-[#0b0b0f] text-white">
        <Nav me={me?.user ?? null} />
        {children}
      </body>
    </html>
  );
}
