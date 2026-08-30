"use client";

import { useMemo } from "react";
import InterviewRoom from "@/app/components/InterviewRoom";

/**
 * 功能测试：一个与真实面试完全相同的房间，只是 A 面试官不进入。
 *
 * 你在房间内自测 麦克风 / 摄像头 / 屏幕共享（meet 同款控制条与网格），下方带
 * 「题目 + 代码书写区」，与真实面试体验一致，方便正式面试前把所有设备都调好。
 */
export default function SelfTest() {
  // 每次进入生成一个一次性房间 id（无面试官，仅自测）。URL/房间名不需要对应用户数据。
  const roomId = useMemo(() => `selftest-${Math.random().toString(36).slice(2, 8)}`, []);

  return (
    <main className="max-w-3xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-1">功能测试</h1>
      <p className="text-white/50 text-sm mb-6">
        这是一个与真实面试完全相同的房间，但 AI 面试官不会进入。请在房间内调试
        <span className="text-white/80"> 麦克风、摄像头、屏幕共享</span>，并可在下方题目区试写代码。
      </p>
      <InterviewRoom
        interviewId={roomId}
        persona="测试"
        agentless
        showTask
      />
      <p className="mt-3 text-xs text-white/40">
        提示：进入后请在右上控制条打开「摄像头 / 麦克风」，用「共享」按钮测试共享全屏。
        若提示需要设备权限，请在浏览器地址栏中允许后再试。
      </p>
    </main>
  );
}
