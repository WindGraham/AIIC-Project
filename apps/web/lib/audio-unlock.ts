/**
 * Shared AudioContext helpers.
 *
 * Browsers block audio playback (autoplay policy) until a *user gesture*. LiveKit/duplex
 * audio may be created before any gesture, so `new Audio().play()` can silently fail and
 * the interviewer's voice is never heard. This module keeps ONE AudioContext and unlocks
 * it on the first pointer/click gesture via `unlockAudio()`, so later playback always works.
 */

let sharedCtx: AudioContext | null = null;

/** Get (or lazily create) the shared AudioContext. */
export function getSharedAudioContext(): AudioContext {
  if (!sharedCtx) {
    const AC =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    sharedCtx = new AC();
  }
  return sharedCtx;
}

/** Try to resume the shared context (call on first user gesture). */
export function unlockAudio(): void {
  try {
    const ctx = getSharedAudioContext();
    if (ctx.state === "suspended") void ctx.resume();
  } catch {
    /* ignore */
  }
}

/** Decode an MP3 base64 blob into an AudioBuffer, then play through the shared context.
 * More reliable than `new Audio(url).play()` under autoplay policy. Returns a promise that
 * resolves when playback finishes. */
export async function playMp3Base64(b64: string, mime = "audio/mpeg"): Promise<void> {
  unlockAudio();
  const ctx = getSharedAudioContext();
  try {
    const blob = base64ToBlob(b64, mime);
    const buf = await blob.arrayBuffer();
    const audioBuf = await ctx.decodeAudioData(buf);
    const src = ctx.createBufferSource();
    src.buffer = audioBuf;
    src.connect(ctx.destination);
    return new Promise((resolve) => {
      src.onended = () => resolve();
      src.start();
    });
  } catch {
    /* decode may fail on some codecs */
  }
}

function base64ToBlob(b64: string, mime: string): Blob {
  const s = b64.trim();
  const idx = s.indexOf(",");
  const clean = idx >= 0 ? s.slice(idx + 1) : s;
  const bin = atob(clean);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}
