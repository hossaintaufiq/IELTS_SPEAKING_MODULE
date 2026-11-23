"""Ask the local LLM (vLLM, OpenAI-compatible) for one JSON reply. No external API is ever called."""
from __future__ import annotations

import json
import os

import httpx

BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ")


last_error = ""        # why the most recent call returned None (shown in the run log next to a fallback question)


async def generate_json(system: str, prompt: str, timeout: float = 10.0) -> dict | None:
    """Return the parsed JSON object, or None on any failure (the caller falls back to the bank).

    A quick failure (bad JSON, an HTTP error) is retried once; a timeout is not, because the conversation cannot wait twice."""
    global last_error
    body = {
        "model": MODEL,
        "temperature": 0.6,
        "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "130")),
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(f"{BASE_URL}/chat/completions", json=body)
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
            data = json.loads(text)
            if isinstance(data, dict):
                last_error = ""
                return data
            last_error = "the reply was JSON but not an object"
        except httpx.TimeoutException:
            last_error = f"timed out after {timeout:g} s"
            return None
        except httpx.HTTPStatusError as e:
            last_error = f"HTTP {e.response.status_code}: {e.response.text[:120]}"
        except json.JSONDecodeError:
            last_error = f"the reply was not valid JSON (cut off at the token limit?): {text[-80:]!r}"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"[:160]
    return None
