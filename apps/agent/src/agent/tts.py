"""TTS — MiniMax text_to_speech -> MP3 bytes. (docs/API使用手册.md)

Three entry points:
- `synthesize(text, voice)`: one-shot, returns the full MP3 bytes (legacy callers).
- `synthesize_stream(text, voice)`: sync generator yielding MP3 chunks as they
  arrive (MiniMax `stream=True` returns ~1KB chunks under an ID3 header).
- `synthesize_stream_async(text, voice)`: async generator over the same stream
  (properly cancellable — used by the full-duplex voice WebSocket).
"""

import httpx

from .config import get_settings

_TTS_ENDPOINT = "https://api.minimax.chat/v1/text_to_speech"


def _payload(text: str, voice: str | None, *, stream: bool) -> dict:
    s = get_settings()
    if not s.minimax_api_key:
        raise RuntimeError("MINIMAX_API_KEY not configured")
    return {
        "model": s.minimax_tts_model,
        "text": text,
        "voice_id": voice or s.minimax_tts_voice,
        "stream": stream,
    }


def _headers() -> dict:
    s = get_settings()
    return {"Authorization": f"Bearer {s.minimax_api_key}", "Content-Type": "application/json"}


def synthesize(text: str, voice: str | None = None) -> bytes:
    r = httpx.post(
        _TTS_ENDPOINT,
        json=_payload(text, voice, stream=False),
        headers=_headers(),
        timeout=60,
    )
    r.raise_for_status()
    return r.content  # MP3 bytes


def synthesize_stream(text: str, voice: str | None = None):
    """Yield MP3 chunks as MiniMax streams them (sync generator).

    Same endpoint as `synthesize` but with `stream=True`; the response is
    `audio/mpeg` and `iter_bytes()` yields ~1024-byte chunks (ID3 first).
    """
    with httpx.stream(
        "POST",
        _TTS_ENDPOINT,
        json=_payload(text, voice, stream=True),
        headers=_headers(),
        timeout=30,
    ) as r:
        r.raise_for_status()
        for chunk in r.iter_bytes():
            if chunk:
                yield chunk


async def synthesize_stream_async(text: str, voice: str | None = None):
    """Async generator over the MiniMax streaming TTS response.

    Cancellable from the event loop (used for barge-in on the voice WS).
    """
    async with httpx.AsyncClient(timeout=30) as client:
        async with client.stream(
            "POST",
            _TTS_ENDPOINT,
            json=_payload(text, voice, stream=True),
            headers=_headers(),
        ) as r:
            r.raise_for_status()
            async for chunk in r.aiter_bytes():
                if chunk:
                    yield chunk
