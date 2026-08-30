"""Verify streaming STT against the REAL Volcengine key.

Steps:
1. Synthesize real Chinese speech -> MP3 via MiniMax TTS (real key from .env).
2. Decode MP3 -> 16kHz mono int16 PCM via miniaudio (proves the pcm path).
3. stream_asr_full(pcm, fmt="pcm")  — 640-byte TaskRequest frames.
4. stream_asr(pcm) incremental     — partials BEFORE final (full-duplex proof).
5. stream_asr_full(mp3, fmt="mp3") — native compressed-format path.
6. transcribe_flash(mp3 b64)       — one-shot regression (must stay working).

Run:  cd apps/agent && PYTHONPATH=src .venv/bin/python scripts/verify_stream_stt.py
Needs: miniaudio (only for MP3->PCM decoding in step 2; stt.py itself does not
       require it) — install with: uv pip install --python .venv/bin/python miniaudio
"""

import asyncio
import base64
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent import stt  # noqa: E402
from agent.config import get_settings  # noqa: E402

TEXT = "你好，欢迎参加面试。请简单介绍一下你自己。"
PCM_CHUNK = 640


def synth_mp3() -> bytes:
    s = get_settings()
    r = httpx.post(
        "https://api.minimax.chat/v1/text_to_speech",
        headers={"Authorization": f"Bearer {s.minimax_api_key}", "Content-Type": "application/json"},
        json={"model": s.minimax_tts_model, "text": TEXT, "voice_id": s.minimax_tts_voice},
        timeout=60,
    )
    r.raise_for_status()
    return r.content


def mp3_to_pcm16k16b_mono(mp3: bytes) -> bytes:
    import miniaudio

    dec = miniaudio.decode_file(
        Path("/tmp/_stt_verify.mp3"),
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=16000,
    )
    return dec.samples.tobytes()  # array('h') -> raw int16 LE PCM


async def main() -> int:
    failures = 0

    print("== 1) synth MP3 via MiniMax TTS ==")
    mp3 = synth_mp3()
    print(f"   mp3 bytes: {len(mp3)}")
    Path("/tmp/_stt_verify.mp3").write_bytes(mp3)

    pcm = mp3_to_pcm16k16b_mono(mp3)
    print(f"   pcm bytes (16k/16b/mono): {len(pcm)}  ({len(pcm)/32000:.2f}s)")

    print("\n== 2) stream_asr_full(pcm, fmt='pcm') — 640-byte frames ==")
    t0 = time.monotonic()
    full_pcm = await stt.stream_asr_full(pcm, fmt="pcm")
    dt = time.monotonic() - t0
    print(f"   [{dt:.1f}s] FULL PCM -> {full_pcm!r}")
    if not full_pcm.strip():
        print("   !! EMPTY"); failures += 1

    print("\n== 3) stream_asr(pcm) incremental — partials before final ==")
    partials: list[tuple[str, bool]] = []
    t0 = time.monotonic()
    async for text, is_final in stt.stream_asr(
        (pcm[i:i + PCM_CHUNK] for i in range(0, len(pcm), PCM_CHUNK)),
        fmt="pcm",
    ):
        partials.append((text, is_final))
        print(f"   [{'F' if is_final else 'p'}] {text!r}")
    dt = time.monotonic() - t0
    partial_only = [t for t, f in partials if not f]
    finals = [t for t, f in partials if f]
    print(f"   [{dt:.1f}s] {len(partials)} yields; {len(partial_only)} partials; {len(finals)} finals")
    if not partial_only:
        print("   !! NO PARTIALS emitted (streaming broken?)"); failures += 1
    if not finals:
        print("   !! NO FINAL emitted"); failures += 1

    print("\n== 4) stream_asr_full(mp3, fmt='mp3') — native compressed path ==")
    t0 = time.monotonic()
    full_mp3 = await stt.stream_asr_full(mp3, fmt="mp3")
    dt = time.monotonic() - t0
    print(f"   [{dt:.1f}s] FULL MP3 -> {full_mp3!r}")
    if not full_mp3.strip():
        print("   !! EMPTY"); failures += 1

    print("\n== 5) transcribe_flash(mp3 b64) — one-shot regression ==")
    flash = stt.transcribe_flash(base64.b64encode(mp3).decode(), "mp3")
    print(f"   FLASH -> {flash!r}")
    if not flash.strip():
        print("   !! EMPTY"); failures += 1

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} FAILURES'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
