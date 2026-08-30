"""STT — Volcengine bigmodel.

Entry points:
- `transcribe_flash(audio_b64, fmt)`: one-shot HTTP (works for WAV/MP3 base64).
- `transcribe_audio(audio_b64, mime)`: auto-choose format, one-shot HTTP.
- `stream_asr(bytes_iter, fmt="pcm", ...)`: TRUE streaming — async generator that
  yields partial `(text, is_final)` tuples as audio streams in and the server
  emits ASRResponse(451) partials. Audio send and response receive run
  concurrently, so partials appear while audio is still being sent (full-duplex
  phone-like voice turn).
- `stream_asr_full(audio: bytes, fmt="pcm", ...) -> str`: cumulative variant —
  sends the whole buffer in fixed-size TaskRequest(200) frames and returns the
  final joined transcript.

Streaming protocol (docs/API使用手册.md §3, verified against the real key):
  WS  wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async
  headers: X-Api-Key / X-Api-Resource-Id / X-Api-Request-Id / X-Api-Sequence:-1
  frame: header[4]=[0x11, msg_type|0x04, serial|0x00, 0]
         + event(4 BE) + sid_len(4 BE) + sid + payload_len(4 BE) + payload
  events: StartSession=100, TaskRequest=200 (audio), FinishSession=102 (client)
          SessionStarted=150, ASRResponse=451 (partial),
          SessionFinished=152 (final w/ punctuation), ASREnded=459 (server)
  audio: pcm = 16kHz int16 mono, 20ms packet = 640 bytes; mp3/ogg/... supported.
  pacing: pcm chunks are paced to real-time (640B=20ms) — required, the server
          closes sessions fed much faster than real-time; live feeds add no delay.
  finish: FinishSession payload must be valid JSON (b"{}") or the server errors.
"""

import asyncio
import base64
import json
import struct
import time as _time
import uuid
from collections.abc import AsyncIterator, Iterable

import httpx
import websockets

from .config import get_settings

_FLASH_ENDPOINT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"

# --- streaming protocol constants (see docs/API使用手册.md §3) ---
_EVENT_START = 100            # StartSession (client)
_EVENT_TASK = 200             # TaskRequest: audio chunk (client)
_EVENT_FINISH = 102           # FinishSession (client); payload MUST be JSON, e.g. b"{}"
_EVENT_SESSION_STARTED = 150  # -> dialog_id (server)
_EVENT_ASR_RESPONSE = 451     # partial result (server)
_EVENT_SESSION_FINISHED = 152  # final result w/ punctuation (server, observed in tests)
_EVENT_ASR_ENDED = 459        # utterance finished (server)

# PCM: 16kHz int16 mono, 20ms = 640 bytes per packet.
_PCM_CHUNK = 640
# Compressed formats: larger stable frames (doc: 8KB packets tested stable).
_COMPRESSED_CHUNK = 8000

_MAX_FRAME = 20 * 1024 * 1024  # server can return large final results


# --------------------------------------------------------------------------
# frame building / parsing
# --------------------------------------------------------------------------

def build_frame(event: int, payload: bytes, sid: str,
                msg_type: int = 0x10, serial: int = 0x10) -> bytes:
    """Build a Volcengine sauc binary frame (doc-derived, verified).

    msg_type 0x10 = text event (StartSession/FinishSession),
             0x20 = audio event (TaskRequest).
    serial   0x10 = JSON serialization, 0x00 = RAW binary audio.
    """
    body = struct.pack(">I", event) + struct.pack(">I", len(sid)) + sid.encode()
    body += struct.pack(">I", len(payload)) + payload
    return bytes([0x11, msg_type | 0x04, serial | 0x00, 0]) + body


def _parse_frame(data: bytes) -> tuple[int | None, str | None, str | None]:
    """Parse one inbound WS frame -> (event, text, error).

    Event is read from the binary header (robust); text is read from the JSON
    payload by scanning for `b'{"'` and parsing the tail (same trick as the doc).
    Text candidates, in order: result.utterances[].text (joined, partials),
    result.text, top-level text. A top-level "error" string is surfaced too.
    """
    event: int | None = None
    if len(data) >= 8:
        event = struct.unpack(">I", data[4:8])[0]
    text: str | None = None
    error: str | None = None
    j = None
    for skip in range(0, min(64, len(data))):
        if data[skip:skip + 2] == b'{"':
            try:
                j = json.loads(data[skip:].decode(errors="replace"))
                break
            except Exception:
                continue
    if isinstance(j, dict):
        err = j.get("error")
        if isinstance(err, str) and err:
            error = err
        res = j.get("result")
        if isinstance(res, dict):
            utts = res.get("utterances")
            if isinstance(utts, list):
                parts = [
                    u.get("text", "")
                    for u in utts
                    if isinstance(u, dict) and u.get("text")
                ]
                if parts:
                    text = "".join(parts)
            elif res.get("text"):
                text = str(res["text"])
        elif j.get("text"):
            text = str(j["text"])
    return event, text, error


# --------------------------------------------------------------------------
# true incremental streaming
# --------------------------------------------------------------------------

async def stream_asr(
    bytes_iter: Iterable[bytes] | AsyncIterator[bytes],
    fmt: str = "pcm",
    chunk_size: int | None = None,
    timeout: float = 20.0,
) -> AsyncIterator[tuple[str, bool]]:
    """TRUE incremental streaming STT over the Volcengine sauc WebSocket.

    Sends audio chunks as TaskRequest(200) frames in a background task while a
    reader loop consumes server frames, so partial `(text, is_final)` tuples are
    yielded as the server emits them — before all audio has been sent. A final
    `(text, True)` is guaranteed: from the server's final result (SessionFinished
    152 / ASREnded 459), else the last accumulated hypothesis on timeout / close.

    Args:
        bytes_iter: sync or async iterable of audio byte chunks (e.g. 640-byte
            PCM mic packets, or larger chunks for compressed formats).
        fmt: format in the StartSession payload — "pcm" (16k int16 mono),
            "mp3", "ogg", "wav", "m4a", "aac", "spx", "amr".
        chunk_size: TaskRequest frame size. Default 640 for pcm, 8000 otherwise.
        timeout: seconds to keep waiting for final results after the last audio
            chunk was sent; on expiry the accumulated text is emitted as final.

    Yields:
        (text, is_final): text is the current cumulative hypothesis; the last
        tuple has is_final=True.
    """
    s = get_settings()
    if not s.volcengine_api_key:
        raise RuntimeError("VOLCENGINE_API_KEY not configured")
    ws_url = s.volcengine_asr_ws
    if not ws_url:
        raise RuntimeError("VOLCENGINE_ASR_WS not configured")

    sid = str(uuid.uuid4())
    if chunk_size is None:
        chunk_size = _PCM_CHUNK if fmt == "pcm" else _COMPRESSED_CHUNK
    start_payload = json.dumps({
        "audio": {"format": fmt, "rate": 16000, "channel": 1},
        "request": {
            "model_name": "bigmodel",
            "enable_punc": True,
            "enable_itn": True,
            "show_utterances": True,
        },
    }).encode()
    headers = {
        "X-Api-Key": s.volcengine_api_key,
        "X-Api-Resource-Id": s.volcengine_asr_resource_id,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Sequence": "-1",
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }

    async with websockets.connect(
        ws_url, additional_headers=headers, max_size=_MAX_FRAME
    ) as ws:
        await ws.send(build_frame(_EVENT_START, start_payload, sid))

        async def _send_audio() -> None:
            """Stream chunks as TaskRequest(200) frames, then FinishSession(102).

            Volcengine closes the session if audio arrives much faster than
            real-time, so pcm chunks are paced to their real-time duration
            (640B = 20ms): a live mic feed at real-time rate adds no latency,
            while a bulk buffer is throttled. Compressed formats get the
            doc-verified 50ms inter-chunk spacing.
            """
            t0 = _time.monotonic()
            sent_bytes = 0

            async def _emit(chunk: bytes) -> None:
                nonlocal sent_bytes
                await ws.send(build_frame(_EVENT_TASK, chunk, sid,
                                          msg_type=0x20, serial=0x00))
                sent_bytes += len(chunk)
                if fmt == "pcm":
                    # 16kHz x int16 mono => 32000 bytes per second of audio
                    expect = sent_bytes / 32000.0
                    elapsed = _time.monotonic() - t0
                    if elapsed < expect:
                        await asyncio.sleep(expect - elapsed)
                else:
                    await asyncio.sleep(0.05)

            if hasattr(bytes_iter, "__aiter__"):
                async for chunk in bytes_iter:
                    if chunk:
                        await _emit(chunk)
            else:
                for chunk in bytes_iter:
                    if chunk:
                        await _emit(chunk)
            await ws.send(build_frame(_EVENT_FINISH, b"{}", sid))  # must be JSON

        send_task = asyncio.create_task(_send_audio())
        final_yielded = False
        last_text = ""
        try:
            while True:
                # surface send-side failures promptly (e.g. server closed early)
                if send_task.done():
                    send_task.result()  # raises if the sender failed
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                except websockets.ConnectionClosed:
                    break  # server closed; emit whatever we accumulated
                event, text, error = _parse_frame(raw)
                if error:
                    raise RuntimeError(f"Volcengine ASR server error: {error}")
                if text:
                    last_text = text
                if event in (_EVENT_ASR_ENDED, _EVENT_SESSION_FINISHED):
                    final_yielded = True
                    yield last_text, True
                    break
                if event == _EVENT_SESSION_STARTED:
                    continue  # session ack, nothing to yield
                if text:
                    yield text, False
            if not final_yielded and last_text:
                # timeout / early close fallback: accumulated hypothesis = final
                yield last_text, True
        finally:
            send_task.cancel()
            try:
                await send_task
            except (asyncio.CancelledError, Exception):
                pass


# --------------------------------------------------------------------------
# cumulative streaming (whole buffer -> final text)
# --------------------------------------------------------------------------

def _chunk_bytes(data: bytes, size: int):
    for i in range(0, len(data), size):
        yield data[i:i + size]


async def stream_asr_full(
    audio: bytes,
    fmt: str = "pcm",
    chunk_size: int | None = None,
    timeout: float = 20.0,
) -> str:
    """Cumulative streaming STT: send the whole buffer, return the final text.

    The buffer is sent as fixed-size TaskRequest frames (640 bytes for pcm,
    8000 otherwise) exactly like the verified protocol walk-through. Returns the
    final cumulative hypothesis (partials grow monotonically, so the last one —
    the ASREnded text when present — is the transcript). Empty string if nothing
    was recognized.

    Args:
        audio: full audio bytes (pcm = 16k int16 mono; or mp3/ogg/... bytes).
        fmt / chunk_size / timeout: see `stream_asr`.
    """
    if chunk_size is None:
        chunk_size = _PCM_CHUNK if fmt == "pcm" else _COMPRESSED_CHUNK
    texts: list[str] = []
    async for text, _is_final in stream_asr(
        _chunk_bytes(audio, chunk_size), fmt=fmt, timeout=timeout
    ):
        texts.append(text)
    return texts[-1] if texts else ""


# --------------------------------------------------------------------------
# one-shot HTTP (unchanged behavior)
# --------------------------------------------------------------------------

def transcribe_flash(audio_b64: str, fmt: str = "wav") -> str:
    s = get_settings()
    if not s.volcengine_api_key:
        raise RuntimeError("VOLCENGINE_API_KEY not configured")
    payload = {"audio": {"data": audio_b64, "format": fmt}, "request": {"model_name": "bigmodel"}}
    headers = {
        "x-api-key": s.volcengine_api_key,
        "X-Api-Resource-Id": s.volcengine_asr_flash_resource_id,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    r = httpx.post(_FLASH_ENDPOINT, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    j = r.json()
    result = j.get("result", {}) if isinstance(j.get("result"), dict) else {}
    return str(result.get("text", "") or "")


def transcribe_audio(audio_b64: str, mime: str | None = None) -> str:
    """Auto-choose format from mime (often the browser sends webm/opus — try mp3/wav)."""
    fmt = "wav"
    if mime and "mp3" in mime:
        fmt = "mp3"
    elif mime and ("wav" in mime or "pcm" in mime or "x-wav" in mime):
        fmt = "wav"
    elif mime and ("mp4" in mime or "aac" in mime):
        fmt = "mp4"
    try:
        return transcribe_flash(audio_b64, fmt)
    except Exception:
        # fallback: some endpoints accept wav even for webm-ish bytes; refuse silently
        raise
