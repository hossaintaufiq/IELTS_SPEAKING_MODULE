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
import re
import struct
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from worker import session as sess
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
                from worker.examiner.llm import generate_json        # the first request to vLLM is the slowest one
                asyncio.run(generate_json("Reply as JSON.", 'Reply with {"ok": true}.', timeout=60))
            except Exception:
                log.exception("model preload failed; sessions will load models on demand")

        threading.Thread(target=work, daemon=True).start()


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


LIVE: dict = {"session": None}           # the newest test (in progress or the last one): what the logs window shows by default
SESSIONS: dict[str, ExamSession] = {}    # every connected test, by id: several devices can take a test at the same time
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "6"))   # one GPU serves only so many tests at once; the next device is told to wait


@app.get("/logs")
def logs_page():
    return FileResponse(WEB / "logs.html")


@app.get("/api/live")
def live_run(id: str = ""):
    """Events of one test (default: the newest), for the logs window's live view, and the list of all connected tests."""
    listing = [{"id": k, "device": v.device, "phase": v.phase, "started": v.started, "active": v.started and v.phase != "done"}
               for k, v in SESSIONS.items()]
    if id == "all":                                   # every connected device in one timeline, oldest first
        merged = [{**e, "dev": v.device or k[:4]} for k, v in SESSIONS.items() for e in v.log]
        merged.sort(key=lambda e: e.get("at", 0))
        return {"active": any(x["active"] for x in listing), "started": bool(listing), "phase": "", "events": merged, "sessions": listing}
    s = SESSIONS.get(id) if id else LIVE["session"]
    if s is None:
        return {"active": False, "started": False, "events": [], "sessions": listing}
    return {"active": s.started and s.phase != "done", "started": s.started, "phase": s.phase, "device": s.device,
            "events": list(s.log), "sessions": listing}


RUN_NAME = re.compile(r"^run_\d{8}_\d{6}(?:_\d{1,8})?$")


@app.get("/api/runs")
def list_runs():
    """Saved test runs, newest first (the page's Run log can open any of them)."""
    files = sorted(sess.RUNS.glob("run_*.json"), reverse=True)[:40] if sess.RUNS.exists() else []
    def device(f: Path) -> str:
        try:
            return json.loads(f.read_text(encoding="utf-8")).get("device", "")
        except Exception:
            return ""
    return [{"name": f.stem, "kb": round(f.stat().st_size / 1024), "saved": f.stat().st_mtime, "device": device(f)} for f in files]


@app.get("/api/runs/{name}")
def get_run(name: str):
    if not RUN_NAME.match(name):                  # the name becomes a file name: nothing else is accepted
        raise HTTPException(404, "no such run")
    path = sess.RUNS / f"{name}.json"
    if not path.exists():
        raise HTTPException(404, "no such run")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


LOG_DIR = Path(os.getenv("LOG_DIR", "/root/work"))          # where setup_instance.sh writes web.log, vllm.log, setup.log
LOG_NAMES = {"web": "web.log", "vllm": "vllm.log", "setup": "setup.log"}
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@app.get("/api/serverlog/{name}")
def server_log(name: str, lines: int = 300, q: str = "", hide_debug: bool = True):
    """The tail of a server log (web = this server, vllm = the LLM, setup = installation), for the page's Server log tab."""
    if name not in LOG_NAMES:
        raise HTTPException(404, "no such log")
    path = LOG_DIR / LOG_NAMES[name]
    if not path.exists():
        return {"name": name, "path": str(path), "exists": False, "lines": []}
    with open(path, "rb") as f:                              # only the end of the file: logs grow large
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 600_000))
        text = f.read().decode("utf-8", "replace")
    rows = [ANSI.sub("", r) for r in text.splitlines()]
    if hide_debug:
        rows = [r for r in rows if "| DEBUG" not in r and "DEBUG:" not in r]
    if q:
        rows = [r for r in rows if q.lower() in r.lower()]
    return {"name": name, "path": str(path), "exists": True, "lines": rows[-max(10, min(lines, 2000)):]}


@app.get("/health")
def health():
    return {"ok": True, "mock": MOCK, "tests_running": sum(1 for v in SESSIONS.values() if v.phase != "done"), "max_tests": MAX_SESSIONS}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    running = sum(1 for v in SESSIONS.values() if v.phase != "done")
    if running >= MAX_SESSIONS:
        # the GPU is shared: a test that cannot get its share would stutter for everyone, so it waits instead
        await websocket.close(code=1013, reason=f"Server is full ({running} tests running). Please try again in a minute.")
        return
    session = ExamSession(send=websocket.send_json)
    session.device = (websocket.query_params.get("device") or "")[:40]     # optional label: open the page with ?device=Laptop
    LIVE["session"] = session
    SESSIONS[session.test_id] = session
    try:
        if MOCK:
            await run_mock(websocket, session)
        else:
            await run_real(websocket, session)
    except WebSocketDisconnect:
        pass
    finally:
        SESSIONS.pop(session.test_id, None)
        path = session.abort() if session.started else None
        if path:
            log.info("saved run log %s", path)


async def run_real(websocket: WebSocket, session: ExamSession):
    from pipecat.pipeline.runner import PipelineRunner

    from worker.pipeline import WorkerConfig, build_task

    session.await_audio = True          # end the test only after the examiner's goodbye has been spoken
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
