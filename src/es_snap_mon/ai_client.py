"""Tiny client for an OpenAI-compatible chat completion endpoint.

Defaults target GitHub Models (https://models.github.ai), which exposes
Copilot-class models (gpt-5, gpt-4o, etc.) for free with a GitHub PAT.
Any OpenAI-compatible endpoint works (Azure OpenAI, openai.com, Ollama, …).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import keyring
import requests

from .config_manager import _APP_NAME, _config_dir

_AI_KEY = "es_snap_mon_ai_token"
_SETTINGS_FILE = "ai_settings.json"

DEFAULT_BASE_URL = "https://models.github.ai/inference"
DEFAULT_MODEL = "openai/gpt-4o"


@dataclass
class AISettings:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL


def _settings_path():
    return _config_dir() / _SETTINGS_FILE


def load_ai_settings() -> AISettings:
    p = _settings_path()
    if not p.exists():
        return AISettings()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return AISettings(
            base_url=data.get("base_url") or DEFAULT_BASE_URL,
            model=data.get("model") or DEFAULT_MODEL,
        )
    except (json.JSONDecodeError, OSError):
        return AISettings()


def save_ai_settings(settings: AISettings) -> None:
    _settings_path().write_text(
        json.dumps({"base_url": settings.base_url, "model": settings.model}, indent=2),
        encoding="utf-8",
    )


def get_ai_token() -> Optional[str]:
    try:
        return keyring.get_password(_APP_NAME, _AI_KEY)
    except Exception:
        return None


def set_ai_token(token: str) -> None:
    keyring.set_password(_APP_NAME, _AI_KEY, token)


def analyze(prompt: str, system: str = "", timeout: int = 60) -> str:
    """Send a chat completion request and return the assistant's text."""
    settings = load_ai_settings()
    token = get_ai_token()
    if not token:
        raise RuntimeError(
            "No API token configured. Open AI Settings and paste a GitHub PAT "
            "(scope: models:read) or any OpenAI-compatible API key."
        )

    url = settings.base_url.rstrip("/") + "/chat/completions"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": settings.model,
        "messages": messages,
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        # Try to surface a useful error
        try:
            err = resp.json()
            msg = err.get("error", {}).get("message") or err.get("message") or resp.text
        except Exception:
            msg = resp.text
        raise RuntimeError(f"HTTP {resp.status_code}: {msg[:400]}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected response shape: {data!r}") from e
