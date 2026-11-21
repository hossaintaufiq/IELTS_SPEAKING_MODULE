"""Test server: serves the web UI and runs one live speaking test per WebSocket.

    python -m worker.server            # real pipeline (needs the GPU box: whisper, kokoro, vLLM)
    MOCK=1 python -m worker.server     # no models: fake examiner, to test the UI and protocol

Open http://localhost:8080 (on the GPU box use an SSH port forward, see deploy/vast/RUNBOOK.md).
This is a quality-testing tool, not the production API: no auth, one test per connection.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import struct
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from worker.session import ExamSession

log = logging.getLogger("speaking.server")
WEB = Path(__file__).resolve().parent.parent / "web"
MOCK = os.getenv("MOCK") == "1"


app = FastAPI(title="Speaking test bench")

if not MOCK:
    from worker import warm

    try:
        warm.install()      # share one loaded Whisper/Kokoro between sessions (must precede pipecat's kokoro import)
    except Exception:       # e.g. a dev PC without the model libraries: the cache is best-effort
        log.warning("model cache not installed; sessions will load models themselves")

    @app.on_event("startup")
    async def _preload_models():
        import asyncio
        import threading

        def work():
            try:
                warm.preload()
            except Exception:
                log.exception("model preload failed; sessions will load models on demand")

        threading.Thread(target=work, daemon=True).start()


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "mock": MOCK}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    session = ExamSession(send=websocket.send_json)
    try:
        if MOCK:
            await run_mock(websocket, session)
        else:
            await run_real(websocket, session)
    except WebSocketDisconnect:
        pass
    finally:
        path = session.abort() if session.started else None
        if path:
            log.info("saved run log %s", path)


async def run_real(websocket: WebSocket, session: ExamSession):
    from pipecat.pipeline.runner import PipelineRunner

    from worker.pipeline import WorkerConfig, build_task

    task = build_task(websocket, WorkerConfig(), session)
    await PipelineRunner(handle_sigint=False).run(task)


async def run_mock(websocket: WebSocket, session: ExamSession):
    """No models: records control messages, answers each one with a beep, so the UI can be tested."""

    class FakeTask:
        async def queue_frames(self, frames):
            await websocket.send_bytes(beep())

    session.task = FakeTask()
    while True:
        msg = await websocket.receive()
        if msg.get("type") == "websocket.disconnect":
            return
        if msg.get("text"):
            await session.handle_control(json.loads(msg["text"]))
        elif msg.get("bytes"):
            session.note_audio(msg["bytes"])    # mic audio is counted but not transcribed in mock mode


def beep(ms: int = 300, hz: int = 660, rate: int = 24000) -> bytes:
    n = rate * ms // 1000
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * hz * i / rate))) for i in range(n))


app.mount("/static", StaticFiles(directory=WEB), name="static")

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8080")))
