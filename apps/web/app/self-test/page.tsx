"use client";

import { useMemo } from "react";
import InterviewRoom from "@/app/components/InterviewRoom";
import VoiceTextTts from "@/app/components/VoiceTextTts";
import RealtimeScreenList from "@/app/components/RealtimeScreenList";

/**
 * 功能测试：与真实面试完全相同的房间（仅无 AI 进入），用于自测。
 * 新增两个专项测试：
 *   A. 语音气泡 → 文字(STT) → 文字再转成 TTS 语音回放。
 *   B. 开摄像头/共享 → 实时流读屏 → 右侧列表不断更新每一帧内容。
 */
export default function SelfTest() {
  const roomId = useMemo(() => `selftest-${Math.random().toString(36).slice(2, 8)}`, []);

  return (
    <main className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-1">功能测试</h1>
      <p className="text-white/50 text-sm mb-6">
        与真实面试完全相同的房间（AI 面试官不进入），自测 麦克风 / 摄像头 / 屏幕共享，并验证
        语音↔文字↔语音、实时流读屏 两条链路。
      </p>

      <div className="flex flex-col gap-4">
        <VoiceTextTts />

        <div className="rounded-2xl border border-white/10 p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm text-white/50">房间 &amp; 实时流读屏</div>
            <div className="text-xs text-white/40">打开摄像头或共享后，下方/右侧列表实时更新</div>
          </div>
          <InterviewRoom interviewId={roomId} persona="测试" agentless showTask />
          <div className="mt-4">
            <RealtimeScreenList />
          </div>
        </div>
      </div>

      <p className="mt-3 text-xs text-white/40">
        提示：请在控制条打开「摄像头 / 麦克风」，或点「共享」测试共享全屏。若提示需设备权限，请在浏览器地址栏允许后重试。
      </p>
    </main>
  );
}
