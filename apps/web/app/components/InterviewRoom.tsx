"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  VideoConference,
  RoomContext,
  RoomAudioRenderer,
} from "@livekit/components-react";
import {
  Room,
  RoomConnectOptions,
  VideoPresets,
} from "livekit-client";
import "@livekit/components-styles";

/**
 * 视频房间：以 livekit-meet 同款组件 (@livekit/components-react) 为基础。
 *
 * 直接复用 meet 的 `VideoConference` prefab——它自带 视频网格 + 麦克风/摄像头/
 * 屏幕共享控制条 + 屏幕共享全屏预览（即 meet 前端那三项），因此本地摄像头与
 * 共享全屏能正常显示。为保证连接稳定，这里用与 meet 相同的原始 `Room` +
 * `enableCameraAndMicrophone()` 流程，而非更高层的 <LiveKitRoom>。
 *
 * 复用/定制：
 *  - `agentless`：进入与真实面试完全相同的房间，但无人机面试官在场——用于「功能测试」。
 *  - `showTask`：下方附带「题目 + 代码书写区」（功能测试 / 双栏布局用）。
 */
export default function InterviewRoom({
  interviewId,
  persona,
  agentless = false,
  showTask = false,
}: {
  interviewId: string;
  persona?: string;
  agentless?: boolean;
  showTask?: boolean;
}) {
  const [conn, setConn] = useState<{ token: string; room: string; url: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [camera, setCamera] = useState(!agentless);
  const [mic, setMic] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const identity = agentless
          ? `selftest-${Math.random().toString(36).slice(2, 8)}`
          : `candidate-${Math.random().toString(36).slice(2, 8)}`;
        const r = await fetch(`/api/livekit/token/${interviewId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ identity, name: agentless ? "测试者" : "候选人" }),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || "获取 token 失败");
        setConn(d);
      } catch (e) {
        setErr(String(e));
      }
    })();
  }, [interviewId, agentless]);

  if (err)
    return (
      <div className="rounded-xl border border-white/10 p-4 text-red-400 text-sm">
        视频房间连接失败：{err}
      </div>
    );

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-white/5">
        <div className="text-sm text-white/60">
          🎥 {agentless ? "测试房间" : "视频面试间"} · {persona ? `人格:${persona}` : "LiveKit"}
        </div>
        <div className="text-xs text-white/40">麦克风 / 摄像头 / 屏幕共享</div>
      </div>
      {conn ? (
        <LiveRoom
          key={interviewId + (agentless ? "-st" : "")}
          url={conn.url}
          token={conn.token}
          camera={camera}
          mic={mic}
          onCamera={setCamera}
          onMic={setMic}
        />
      ) : (
        <div className="h-24 flex items-center justify-center text-white/40 text-sm">
          正在连接视频面试间…
        </div>
      )}
      {showTask && <TaskPanel />}
    </div>
  );
}

function LiveRoom({
  url,
  token,
  camera,
  mic,
  onCamera,
  onMic,
}: {
  url: string;
  token: string;
  camera: boolean;
  mic: boolean;
  onCamera: (v: boolean) => void;
  onMic: (v: boolean) => void;
}) {
  const [ready, setReady] = useState(false);
  const room = useMemo(
    () =>
      new Room({
        adaptiveStream: true,
        dynacast: true,
        publishDefaults: { red: true, videoSimulcastLayers: [VideoPresets.h540, VideoPresets.h216] },
      }),
    [],
  );

  useEffect(() => {
    let alive = true;
    const connectOptions: RoomConnectOptions = { autoSubscribe: true };
    room
      .connect(url, token, connectOptions)
      .then(() => {
        // 与 meet 相同：进入即开启麦克风与摄像头，保证本地预览与共享屏正常。
        room.localParticipant.setMicrophoneEnabled(mic).catch(() => {});
        if (camera) room.localParticipant.setCameraEnabled(true).catch(() => {});
        if (alive) setReady(true);
      })
      .catch((e) => console.error("room connect failed:", e));
    return () => {
      alive = false;
      room.disconnect().catch(() => {});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, token]);

  useEffect(() => {
    if (room.localParticipant?.isMicrophoneEnabled !== mic) {
      room.localParticipant.setMicrophoneEnabled(mic).catch(() => {});
    }
  }, [mic, room]);

  useEffect(() => {
    if (room.localParticipant?.isCameraEnabled !== camera) {
      room.localParticipant.setCameraEnabled(camera).catch(() => {});
    }
  }, [camera, room]);

  return (
    <RoomContext.Provider value={room}>
      {ready ? (
        <div style={{ height: 300 }} className="relative">
          <VideoConference />
          <RoomAudioRenderer />
        </div>
      ) : (
        <div className="h-24 flex items-center justify-center text-white/40 text-sm">正在进入房间…</div>
      )}
      <div className="flex items-center gap-4 px-4 py-2 border-t border-white/10">
        <button
          onClick={() => onMic(!mic)}
          className={`rounded-lg px-3 py-1.5 text-sm ${mic ? "bg-emerald-500/20 text-emerald-300" : "bg-white/10 text-white/40"}`}
        >
          {mic ? "🎙️ 麦克风开" : "🔇 麦克风关"}
        </button>
        <button
          onClick={() => onCamera(!camera)}
          className={`rounded-lg px-3 py-1.5 text-sm ${camera ? "bg-emerald-500/20 text-emerald-300" : "bg-white/10 text-white/40"}`}
        >
          {camera ? "📷 摄像头开" : "📷 摄像头关"}
        </button>
        <span className="text-xs text-white/40">共享屏幕：用 VideoConference 控制条的「共享」</span>
      </div>
    </RoomContext.Provider>
  );
}

/** 题目 + 手撕代码书写区（用于「功能测试」房间，或双栏布局时）。 */
function TaskPanel() {
  const [code, setCode] = useState("");
  const [question, setQuestion] = useState(
    "（功能测试）这里会在真实面试中显示当前题目；你可在此练习书写代码。",
  );
  return (
    <div className="border-t border-white/10 p-4">
      <div className="text-sm text-white/50 mb-2">🧩 题目 + 代码区（功能测试）</div>
      <div className="text-sm text-white/80 mb-2">{question}</div>
      <textarea
        className="w-full h-36 rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-sm"
        spellCheck={false}
        placeholder="在这里练习写你的代码…"
        value={code}
        onChange={(e) => setCode(e.target.value)}
      />
    </div>
  );
}

/**
 * ControlDock — 右侧竖列：小摄像头缩略图 + 麦克风/摄像头/共享屏 基础控制 + 聊天开关。
 * 与 LiveKit 房间解耦（直接操作浏览器媒体设备），让"左屏对话、右侧设备控制"布局成立。
 */
export function ControlDock({ onChatOpen }: { onChatOpen?: (open: boolean) => void }) {
  const camRef = useRef<HTMLVideoElement | null>(null);
  const [camOn, setCamOn] = useState(false);
  const [micOn, setMicOn] = useState(true);
  const [screenOn, setScreenOn] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Reflect a camera stream into the small thumbnail.
  async function toggleCam() {
    if (camOn) {
      camRef.current?.srcObject && (camRef.current.srcObject = null);
      setCamOn(false);
      return;
    }
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: true });
      if (camRef.current) { camRef.current.srcObject = s; await camRef.current.play().catch(() => {}); }
      setCamOn(true);
      setErr(null);
    } catch (e: any) {
      setErr("摄像头不可用：" + (e?.message || String(e)));
    }
  }

  async function toggleMic() {
    if (micOn) { setMicOn(false); return; }
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      setMicOn(true);
      setErr(null);
    } catch (e: any) {
      setErr("麦克风不可用：" + (e?.message || String(e)));
    }
  }

  async function toggleScreen() {
    if (screenOn) {
      camRef.current?.srcObject && (camRef.current.srcObject = null);
      setScreenOn(false);
      return;
    }
    try {
      const s = await (navigator.mediaDevices as any).getDisplayMedia({ video: true, audio: false });
      const track = s.getVideoTracks()[0];
      if (track) track.onended = () => setScreenOn(false);
      if (camRef.current) { camRef.current.srcObject = s; await camRef.current.play().catch(() => {}); }
      setScreenOn(true);
      setErr(null);
    } catch (e: any) {
      setErr("共享屏失败：" + (e?.message || String(e)));
    }
  }

  function toggleChat() {
    const next = !chatOpen;
    setChatOpen(next);
    onChatOpen?.(next);
  }

  const Btn = ({ on, onClick, icon, label }: { on: boolean; onClick: () => void; icon: string; label: string }) => (
    <button onClick={onClick} title={label}
      className={`w-11 h-11 rounded-full flex items-center justify-center text-lg transition-colors ${on ? "bg-emerald-500/25 border-emerald-400/40" : "bg-white/5 border-white/15"}`}>
      {icon}
    </button>
  );

  return (
    <div className="flex flex-col items-center gap-1">
      {/* 小摄像头/共享屏缩略图（右上角） */}
      <div className="w-[152px] h-[86px] rounded-lg bg-black/50 border border-white/10 overflow-hidden relative">
        <video ref={camRef} muted playsInline className="w-full h-full object-cover" />
        <span className="absolute bottom-0.5 left-1 text-[9px] text-white/50">
          {screenOn ? "屏幕共享" : camOn ? "本地摄像头" : "摄像头关"}
        </span>
      </div>
      {/* 竖列基础控制：视频/共享/麦克风/聊天 */}
      <div className="flex flex-col gap-1.5 items-center pt-1">
        <Btn on={camOn} onClick={toggleCam} icon="📷" label="摄像头" />
        <Btn on={screenOn} onClick={toggleScreen} icon="🖥️" label="共享屏幕" />
        <Btn on={micOn} onClick={toggleMic} icon={micOn ? "🎙️" : "🔇"} label="麦克风" />
        <Btn on={chatOpen} onClick={toggleChat} icon="💬" label="聊天" />
      </div>
      {err && <div className="mt-1 max-w-[152px] text-[10px] text-red-400 text-center">{err}</div>}
    </div>
  );
}
