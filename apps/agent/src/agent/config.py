"""Lazy-read settings. No key => build/run still works (offline/mock-first).
Mirrors DeepInterview's core/config.py philosophy: provider selection defaults
to mock/offline and is env-overridable."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"

    # --- LLM (OpenAI-compatible) ---
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    # Vision / multimodal (for AI reading the shared screen) + low-latency voice LLM
    gemini_api_key: str = ""
    llm_vision_model: str = ""

    # --- STT / TTS ---
    deepgram_api_key: str = ""
    stt_model: str = "nova-2"  # zh-verified; smoke-test nova-3 first
    elevenlabs_api_key: str = ""
    cartesia_api_key: str = ""
    tts_model: str = "eleven_flash_v2_5"

    # --- LiveKit (self-hosted; reuse /data/livekit) ---
    livekit_url: str = "ws://127.0.0.1:7880"
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    agent_name: str = "interviewer"

    # --- Info search ---
    tavily_api_key: str = ""
    xhs_cookie: str = ""
    zhihu_d_cookie: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
