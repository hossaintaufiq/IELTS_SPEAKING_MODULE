"""Ask the local LLM (vLLM, OpenAI-compatible) for one JSON reply. No external API is ever called."""
from __future__ import annotations

import json
import os

import httpx

BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ")


async def generate_json(system: str, prompt: str, timeout: float = 10.0) -> dict | None:
    """Return the parsed JSON object, or None on any failure (the caller falls back to the bank)."""
    body = {
        "model": MODEL,
        "temperature": 0.6,
        "max_tokens": 220,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{BASE_URL}/chat/completions", json=body)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None
