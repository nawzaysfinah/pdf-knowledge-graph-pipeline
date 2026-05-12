"""Local Ollama client for offline LLM calls."""

from __future__ import annotations

from typing import Any

import requests


class OllamaClient:
    """Minimal Ollama API wrapper."""

    def __init__(self, base_url: str, model: str, timeout_seconds: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def health(self) -> bool:
        response = requests.get(f"{self.base_url}/api/tags", timeout=10)
        response.raise_for_status()
        return True

    def generate(
        self,
        prompt: str,
        *,
        json_mode: bool = False,
        temperature: float = 0.1,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"

        response = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return str(data.get("response", ""))
