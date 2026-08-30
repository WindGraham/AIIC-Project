/**
 * ScreenFeed — 候选人的摄像头/共享屏实时画面 → 读屏（逐帧即时流）。
 *
 * 每 2s 取一帧（原图，不缩图）→ 立刻单独发给 Kimi 读屏 → 结果即时 POST /screen-note。
 * 采用"帧回完再发下一帧"的串行流：一张结果回来后，立即取最新的下一帧发送。
 * 这样不会因 Kimi(单帧~5s) 延迟而积压请求，且永远发送最新画面，agent 拿到连续旁注。
 */

import { getLiveKitRoom } from "@/lib/livekit-room";

const PROMPT = "这是屏幕实时画面的一帧。用一句中文简述画面中与面试相关的最重要内容，不超过30字。";
const FRAME_MS = 2000;      // 每 2 秒取一帧（Kimi 单帧 ~5s，串行逐帧，不缩图）
const MAX_INFLIGHT = 1;     // 串行：一次只有 1 帧在飞

let stoppedRef = false;
let interviewIdRef = "";
let captureTimer: number | null = null;
let latestFrame: { data: string; mime: string } | null = null;
let inflight = 0;
let sending = false;
let lastSent = new Date(0);

function toJpegB64(video: HTMLVideoElement): string {
  // 原图直出，不缩图（Kimi 支持原图；保持画面细节以便准确读屏）。
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, video.videoWidth);
  canvas.height = Math.max(1, video.videoHeight);
  canvas.getContext("2d")!.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.8).split(",")[1];
}

/** 每 2s 取最新一帧（只保留最新；旧的被覆盖）。若摄像头/共享都关了，就自动停流。 */
async function capture() {
  if (stoppedRef) return;
  const room = getLiveKitRoom();
  if (!room) return;
  const pubs = room.localParticipant.getTrackPublications();
  const hasVideo = pubs.some((p) => p.track?.kind === "video");
  if (!hasVideo) {
    // 监测到摄像头/共享关闭 -> 停止实时视频流识别。
    stopScreenFeed();
    return;
  }

  const scr = pubs.find((p) => p.track?.kind === "video" && (p.source as string) === "screen_share");
  const src = scr?.track?.mediaStreamTrack || pubs.find((p) => p.track?.kind === "video")?.track?.mediaStreamTrack;
  if (!src) return;

  const v = document.createElement("video");
  v.srcObject = new MediaStream([src]);
  v.autoplay = true; v.muted = true; v.playsInline = true;
  await v.play().catch(() => {});
  await new Promise((r) => setTimeout(r, 300));
  if (stoppedRef || v.videoWidth === 0) return;
  try {
    latestFrame = { data: toJpegB64(v), mime: "image/jpeg" };
  } catch {
    latestFrame = null;
  }
}

/** 串行发送：上一帧结果回来后，立即发最新的下一帧。 */
async function drain() {
  if (stoppedRef || sending || inflight >= MAX_INFLIGHT) return;
  if (!latestFrame) return;
  // 有结果回来才发下一帧（避免积压）。
  if (Date.now() - lastSent.getTime() < FRAME_MS) return;
  sending = true;
  const fr = latestFrame;
  latestFrame = null;
  inflight++;
  try {
    const r = await fetch("/api/vision/analyze", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_b64: fr.data, mime: fr.mime, prompt: PROMPT }),
    });
    const d = await r.json();
    const desc: string = d?.description || "";
    lastSent = new Date();
    if (desc && !desc.startsWith("(reading failed") && !d?.error) {
      await fetch(`/api/interviews/${encodeURIComponent(interviewIdRef)}/screen-note`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: desc }),
      }).catch(() => {});
    }
  } catch {
    lastSent = new Date();
  } finally {
    inflight--;
    sending = false;
  }
}

export function startScreenFeed(interviewId: string) {
  interviewIdRef = interviewId;
  stoppedRef = false;
  if (captureTimer) window.clearInterval(captureTimer);
  captureTimer = window.setInterval(capture, FRAME_MS);
  void drain();
  window.setInterval(drain, 600);
}

export function stopScreenFeed() {
  stoppedRef = true;
  if (captureTimer) { window.clearInterval(captureTimer); captureTimer = null; }
  latestFrame = null;
}
