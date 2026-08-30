/**
 * Push-to-talk (按住说话) voice client for ProbeDesk.
 *
 * More stable than full-duplex: the user holds a button to talk, releases to send.
 * While held we capture mic audio to a 16 kHz mono WAV; on release we POST the
 * WAV to /api/voice/answer (PTT endpoint). The agent transcribes it (Volcengine
 * STT), runs the SAME per-round interviewer agent, and returns fresh TTS audio
 * (MiniMax) which we play back.
 *
 *   Recording -> MediaRecorder/WebAudio WAV (16 kHz mono) -> POST /api/voice/answer
 *   <- {spoken, audio_b64, next_question, done, section, phase}
 *
 * This is intentionally simpler than the full-duplex WS: no continuous mic, no
 * barge-in logic, one utterance per tap. Falls back cleanly to text when the mic
 * or STT/TTS is unavailable.
 */

import { createRecorder, playAudioBase64, base64ToBlob } from "@/lib/voice";

export interface PttCallbacks {
  /** Live-ish partial while recording (best-effort; PTT sends a single burst). */
  onRecording?: (active: boolean) => void;
  /** Agent's spoken line (the next interviewer question / follow-up). */
  onSpoken?: (text: string) => void;
  /** The interview is over. */
  onDone?: () => void;
  /** Non-fatal error (STT/TTS/network) — the room should fall back to text. */
  onError?: (message: string) => void;
  /** Engine/orchestrator status change. */
  onStatus?: (status: "idle" | "recording" | "processing" | "playing" | "error") => void;
}

export interface PttHandle {
  /** Begin capturing through the mic (hold). */
  press(): Promise<boolean>;
  /** Stop capturing, send the recorded utterance, and play the reply. */
  release(): Promise<void>;
  /** Release and discard without sending (cancel). */
  cancel(): void;
  isRecording(): boolean;
  /** Play a pre-existing agent line's audio directly (e.g. the opening). */
  playLine(b64: string): Promise<void>;
}

export function createPtt(interviewId: string, callbacks: PttCallbacks = {}): PttHandle {
  let recorder: ReturnType<typeof createRecorder> | null = null;
  let recording = false;
  let ctx: AudioContext | null = null;

  function setStatus(s: Parameters<NonNullable<PttCallbacks["onStatus"]>>[0]) {
    try {
      callbacks.onStatus?.(s);
    } catch {
      /* ignore */
    }
  }

  async function press(): Promise<boolean> {
    if (recording) return true;
    try {
      recorder = createRecorder();
      await recorder.start();
      recording = true;
      setStatus("recording");
      callbacks.onRecording?.(true);
      return true;
    } catch (e) {
      setStatus("error");
      callbacks.onError?.(String(e));
      return false;
    }
  }

  async function release(): Promise<void> {
    if (!recording || !recorder) return;
    recording = false;
    setStatus("processing");
    callbacks.onRecording?.(false);
    try {
      const b64 = await recorder.stop();
      recorder = null;
      if (!b64) {
        setStatus("idle");
        callbacks.onError?.("没有录到声音，请重试。");
        return;
      }
      const d = await (
        await fetch("/api/voice/answer", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ interview_id: interviewId, audio_b64: b64, format: "wav" }),
        })
      ).json();
      if (d.done) callbacks.onDone?.();
      else if (d.spoken) {
        callbacks.onSpoken?.(d.spoken);
        setStatus("playing");
        if (d.audio_b64) await playAudioBase64(d.audio_b64);
        else callbacks.onError?.("AI 语音服务不可用，可查看文字。");
      }
    } catch (e) {
      setStatus("error");
      callbacks.onError?.(String(e));
    } finally {
      setStatus("idle");
    }
  }

  function cancel() {
    recording = false;
    recorder = null;
    setStatus("idle");
  }

  async function playLine(b64: string) {
    if (!b64) return;
    try {
      setStatus("playing");
      const blob = base64ToBlob(b64, "audio/mpeg");
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => {
        URL.revokeObjectURL(url);
        setStatus("idle");
      };
      await audio.play();
    } catch {
      setStatus("idle");
    }
  }

  void ctx;
  return {
    press,
    release,
    cancel,
    isRecording: () => recording,
    playLine,
  };
}
