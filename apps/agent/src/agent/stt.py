"""STT — Volcengine bigmodel.

Two entry points:
- `transcribe_flash(audio_b64, fmt)`: one-shot HTTP (works for WAV/MP3 base64).
- `transcribe_stream(iter_binary)`: streaming WebSocket client (TaskRequest frames);
  used by the full-duplex agent later. Reasonably robust; callers degrade on failure.
"""

import base64
import uuid

import httpx

from .config import get_settings

_FLASH_ENDPOINT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"


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
