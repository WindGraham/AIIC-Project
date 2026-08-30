"""Lazy-read settings. No key => build/run still works (offline/mock-first).
Real provider stack (see docs/API使用手册.md):
  LLM (DeepSeek, OpenAI-compatible) · vision/low-latency voice LLM (aixhan Gemini :generateContent)
  STT (Volcengine bigmodel) · TTS (MiniMax).

Env vars are mapped case-insensitively by pydantic-settings from field names."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at apps/agent/.env; anchor to this module so config is CWD-independent.
_ENV_FILE = str(Path(__file__).resolve().parents[2] / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"

    # --- LLM (DeepSeek, OpenAI-compatible) ---
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    # --- Vision / multimodal (aixhan Gemini-compatible, MUST use :generateContent) ---
    gemini_api_key: str = ""
    gemini_base_url: str = "https://api.aixhan.com/v1beta"
    gemini_model: str = "gemini-3.5-flash"

    # --- Vision (Kimi Code K2.7, OpenAI-compatible image_url) 屏幕读屏 ---
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.kimi.com/coding/v1"
    kimi_model: str = "kimi-for-coding"

    # --- STT (Volcengine bigmodel) ---
    volcengine_api_key: str = ""
    volcengine_asr_resource_id: str = "volc.seedasr.sauc.duration"  # streaming
    volcengine_asr_ws: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
    # one-shot flash resource id (used for batch / post transcript fallback)
    volcengine_asr_flash_resource_id: str = "volc.bigasr.auc_turbo"

    # --- TTS (MiniMax) ---
    minimax_api_key: str = ""
    minimax_tts_model: str = "speech-01"
    minimax_tts_voice: str = "male-qn-qingse"

    # --- LiveKit (self-hosted; reuse /data/livekit) ---
    livekit_url: str = "ws://127.0.0.1:7880"  # internal, server-side REST/WS
    livekit_public_url: str = "wss://voice.windgraham.art"  # browser-reachable
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    agent_name: str = "interviewer"

    # --- Info search ---
    tavily_api_key: str = ""
    xhs_cookie: str = ""
    zhihu_d_cookie: str = ""

    # --- Runtime data directory (must NOT be on / — relocate to a data disk).
    # SQLite store (users/sessions/resumes/bookings), recordings & caches live here.
    data_dir: str = "/data/probedesk"


@lru_cache
def get_settings() -> Settings:
    return Settings()
