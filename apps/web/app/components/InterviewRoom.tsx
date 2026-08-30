"use client";

import { useEffect, useState } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  VideoConference,
  TrackToggle,
  useTracks,
  useLocalParticipant,
  ChatToggle,
  useRoomContext,
} from "@livekit/components-react";
import { Track } from "livekit-client";
import "@livekit/components-styles";

/** 方案2: 以 livekit-meet 的组件库 (@livekit/components-react) 为基础，在 ProbeDesk
 * 房间内重排成"面试态"——去掉会议元素(大厅/参会者列表/聊天/举手)，保留 音视频 +
 * 摄像头 + 麦克风 + 屏幕共享 + 录制。真实音视频走 LiveKit；AI 面试官(agent) 通过
 * `agent_dispatch` 在到点/开场时进入同一房间。 */
export default function InterviewRoom({ interviewId, persona }: { interviewId: string; persona?: string }) {
  const [conn, setConn] = useState<{ token: string; room: string; url: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const identity = `candidate-${Math.random().toString(36).slice(2, 8)}`;
        const r = await fetch(`/api/livekit/token/${interviewId}`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ identity, name: "候选人" }),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || "获取 token 失败");
        setConn(d);
      } catch (e) {
        setErr(String(e));
      }
    })();
  }, [interviewId]);

  if (err) return <div className="rounded-xl border border-white/10 p-4 text-red-400 text-sm">视频房间连接失败：{err}</div>;

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-white/5">
        <div className="text-sm text-white/60">🎥 视频面试间 · {persona ? `人格：${persona}` : "LiveKit"}</div>
        <div className="text-xs text-white/40">语音 / 摄像头 / 屏幕共享 / 录制</div>
      </div>
      {conn ? (
        <LiveKitRoom
          token={conn.token}
          serverUrl={conn.url}
          connect={true}
          audio={true}
          video={true}
          className="bg-black"
          style={{ height: 520 }}
        >
          {/* 候选人画布 + 麦克风/摄像头/屏幕/录制 控制条；无会议元素 */}
          <VideoConference />
          <TrackToggle source={Track.Source.Microphone} />
          <TrackToggle source={Track.Source.Camera} style={{ marginLeft: 8 }} />
          <TrackToggle source={Track.Source.ScreenShare} style={{ marginLeft: 8 }} />
          <RoomAudioRenderer />
        </LiveKitRoom>
      ) : (
        <div className="h-24 flex items-center justify-center text-white/40 text-sm">正在连接视频面试间…</div>
      )}
    </div>
  );
}
