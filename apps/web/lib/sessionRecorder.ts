/**
 * SessionRecorder — 面试期间把"交互数据"保存下来：
 *  1) 音视频：用 MediaRecorder 录制本地 麦克风+共享屏 混合流，结束后上传到 agent 落盘。
 *  2) 转写：把对话（文字/语音转的文字 + agent 回复）实时上报给 agent 落库（transcript）。
 *
 * 全部走 /api/interviews/{id}/recording 与 /api/interviews/{id}/save-transcript，
 * 落在 /data/probedesk/{recordings, sqlite}。
 */

interface Turn {
  role: "ai" | "cand";
  text: string;
  ts: string;
}

export function createSessionRecorder(interviewId: string) {
  let recorder: MediaRecorder | null = null;
  let chunks: Blob[] = [];
  let activeStream: MediaStream | null = null;
  let transcript: Turn[] = [];

  function now() {
    return new Date().toISOString();
  }

  async function start() {
    // Record the candidate's mic + screen (if sharing). Camera video is large; keep
    // mic + screen as the audio/visual evidence, and rely on the transcript for text.
    try {
      const streams: MediaStream[] = [];
      const audio = await navigator.mediaDevices.getUserMedia({ audio: true });
      streams.push(audio);
      activeStream = new MediaStream();
      activeStream.addTrack(audio.getAudioTracks()[0]);
      try {
        const disp = await (navigator.mediaDevices as any).getDisplayMedia({ video: true, audio: false });
        disp.getVideoTracks().forEach((t: MediaStreamTrack) => activeStream!.addTrack(t));
        streams.push(disp);
      } catch {
        // no screen share — record audio only
      }
      const mime = ["video/webm;codecs=vp8,opus", "video/webm", "audio/webm"].find((m) =>
        MediaRecorder.isTypeSupported(m),
      ) || "";
      recorder = new MediaRecorder(activeStream, mime ? { mimeType: mime } : undefined);
      chunks = [];
      recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      recorder.start(2000);
      return true;
    } catch {
      return false; // no mic/screen available — transcript-only fallback
    }
  }

  async function stop() {
    if (!recorder) return;
    const done = new Promise<void>((resolve) => {
      recorder!.onstop = () => resolve();
    });
    try { recorder.stop(); } catch { /* ignore */ }
    await done;
    recorder = null;
    activeStream?.getTracks().forEach((t) => t.stop());
    activeStream = null;
    if (chunks.length) {
      const blob = new Blob(chunks, { type: chunks[0].type || "video/webm" });
      chunks = [];
      const buf = await blob.arrayBuffer();
      const bytes = new Uint8Array(buf);
      let bin = "";
      const chunkSize = 0x8000;
      for (let i = 0; i < bytes.length; i += chunkSize) bin += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
      const b64 = btoa(bin);
      await fetch(`/api/interviews/${interviewId}/recording`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: b64, mime: blob.type }),
      }).catch(() => {});
    }
  }

  function pushTurn(role: "ai" | "cand", text: string) {
    if (!text?.trim()) return;
    transcript.push({ role, text: text.trim(), ts: now() });
    // Fire-and-forget persistence of the running transcript.
    fetch(`/api/interviews/${interviewId}/save-transcript`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: transcript }),
    }).catch(() => {});
  }

  function getTranscript() {
    return transcript;
  }

  return { start, stop, pushTurn, getTranscript };
}
