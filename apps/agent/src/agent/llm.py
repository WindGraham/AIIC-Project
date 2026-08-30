"""Unified LLM client for the agent.

- `chat` / `chat_json`: DeepSeek (OpenAI-compatible). `response_format=json_object` for
  schema-constrained outputs.
- `vision`: aixhan Gemini-compatible `:generateContent` (MUST use that endpoint + /v1beta).

All methods raise on error; callers may wrap with a mock fallback. Uses `httpx`
(installed as an agent dep)."""

import json
from typing import Any

import httpx

from .config import get_settings


class LLM:
    def __init__(self) -> None:
        self.settings = get_settings()

    # ---- DeepSeek (OpenAI-compatible) ----
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = False,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        r = httpx.post(
            f"{self.settings.llm_base_url}/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def chat_json(self, messages: list[dict[str, Any]], *, max_tokens: int = 2048) -> dict[str, Any]:
        txt = self.chat(messages, json_mode=True, max_tokens=max_tokens)
        return json.loads(txt)

    # ---- Gemini vision (aixhan) ----
    def vision(self, prompt: str, image_b64: str, mime: str = "image/png", *, timeout: float = 60.0) -> str:
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime, "data": image_b64}},
                    ],
                }
            ]
        }
        r = httpx.post(
            f"{self.settings.gemini_base_url}/models/{self.settings.gemini_model}:generateContent",
            json=payload,
            headers={"Authorization": f"Bearer {self.settings.gemini_api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        r.raise_for_status()
        d = r.json()
        parts = d["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)

    # ---- Kimi Code K2.7 vision (OpenAI-compatible image_url) ------------------
    @staticmethod
    def _mime_b64(mime: str, image_b64: str) -> str:
        if image_b64.startswith("data:"):
            return image_b64
        return f"data:{mime};base64,{image_b64}"

    def vision_kimi(self, prompt: str, image_b64: str, mime: str = "image/jpeg", *,
                    timeout: float = 90.0) -> str:
        """One image -> text, via Kimi Code (OpenAI-compatible /chat/completions)."""
        content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": self._mime_b64(mime, image_b64)}}]
        payload = {"model": self.settings.kimi_model, "messages": [{"role": "user", "content": content}], "max_tokens": 512}
        r = httpx.post(
            f"{self.settings.kimi_base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self.settings.kimi_api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def vision_kimi_multi(self, prompt: str, images: list[tuple[str, str]], *,
                          timeout: float = 120.0) -> str:
        """Multiple images in ONE request (streaming context). images = [(b64, mime), ...]."""
        content: list[dict] = [{"type": "text", "text": prompt}]
        for b64, mime in images:
            content.append({"type": "image_url", "image_url": {"url": self._mime_b64(mime, b64)}})
        payload = {"model": self.settings.kimi_model, "messages": [{"role": "user", "content": content}], "max_tokens": 512}
        r = httpx.post(
            f"{self.settings.kimi_base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self.settings.kimi_api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
