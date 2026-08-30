import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ProbeDesk · AI 面试官",
  description: "LiveKit 驱动的 AI 模拟面试官平台（CS 算法 / 研发岗）",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
