/**
 * Full-duplex (phone-call style) voice client for ProbeDesk.
 *
 * The microphone stays open for the whole interview — no push-to-talk. The
 * user just talks; the agent's WebSocket endpoint transcribes continuously
 * (live partial captions), commits candidate turns ("final"), replies with
 * interviewer speech ("spoken" + MP3 "audio" chunks) and auto-interrupts its
 * own speech the moment it hears the user talk again. This client's only jobs:
 * stream 16 kHz int16 mono PCM frames over the WS and queue incoming MP3
 * chunks for gapless sequential playback.
 *
 * ── Agent WS endpoint:  ws(s)://<agent>/ws/voice?interview_id=<id>
 *
 *   Client → server:
 *     JSON  {"type":"start"}            sent once the socket is open
 *     binary PCM frames                 640 bytes = 320 samples = 20 ms @16 kHz
 *                                       int16 little-endian, mono
 *     JSON  {"type":"stop"}             sent on teardown
 *
 *   Server → client (client is tolerant of extra/unknown fields and types):
 *     JSON  {"type":"partial","text":…} live caption while the user talks
 *     JSON  {"type":"final","text":…}   committed candidate turn
 *     JSON  {"type":"audio","base64":…} MP3 chunk to play immediately
 *     JSON  {"type":"spoken","text":…}  interviewer line (add as AI turn)
 *     JSON  {"type":"done"}             interview finished
 *
 * ── WS URL resolution (the browser cannot read server-side env) ──────────────
 *   1. NEXT_PUBLIC_AGENT_WS_URL (build-time override, e.g. wss://host/ws/voice)
 *   2. GET /api/voice/ws-config         runtime; server derives the URL from
 *                                       AGENT_API_URL / AGENT_WS_URL (same box:
 *                                       ws://127.0.0.1:8000/ws/voice)
 *   3. same-origin ws(s)://<location.host>/ws/voice — production fallback when
 *      nginx upgrades /ws/voice to the agent (see deploy/nginx.conf)
 *
 * ── Why not a Next.js route-handler WS proxy? ────────────────────────────────
 * App Router route handlers are request/response only: Next never hands them
 * the raw HTTP upgrade, so they cannot tunnel a WebSocket to the agent. A real
 * proxy would require replacing `next start` with a custom Node server (not
 * used here). The client therefore connects to the agent directly; in
 * production nginx performs the upgrade.
 */

export type FullDuplexStatus = "idle" | "starting" | "live" | "error" | "stopped";

import { playMp3Base64 } from "@/lib/audio-unlock";

export interface FullDuplexCallbacks {
  /** Live partial transcription while the user is talking. */
  onPartial?: (text: string) => void;
  /** Committed candidate turn — add to the conversation as "我". */
  onFinal?: (text: string) => void;
  /** Interviewer line — add to the conversation as "面试官". */
  onSpoken?: (text: string, section?: string, phase?: string) => void;
  /** Raw incoming audio chunk (already queued by the engine; informational). */
  onAudio?: (base64: string) => void;
  /** The agent signalled the interview is over. */
  onDone?: () => void;
  /** Engine lifecycle changes (connection, mic, playback). */
  onStatus?: (status: FullDuplexStatus, detail?: string) => void;
}

export interface FullDuplexHandle {
  /** Open the WS, start the mic and begin streaming PCM frames. */
  start(): Promise<void>;
  /** Send {"type":"stop"}, close the socket and release the mic. */
  stop(): void;
  /** Send an arbitrary JSON control message while connected. */
  sendControl(msg: Record<string, unknown>): void;
  /** Send a raw binary chunk (e.g. a pre-recorded PCM frame) if open. */
  sendAudioChunk(data: ArrayBuffer): void;
  isLive(): boolean;
}

const FRAME_SAMPLES = 320; // 20 ms @ 16 kHz int16 mono → 640 bytes
const TARGET_RATE = 16000;
const MAX_PENDING_BYTES = 30 * TARGET_RATE * 2; // ~30 s of buffered PCM cap
const MAX_CONNECT_ATTEMPTS = 3;
const CONNECT_TIMEOUT_MS = 8000;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// Linear-interpolation resampler (defensive: most browsers honour
// AudioContext({sampleRate:16000}) and resample the media stream themselves,
// but if ctx.sampleRate differs we do it here).
// ---------------------------------------------------------------------------
function resampleLinear(input: Float32Array, from: number, to: number): Float32Array {
  if (from <= 0 || to <= 0 || from === to) return input;
  const ratio = from / to;
  const outLen = Math.max(1, Math.ceil(input.length / ratio));
  const out = new Float32Array(outLen);
  let t = 0;
  for (let o = 0; o < outLen; o++) {
    const i = Math.min(Math.floor(t), input.length - 1);
    const frac = t - i;
    const s0 = input[i];
    const s1 = input[Math.min(i + 1, input.length - 1)];
    out[o] = s0 + (s1 - s0) * frac;
    t += ratio;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Sequential MP3 playback queue (minimal gap; new chunks append at the end).
// Interruption is handled by the server: it stops sending chunks when the
// user talks, so this queue simply drains what was already received.
// ---------------------------------------------------------------------------
function createPlaybackQueue() {
  const queue: string[] = []; // MP3 base64 chunks, played sequentially via shared AudioContext
  let playing = false;
  let stopped = false;

  function pump() {
    if (playing || stopped || queue.length === 0) return;
    playing = true;
    const b64 = queue.shift()!;
    // Play through the shared (user-gesture-unlocked) AudioContext so the agent's
    // voice is actually audible under browser autoplay policy.
    playMp3Base64(b64).then(() => { playing = false; pump(); });
  }

  return {
    enqueue(b64: string) {
      if (stopped) return;
      queue.push(b64);
      pump();
    },
    clear() {
      queue.length = 0;
    },
    stop() {
      stopped = true;
      queue.length = 0;
      playing = false;
    },
  };
}

// ---------------------------------------------------------------------------
// WS URL resolution
// ---------------------------------------------------------------------------
async function resolveAgentWsBase(): Promise<string> {
  const buildTime = process.env.NEXT_PUBLIC_AGENT_WS_URL;
  if (buildTime) return buildTime.replace(/\/$/, "");
  try {
    const r = await fetch("/api/voice/ws-config", { cache: "no-store" });
    if (r.ok) {
      const d = await r.json();
      if (typeof d?.url === "string" && d.url) return d.url.replace(/\/$/, "");
    }
  } catch {
    /* fall through */
  }
  const proto = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${typeof window !== "undefined" ? window.location.host : "127.0.0.1:8000"}/ws/voice`;
}

// ---------------------------------------------------------------------------
// Full-duplex engine
// ---------------------------------------------------------------------------
export function createFullDuplex(interviewId: string, callbacks: FullDuplexCallbacks = {}): FullDuplexHandle {
  let ws: WebSocket | null = null;
  let status: FullDuplexStatus = "idle";
  let stream: MediaStream | null = null;
  let ctx: AudioContext | null = null;
  let src: MediaStreamAudioSourceNode | null = null;
  let processor: ScriptProcessorNode | null = null;

  // int16 sample accumulator → 640-byte frames; buffered until the WS is open
  // so early mic audio isn't lost while getUserMedia/connect race.
  const acc: number[] = [];
  const pending: ArrayBuffer[] = [];
  let pendingBytes = 0;

  const playback = createPlaybackQueue();
  let stopping = false;

  function setStatus(s: FullDuplexStatus, detail?: string) {
    status = s;
    try {
      callbacks.onStatus?.(s, detail);
    } catch {
      /* callback errors must not break the engine */
    }
  }

  function pushSamples(f32: Float32Array) {
    for (let i = 0; i < f32.length; i++) {
      const v = Math.max(-32768, Math.min(32767, Math.round(f32[i] * 32767)));
      acc.push(v);
    }
    while (acc.length >= FRAME_SAMPLES) {
      const frame = new Int16Array(FRAME_SAMPLES);
      for (let i = 0; i < FRAME_SAMPLES; i++) frame[i] = acc[i];
      acc.splice(0, FRAME_SAMPLES);
      const buf: ArrayBuffer = frame.buffer;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(buf);
      } else {
        pending.push(buf);
        pendingBytes += buf.byteLength;
        if (pendingBytes > MAX_PENDING_BYTES) {
          pending.length = 0;
          pendingBytes = 0;
        }
      }
    }
  }

  function flushPending() {
    while (pending.length > 0) {
      const buf = pending.shift()!;
      pendingBytes -= buf.byteLength;
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(buf);
    }
  }

  function handleServerMessage(data: string | Blob | ArrayBuffer): void {
    let text: string;
    if (typeof data === "string") text = data;
    else if (data instanceof Blob) {
      // Tolerant: server may deliver text frames as Blobs.
      const reader = new FileReader();
      reader.onload = () => handleServerMessage(String(reader.result ?? ""));
      reader.readAsText(data);
      return;
    } else {
      text = new TextDecoder().decode(data);
    }
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(text) as Record<string, unknown>;
    } catch {
      return; // binary frame we don't understand — ignore
    }
    if (!msg || typeof msg.type !== "string") return;
    const str = (k: string) => (typeof msg[k] === "string" ? (msg[k] as string).trim() : "");
    switch (msg.type) {
      case "partial":
        if (str("text")) callbacks.onPartial?.(str("text"));
        break;
      case "final":
        if (str("text")) {
          callbacks.onFinal?.(str("text"));
        }
        break;
      case "spoken": {
        const t = str("text");
        if (t) callbacks.onSpoken?.(t, str("section") || undefined, str("phase") || undefined);
        // 新版协议：spoken 自带完整 `audio`（先行生成好的语音），text 与 voice 同时到达，
        // 立即播放，实现"语音生成好之后再回复"。若无 audio，则等后续 streaming 音频块。
        const bundled = str("audio") || str("audio_b64") || str("data");
        if (bundled) {
          callbacks.onAudio?.(bundled);
          playback.enqueue(bundled);
        }
        break;
      }
      case "audio": {
        const b64 = str("base64") || str("audio_b64") || str("data");
        if (b64) {
          callbacks.onAudio?.(b64);
          playback.enqueue(b64);
        }
        break;
      }
      case "done":
        // `done` = the WHOLE interview is over (the agent said so). Stop & show report.
        callbacks.onDone?.();
        break;
      case "end_turn":
        // Normal end of one spoken turn — keep listening for the next result.
        break;
      case "error":
        // non-fatal provider error (e.g. one STT/TTS call failed) — keep listening
        if (str("error")) console.warn("[fullDuplexVoice] agent error:", str("error"));
        break;
      default:
        break; // tolerate unknown protocol extensions
    }
  }

  function openSocket(url: string): Promise<WebSocket> {
    return new Promise((resolve, reject) => {
      const sock = new WebSocket(url);
      sock.binaryType = "arraybuffer";
      let settled = false;
      const timer = window.setTimeout(() => {
        if (settled) return;
        settled = true;
        try {
          sock.close();
        } catch {
          /* ignore */
        }
        reject(new Error("语音连接超时"));
      }, CONNECT_TIMEOUT_MS);
      sock.onopen = () => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        resolve(sock);
      };
      sock.onmessage = (ev) => handleServerMessage(ev.data);
      sock.onclose = () => {
        window.clearTimeout(timer);
        if (!settled) {
          settled = true;
          reject(new Error("语音连接关闭"));
          return;
        }
        if (ws === sock && !stopping) {
          ws = null;
          setStatus("error", "语音连接已断开");
        }
      };
      sock.onerror = () => {
        /* onclose follows; avoid double-handling */
      };
    });
  }

  async function connectWs(): Promise<void> {
    const base = await resolveAgentWsBase();
    const sep = base.includes("?") ? "&" : "?";
    const url = `${base}${sep}interview_id=${encodeURIComponent(interviewId)}`;
    let lastErr: unknown = null;
    for (let attempt = 1; attempt <= MAX_CONNECT_ATTEMPTS; attempt++) {
      try {
        const sock = await openSocket(url);
        ws = sock;
        try {
          sock.send(JSON.stringify({ type: "start" }));
        } catch {
          /* ignore */
        }
        flushPending();
        return;
      } catch (e) {
        lastErr = e;
        if (attempt < MAX_CONNECT_ATTEMPTS) await sleep(1200 * attempt);
      }
    }
    throw lastErr instanceof Error ? lastErr : new Error("无法连接语音服务");
  }

  async function startMic(): Promise<void> {
    const AC =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) throw new Error("浏览器不支持 Web Audio");
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("浏览器不支持麦克风");
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
    });
    ctx = new AC({ sampleRate: TARGET_RATE });
    try {
      await ctx.resume();
    } catch {
      /* some browsers refuse until a gesture; capture may start late — buffered anyway */
    }
    src = ctx.createMediaStreamSource(stream);
    processor = ctx.createScriptProcessor(4096, 1, 1);
    processor.onaudioprocess = (e) => {
      const ch = e.inputBuffer.getChannelData(0);
      // Defensive downsample; normally ctx.sampleRate is already 16000.
      pushSamples(ctx!.sampleRate === TARGET_RATE ? ch : resampleLinear(ch, ctx!.sampleRate, TARGET_RATE));
    };
    // A ScriptProcessor only runs when connected into the graph; a zero-gain
    // stage keeps it processing without monitoring the mic through speakers
    // (which would feed back into the agent's barge-in VAD).
    const mute = ctx.createGain();
    mute.gain.value = 0;
    src.connect(processor);
    processor.connect(mute);
    mute.connect(ctx.destination);
  }

  function stopMic() {
    try {
      processor?.disconnect();
      src?.disconnect();
      stream?.getTracks().forEach((t) => t.stop());
      ctx?.close();
    } catch {
      /* ignore */
    }
    processor = null;
    src = null;
    stream = null;
    ctx = null;
  }

  async function start(): Promise<void> {
    if (status === "live" || status === "starting") return;
    stopping = false;
    setStatus("starting");
    try {
      // 1) mic first so no audio is lost while the socket connects
      await startMic();
      // 2) socket (buffered frames are flushed on open)
      await connectWs();
      setStatus("live");
    } catch (e) {
      stopMic();
      setStatus("error", e instanceof Error ? e.message : String(e));
      throw e;
    }
  }

  function stop() {
    stopping = true;
    try {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "stop" }));
      }
      ws?.close();
    } catch {
      /* ignore */
    }
    ws = null;
    playback.stop();
    pending.length = 0;
    pendingBytes = 0;
    acc.length = 0;
    stopMic();
    setStatus("stopped");
  }

  return {
    start,
    stop,
    sendControl(msg: Record<string, unknown>) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify(msg));
        } catch {
          /* ignore */
        }
      }
    },
    sendAudioChunk(data: ArrayBuffer) {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(data);
      else if (!stopping) {
        pending.push(data);
        pendingBytes += data.byteLength;
      }
    },
    isLive: () => status === "live",
  };
}
