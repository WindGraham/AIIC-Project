/**
 * Browser-side LiveKit agent shim ("AI 面试官 participant").
 *
 * The LiveKit REST API cannot make a participant join a room (participants
 * connect over WebSocket with a JWT). Instead of wiring the heavy
 * livekit-agents worker framework, the FRONTEND opens a second, hidden LiveKit
 * connection under the `agent-interviewer` identity minted by the agent's
 * `agent-join` endpoint. That participant:
 *
 *   1. publishes an "AI 面试官" video tile   -> agent is VIDEO-visible in the room
 *   2. publishes the TTS voice bus as a mic  -> agent is AUDIBLE in the room and
 *                                               in the egress recording
 *   3. subscribes to the candidate's screen-share track, downsamples frames and
 *      POSTs them to /api/vision/analyze (Gemini) -> agent SEES the shared screen
 *
 * Audio path: TTS MP3 is decoded into a shared AudioContext whose
 * MediaStreamDestination is published as the agent's mic track. The candidate
 * room's RoomAudioRenderer plays that remote track — a single playback path, no
 * double audio. When the agent connection is down, `speakInterviewer` falls
 * back to direct <audio> playback (playAudioBase64).
 */

import {
  LocalAudioTrack,
  LocalVideoTrack,
  RemoteTrack,
  Room,
  RoomEvent,
  Track,
} from "livekit-client";
import { playAudioBase64 } from "@/lib/voice";

export type ScreenReadHandler = (text: string) => void;

interface AgentState {
  room: Room | null;
  connected: boolean;
  ctx: AudioContext | null;
  busDest: MediaStreamAudioDestinationNode | null;
  busTrack: LocalAudioTrack | null;
  screenHandler: ScreenReadHandler | null;
  screenVideo: HTMLVideoElement | null;
  sampling: boolean;
  reading: boolean;
  lastReadAt: number;
  tileTimer: number | null;
}

const state: AgentState = {
  room: null,
  connected: false,
  ctx: null,
  busDest: null,
  busTrack: null,
  screenHandler: null,
  screenVideo: null,
  sampling: false,
  reading: false,
  lastReadAt: 0,
  tileTimer: null,
};

export function isAgentConnected(): boolean {
  return state.connected;
}

export function setScreenReadHandler(fn: ScreenReadHandler | null) {
  state.screenHandler = fn;
}

/** Speak the interviewer's TTS through the agent participant (published to the
 * room). Returns true if handled; caller should fall back to direct playback. */
export async function agentSpeak(mp3B64: string): Promise<boolean> {
  if (!state.connected || !state.room) return false;
  try {
    if (!state.ctx || !state.busDest) {
      const AC = (window.AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext) as
        | typeof AudioContext
        | undefined;
      if (!AC) return false;
      state.ctx = new AC();
      state.busDest = state.ctx.createMediaStreamDestination();
    }
    const ctx = state.ctx;
    if (ctx.state === "suspended") {
      try {
        await ctx.resume();
      } catch {
        return false;
      }
    }
    const buf = await fetch(`data:audio/mp3;base64,${mp3B64}`).then((r) => r.arrayBuffer());
    const audioBuf = await ctx.decodeAudioData(buf);
    const src = ctx.createBufferSource();
    src.buffer = audioBuf;
    src.connect(state.busDest!);
    src.start();
    if (!state.busTrack && state.room) {
      const t = state.busDest.stream.getAudioTracks()[0];
      state.busTrack = new LocalAudioTrack(t, undefined, true, ctx);
      await state.room.localParticipant.publishTrack(state.busTrack, {
        name: "interviewer-voice",
        source: Track.Source.Microphone,
      });
    }
    return true;
  } catch (e) {
    console.warn("agentSpeak failed:", e);
    return false;
  }
}

/** Speak interviewer TTS via the agent when possible, else direct playback. */
export async function speakInterviewer(mp3B64: string): Promise<void> {
  if (!(await agentSpeak(mp3B64))) {
    await playAudioBase64(mp3B64);
  }
}

// ---------------------------------------------------------------------------
// Screen-share sampling -> Gemini vision ("agent sees screen")
// ---------------------------------------------------------------------------
const SCREEN_PROMPT =
  "你是一位 AI 面试官，正在实时观看候选人的共享屏幕。请读取并简要描述画面上与面试相关的最重要内容。";

function sampleScreen() {
  if (state.sampling) return;
  state.sampling = true;
  const canvas = document.createElement("canvas");
  const tick = async () => {
    if (!state.connected) {
      state.sampling = false;
      return;
    }
    const v = state.screenVideo;
    if (v && v.videoWidth > 0 && state.screenHandler) {
      const now = Date.now();
      if (now - state.lastReadAt > 6000 && !state.reading) {
        state.reading = true;
        try {
          const maxW = 960;
          const scale = Math.min(1, maxW / v.videoWidth);
          canvas.width = Math.max(1, Math.round(v.videoWidth * scale));
          canvas.height = Math.max(1, Math.round(v.videoHeight * scale));
          canvas.getContext("2d")!.drawImage(v, 0, 0, canvas.width, canvas.height);
          const b64 = canvas.toDataURL("image/jpeg", 0.7).split(",")[1];
          const d = await (
            await fetch("/api/vision/analyze", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ image_b64: b64, prompt: SCREEN_PROMPT }),
            })
          ).json();
          const text: string = d?.description || d?.error || "";
          if (text) {
            state.lastReadAt = Date.now();
            state.screenHandler(text);
          }
        } catch {
          /* keep sampling on next tick */
        } finally {
          state.reading = false;
        }
      }
    }
    setTimeout(tick, 4000);
  };
  tick();
}

// ---------------------------------------------------------------------------
// Join / leave
// ---------------------------------------------------------------------------
export async function joinAsAgent(interviewId: string): Promise<boolean> {
  if (state.connected) return true;
  try {
    const r = await fetch(`/api/interviews/${interviewId}/agent-join`, { method: "POST" });
    const d = await r.json();
    if (!r.ok || !d?.token || !d?.url) {
      console.warn("agent-join failed:", d);
      return false;
    }
    const room = new Room({ adaptiveStream: true });

    room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
      if (track.source === Track.Source.ScreenShare) {
        const v = document.createElement("video");
        v.srcObject = new MediaStream([track.mediaStreamTrack]);
        v.autoplay = true;
        v.muted = true;
        v.playsInline = true;
        v.style.display = "none";
        v.onloadedmetadata = () => v.play().catch(() => {});
        document.body.appendChild(v);
        state.screenVideo = v;
        sampleScreen();
      }
    });
    room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
      if (track.source === Track.Source.ScreenShare && state.screenVideo) {
        state.screenVideo.remove();
        state.screenVideo = null;
      }
    });
    room.on(RoomEvent.Disconnected, () => {
      state.connected = false;
      state.room = null;
      if (state.screenVideo) {
        state.screenVideo.remove();
        state.screenVideo = null;
      }
    });

    await room.connect(d.url, d.token, { autoSubscribe: true });
    state.room = room;
    state.connected = true;

    // 1) publish the interviewer video tile (Canvas -> Camera track)
    const tile = document.createElement("canvas");
    tile.width = 640;
    tile.height = 360;
    const tctx = tile.getContext("2d")!;
    const drawTile = () => {
      const g = tctx.createLinearGradient(0, 0, 0, 360);
      g.addColorStop(0, "#1e3a8a");
      g.addColorStop(1, "#0f172a");
      tctx.fillStyle = g;
      tctx.fillRect(0, 0, 640, 360);
      tctx.fillStyle = "rgba(255,255,255,0.96)";
      tctx.font = "76px system-ui, sans-serif";
      tctx.textAlign = "center";
      tctx.fillText("🤖", 320, 128);
      tctx.font = "bold 42px system-ui, sans-serif";
      tctx.fillText("AI 面试官", 320, 216);
      tctx.font = "26px system-ui, sans-serif";
      tctx.fillStyle = "rgba(255,255,255,0.72)";
      tctx.fillText(state.connected ? "正在聆听与观察…" : "连接中…", 320, 276);
    };
    drawTile();
    state.tileTimer = window.setInterval(drawTile, 5000);
    const vstream = tile.captureStream(10);
    const vtrack = new LocalVideoTrack(vstream.getVideoTracks()[0]);
    await room.localParticipant.publishTrack(vtrack, {
      name: "interviewer-tile",
      source: Track.Source.Camera,
      simulcast: false,
    });

    return true;
  } catch (e) {
    console.warn("joinAsAgent error:", e);
    return false;
  }
}

export function leaveAgent() {
  state.connected = false;
  state.sampling = false;
  state.reading = false;
  if (state.tileTimer !== null) {
    window.clearInterval(state.tileTimer);
    state.tileTimer = null;
  }
  if (state.screenVideo) {
    state.screenVideo.remove();
    state.screenVideo = null;
  }
  state.busTrack = null;
  const room = state.room;
  state.room = null;
  try {
    room?.disconnect();
  } catch {
    /* ignore */
  }
}
