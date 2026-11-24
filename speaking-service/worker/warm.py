"""Load the heavy models once, at server start, and share them between sessions.

Without this every new test reloads Whisper and Kokoro (about 10 s before the examiner speaks).
`install()` wraps the model constructors in a cache, so Pipecat's services and our caption tap get
the already-loaded instance. `preload()` builds them once so the first session is fast too.

Shared instances are used by one test at a time in this test bench. Before serving several
students at once, check thread-safety and per-model concurrency (open item in docs/PROGRESS.md).
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("speaking.warm")
_installed = False


def _cached(cls):
    cache: dict = {}

    def factory(*args, **kwargs):
        key = (args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = cls(*args, **kwargs)
        return cache[key]

    factory.__wrapped__ = cls
    return factory


def install() -> None:
    """Must run before pipecat's kokoro service module is imported."""
    global _installed
    if _installed:
        return
    import faster_whisper
    import kokoro_onnx

    faster_whisper.WhisperModel = _cached(faster_whisper.WhisperModel)
    kokoro_onnx.Kokoro = _cached(kokoro_onnx.Kokoro)
    _installed = True


def preload() -> None:
    """Build every model once (blocking). Run in a thread at startup."""
    from faster_whisper import WhisperModel
    from kokoro_onnx import Kokoro

    device = os.getenv("WHISPER_DEVICE", "cuda")
    compute = os.getenv("WHISPER_COMPUTE", "float16")
    from worker import caption_budget
    names = {os.getenv("WHISPER_MODEL", "large-v3-turbo")}
    if caption_budget.enabled():                       # CAPTIONS=off: the small caption model is never needed, so it is not loaded
        names.add(os.getenv("CAPTION_MODEL", "small.en"))
    for name in sorted(names):
        WhisperModel(name, device=device, compute_type=compute)
        log.info("preloaded whisper %s", name)
    # Same arguments the Pipecat service passes, so it hits the cache.
    from pathlib import Path
    Kokoro(str(Path(os.getenv("KOKORO_MODEL", "models/cache/kokoro-v1.0.onnx"))),
           str(Path(os.getenv("KOKORO_VOICES", "models/cache/voices-v1.0.bin"))))
    log.info("preloaded kokoro")
    import pipecat.services.kokoro.tts  # noqa: F401  (import cost paid now, not on the first Start)
    import pipecat.services.whisper.stt  # noqa: F401
    log.info("models ready")
