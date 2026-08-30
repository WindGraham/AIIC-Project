"""TTS — MiniMax text_to_speech -> MP3 bytes. (docs/API使用手册.md)"""

import httpx

from .config import get_settings


def synthesize(text: str, voice: str | None = None) -> bytes:
    s = get_settings()
    if not s.minimax_api_key:
        raise RuntimeError("MINIMAX_API_KEY not configured")
    payload = {"model": s.minimax_tts_model, "text": text, "voice_id": voice or s.minimax_tts_voice}
    r = httpx.post(
        "https://api.minimax.chat/v1/text_to_speech",
        json=payload,
        headers={"Authorization": f"Bearer {s.minimax_api_key}", "Content-Type": "application/json"},
        timeout=60,
    )
    r.raise_for_status()
    return r.content  # MP3 bytes
