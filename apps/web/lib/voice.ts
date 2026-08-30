/** Browser-side voice capture (Web Audio -> 16kHz mono WAV) + audio playback.
 * We avoid MediaRecorder/webm because Volcengine flash STT accepts WAV/MP3; this
 * produces a raw PCM WAV without needing ffmpeg. Server handles STT/TTS. */

export interface VoiceRecorder {
  start(): Promise<void>;
  stop(): Promise<string>; // base64 wav
}

function encodeWav(samples: Int16Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (o: number, s: string) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };
  writeStr(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); writeStr(8, "WAVE");
  writeStr(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  writeStr(36, "data"); view.setUint32(40, samples.length * 2, true);
  let off = 44;
  for (let i = 0; i < samples.length; i++) { view.setInt16(off, samples[i], true); off += 2; }
  return new Blob([view], { type: "audio/wav" });
}

export function createRecorder(): VoiceRecorder {
  let ctx: AudioContext | null = null;
  let src: MediaStreamAudioSourceNode | null = null;
  let processor: ScriptProcessorNode | null = null;
  let stream: MediaStream | null = null;
  let raw: number[] = [];

  async function start() {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
    });
    const AC = (window.AudioContext || (window as any).webkitAudioContext) as typeof AudioContext;
    ctx = new AC({ sampleRate: 16000 });
    src = ctx.createMediaStreamSource(stream);
    processor = ctx.createScriptProcessor(4096, 1, 1);
    raw = [];
    processor.onaudioprocess = (e) => {
      const d = e.inputBuffer.getChannelData(0);
      for (let i = 0; i < d.length; i++) raw.push(d[i]);
    };
    src.connect(processor);
    processor.connect(ctx.destination);
  }

  function stop(): Promise<string> {
    return new Promise((resolve) => {
      try {
        processor?.disconnect();
        src?.disconnect();
        stream?.getTracks().forEach((t) => t.stop());
        ctx?.close();
      } catch {}
      const int16 = new Int16Array(raw.length);
      for (let i = 0; i < raw.length; i++) int16[i] = Math.max(-32768, Math.min(32767, raw[i] * 32767));
      const wav = encodeWav(int16, 16000);
      const reader = new FileReader();
      reader.onload = () => resolve((reader.result as string).split(",")[1] || "");
      reader.readAsDataURL(wav);
    });
  }

  return { start, stop };
}

export function playAudioBase64(b64: string): Promise<void> {
  return new Promise((resolve) => {
    const audio = new Audio(`data:audio/mp3;base64,${b64}`);
    audio.play().then(() => resolve()).catch(() => resolve());
  });
}
