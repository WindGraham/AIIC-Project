/**
 * ScreenFeed — 当候选人开了摄像头或共享屏时，周期性采样画面帧 → Gemini 视觉读屏 →
 * 把得到的文本作为"看屏幕"旁注喂给 agent (POST /api/interviews/{id}/screen-note)。
 *
 * 与前端的 livekit-room store 一起：开摄像头/共享即自动开始读屏，关上即停止。
 */

import { getLiveKitRoom } from "@/lib/livekit-room";

const SCREEN_PROMPT =
  "你是一位 AI 面试官，正在实时观看候选人共享的屏幕/摄像头画面。请用简短中文描述画面上与面试相关的最重要内容（代码/文字/图表），不要评论人物。";

let interval: number | null = null;
let lastSent = 0;
let stoppedRef = false;
let interviewIdRef = "";

function toJpegB64(video: HTMLVideoElement, maxW = 960): string {
  const scale = Math.min(1, maxW / video.videoWidth);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
  canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
  canvas.getContext("2d")!.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.7).split(",")[1];
}

async function sample() {
  if (stoppedRef) return;
  const room = getLiveKitRoom();
  if (!room) return;
  // Only sample when the candidate is publishing camera or screen-share video.
  const pubs = room.localParticipant.getTrackPublications();
  const hasVideo = pubs.some((p) => p.track?.kind === "video");
  if (!hasVideo) return;

  const scr = pubs.find((p) => p.track?.kind === "video" && (p.source as string) === "screen_share");
  const srcTrack = scr?.track?.mediaStreamTrack || pubs.find((p) => p.track?.kind === "video")?.track?.mediaStreamTrack;
  if (!srcTrack) return;

  const video = document.createElement("video");
  video.srcObject = new MediaStream([srcTrack]);
  video.autoplay = true;
  video.muted = true;
  video.playsInline = true;
  await video.play().catch(() => {});
  await new Promise((r) => setTimeout(r, 600)); // let metadata load
  if (stoppedRef || video.videoWidth === 0) return;

  const now = Date.now();
  if (now - lastSent < 5000) return; // throttle ~5s
  lastSent = now;

  try {
    const b64 = toJpegB64(video);
    const v = await (
      await fetch("/api/vision/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_b64: b64, prompt: SCREEN_PROMPT }),
      })
    ).json();
    const desc: string = v?.description || "";
    if (desc) {
      // Feed the description to the agent as a screen side-note.
      await fetch(`/api/interviews/${encodeURIComponent(interviewIdRef)}/screen-note`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: desc }),
      });
    }
  } catch {
    /* keep sampling on next tick */
  }
}

/** Start sampling (call when camera/screen turns on — or unconditionally on mount). */
export function startScreenFeed(interviewId: string) {
  interviewIdRef = interviewId;
  stoppedRef = false;
  if (interval) window.clearInterval(interval);
  interval = window.setInterval(() => sample(), 4500);
}

/** Stop sampling. */
export function stopScreenFeed() {
  stoppedRef = true;
  if (interval) {
    window.clearInterval(interval);
    interval = null;
  }
}
