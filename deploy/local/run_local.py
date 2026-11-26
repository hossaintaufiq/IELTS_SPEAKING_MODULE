"""Run the speaking service on this PC, for local testing with the ieltsup apps.

    .venv/Scripts/python.exe deploy/local/run_local.py voice     real voice on the CPU: Whisper base.en + Kokoro, bank questions
    .venv/Scripts/python.exe deploy/local/run_local.py mock      no models: the examiner "speaks" beeps, to test screens and messages

Listens on http://localhost:8080 (public: /v1, /health) and http://localhost:8081 (internal: test bench, monitor, logs).
Keys are created once in deploy/local/.env (never committed). Put SERVICE_API_KEYS from there into ieltsup's
services/examCoreAPI/.env as LOCAL_AI_API_KEY.

This is for trying the flow, not for measuring quality or speed: that needs the GPU box (deploy/vast/RUNBOOK.md).
Without a language model the examiner asks questions from the question bank instead of building them on the answers. To use one,
set LLM_BASE_URL (an OpenAI-compatible address) and LLM_MODEL before starting.
"""
from __future__ import annotations

import os
import runpy
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEYS = Path(__file__).resolve().parent / ".env"
NAMES = ("SERVICE_API_KEYS", "MONITOR_KEY", "TOKEN_SECRET")


def load_keys() -> dict[str, str]:
    """The keys from deploy/local/.env, creating any that are missing."""
    found: dict[str, str] = {}
    if KEYS.exists():
        for line in KEYS.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name in NAMES:
                found[name] = value.strip()
    missing = [n for n in NAMES if not found.get(n)]
    if missing:
        found.update({n: secrets.token_urlsafe(32) for n in missing})
        KEYS.write_text("".join(f"{n}={found[n]}\n" for n in NAMES), encoding="utf-8")
        print(f"created {', '.join(missing)} in {KEYS}")
    return found


def voice_settings() -> dict[str, str]:
    models = ROOT / ".model-cache"
    kokoro, voices = models / "kokoro-v1.0.int8.onnx", models / "voices-v1.0.bin"
    for path in (kokoro, voices):
        if not path.exists():
            raise SystemExit(f"missing {path}: download the Kokoro model files first (see deploy/vast/setup_instance.sh)")
    return {
        "WHISPER_DEVICE": "cpu", "WHISPER_COMPUTE": "int8", "WHISPER_MODEL": "base.en",
        "CAPTIONS": "off",                                        # live captions cost a second model
        "KOKORO_MODEL": str(kokoro), "KOKORO_VOICES": str(voices),
        "LLM_BASE_URL": "http://127.0.0.1:1/v1",                  # nothing listens here: the examiner uses the question bank at once
        "SLOW_P95_S": "300",                                      # a CPU is slow: do not refuse the next test because of it
    }


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "voice"
    if mode not in ("voice", "mock"):
        raise SystemExit("usage: run_local.py [voice|mock]")
    os.environ.update(load_keys())
    settings = {"ALLOWED_ORIGINS": "http://localhost:3000", "HOST": "127.0.0.1", "PORT": "8080", "INTERNAL_PORT": "8081", "MAX_SESSIONS": "1"}
    if mode == "mock":
        os.environ["MOCK"] = "1"
    else:
        os.environ.pop("MOCK", None)
        settings.update(voice_settings())
    for name, value in settings.items():
        os.environ.setdefault(name, value)                        # anything already set in the shell wins
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    sys.argv = ["worker.server"]
    print(f"speaking service, {mode} mode: http://localhost:{os.environ['PORT']}/health (ready may take a minute)", flush=True)
    runpy.run_module("worker.server", run_name="__main__")


if __name__ == "__main__":
    main()
