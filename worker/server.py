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

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from worker import caption_budget
from worker import monitor as mon
from worker import service_api as svc
from worker import session as sess
from worker.session import ExamSession

log = logging.getLogger("speaking.server")
READY = {"done": False, "error": ""}      # the models have been loaded (the first minutes after a start); MOCK has none to load
mon.install_failure_log()                 # warnings and errors of the service, kept in memory for the monitoring page
WEB = Path(__file__).resolve().parent.parent / "web"
MOCK = os.getenv("MOCK") == "1"


app = FastAPI(title="Speaking test bench")


# ---- access code ---------------------------------------------------------------------------------------------
# A public link (Cloudflare Tunnel) must not be usable by whoever finds it: every test uses the shared GPU. Set ACCESS_CODE and open
# the page once as /?key=<code>; the browser then keeps a cookie, which the page, the logs and the microphone connection all carry.
# Not set (the default, and on a private SSH tunnel): no check at all.
ACCESS = {"code": os.getenv("ACCESS_CODE", "")}
COOKIE = "access"
MONITOR_PATHS = ("/api/live", "/api/runs", "/api/serverlog/")      # transcripts and logs: only with MONITOR_KEY, see _monitor_guard


def _code_from(scope) -> tuple[bool, bool]:
    """(allowed, came_from_the_link): the code in ?key= or in the cookie."""
    from urllib.parse import parse_qs
    import hmac

    want = ACCESS["code"]
    key = (parse_qs(scope.get("query_string", b"").decode("latin-1")).get("key") or [""])[0]
    if key and hmac.compare_digest(key, want):
        return True, True
    headers = dict(scope.get("headers") or [])
    for part in headers.get(b"cookie", b"").decode("latin-1").split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE and value and hmac.compare_digest(value, want):
            return True, False
    return False, False


class AccessCodeMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        # /v1 is the service API: the caller is a server, not a browser, and proves itself with its own API key (worker/service_api.py).
        # The monitoring page and the data behind it (/api/monitor, runs, live view, server log) have their own key (MONITOR_KEY).
        if (scope["type"] not in ("http", "websocket") or not ACCESS["code"] or path in ("/health", "/monitor", "/api/monitor")
                or path.startswith(MONITOR_PATHS) or path.startswith("/v1/")):
            return await self.inner(scope, receive, send)
        ok, from_link = _code_from(scope)
        if not ok:
            if scope["type"] == "websocket":
                await receive()                                  # the connect message
                return await send({"type": "websocket.close", "code": 1008, "reason": "Access code needed"})
            body = b"Access code needed. Open the link you were given (it ends in ?key=...)."
            await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain"), (b"content-length", str(len(body)).encode())]})
            return await send({"type": "http.response.body", "body": body})
        if scope["type"] == "http" and from_link:
            async def with_cookie(message):
                if message["type"] == "http.response.start":
                    message = {**message, "headers": [*message.get("headers", []),
                                                      (b"set-cookie", f"{COOKIE}={ACCESS['code']}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400".encode())]}
                await send(message)
            return await self.inner(scope, receive, with_cookie)
        return await self.inner(scope, receive, send)


app.add_middleware(AccessCodeMiddleware)

if not MOCK:
    from worker import warm

    try:
        warm.install()      # share one loaded Whisper/Kokoro between sessions (must precede pipecat's kokoro import)
    except Exception:       # e.g. a dev PC without the model libraries: the cache is best-effort
        log.warning("model cache not installed; sessions will load models themselves")

    @app.on_event("startup")
    async def _require_keys():
        # A real service without keys is either closed (no one can use it) or, worse, readable by anyone who finds the address.
        missing = [n for n, v in (("SERVICE_API_KEYS", svc.configured_keys()), ("MONITOR_KEY", os.getenv("MONITOR_KEY", ""))) if not v]
        if missing:
            raise RuntimeError(f"Refusing to start: set {' and '.join(missing)} (see README, Server settings). MOCK=1 needs none.")

    @app.on_event("startup")
    async def _preload_models():
        import asyncio
        import threading

        def work():
            try:
                warm.preload()
                from worker.examiner.llm import generate_json        # the first request to vLLM is the slowest one
                asyncio.run(generate_json("Reply as JSON.", 'Reply with {"ok": true}.', timeout=60))
            except Exception as e:
                log.exception("model preload failed; sessions will load models on demand")
                READY["error"] = f"{type(e).__name__}: {e}"[:200]
            finally:
                READY["done"] = True       # finished, one way or the other; is_ready() is false when it failed (the error shows in /health)

        threading.Thread(target=work, daemon=True).start()


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


LIVE: dict = {"session": None}           # the newest test (in progress or the last one): what the logs window shows by default
SESSIONS: dict[str, ExamSession] = {}    # every connected test, by id: several devices can take a test at the same time
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "6"))   # one GPU serves only so many tests at once; the next device is told to wait


@app.get("/logs")
def logs_page():
    return RedirectResponse("/monitor#runlog")      # the run log lives in the monitoring page


@app.get("/api/live")
def live_run(request: Request, id: str = ""):
    """Events of one test (default: the newest), for the logs window's live view, and the list of all connected tests."""
    if (denied := _monitor_guard(request)) is not None:
        return denied
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
def list_runs(request: Request):
    """Saved test runs, newest first (the page's Run log can open any of them)."""
    if (denied := _monitor_guard(request)) is not None:
        return denied
    files = sorted(sess.RUNS.glob("run_*.json"), reverse=True)[:40] if sess.RUNS.exists() else []
    def device(f: Path) -> str:
        try:
            return json.loads(f.read_text(encoding="utf-8")).get("device", "")
        except Exception:
            return ""
    return [{"name": f.stem, "kb": round(f.stat().st_size / 1024), "saved": f.stat().st_mtime, "device": device(f)} for f in files]


@app.get("/api/runs/{name}")
def get_run(name: str, request: Request):
    if (denied := _monitor_guard(request)) is not None:
        return denied
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
def server_log(request: Request, name: str, lines: int = 300, q: str = "", hide_debug: bool = True):
    """The tail of a server log (web = this server, vllm = the LLM, setup = installation), for the page's Server log tab."""
    if (denied := _monitor_guard(request)) is not None:
        return denied
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


def is_ready() -> bool:
    return MOCK or (READY["done"] and not READY["error"])


def running_tests() -> int:
    return sum(1 for v in SESSIONS.values() if v.phase != "done")


@app.get("/health")
def health():
    return {"ok": True, "mock": MOCK, "tests_running": running_tests(), "max_tests": MAX_SESSIONS,
            "version": svc.API_VERSION, "ready": is_ready(), "models_error": READY["error"]}


async def _serve(websocket: WebSocket, session: ExamSession, *, service: bool = False) -> None:
    """Run one test on an accepted socket and, whatever happens, forget it and save what it recorded.
    `service`: the contract's `test` message first, and a failure is reported as an `error` message instead of just ending the socket."""
    LIVE["session"] = session
    SESSIONS[session.test_id] = session
    try:
        if service:
            await websocket.send_json({"type": "test", "id": session.test_id})
        if MOCK:
            await run_mock(websocket, session)
        else:
            await run_real(websocket, session)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        if not service:
            raise
        log.exception("test %s failed", session.test_id)
        session.status, session.end_reason = "failed", session.end_reason or "error"
        try:
            await websocket.send_json({"type": "error", "code": "internal", "message": f"{type(e).__name__}"})
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        SESSIONS.pop(session.test_id, None)
        path = session.abort() if session.started else None
        if path:
            log.info("saved run log %s", path)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    running = running_tests()
    if running >= MAX_SESSIONS:
        # the GPU is shared: a test that cannot get its share would stutter for everyone, so it waits instead
        await websocket.close(code=1013, reason=f"Server is full ({running} tests running). Please try again in a minute.")
        return
    session = ExamSession(send=websocket.send_json)
    session.device = (websocket.query_params.get("device") or "")[:40]     # optional label: open the page with ?device=Laptop
    await _serve(websocket, session)


# ---- service API (docs/API_CONTRACT_V1.md): one WebSocket per test, API key, results -------------------------------------
@app.websocket("/v1/session")
async def v1_session(websocket: WebSocket):
    # A refusal before accept() reaches the caller as an HTTP 403 on the upgrade request (the socket never opens).
    if svc.check_bearer(websocket.headers.get("authorization")) != "ok":
        await websocket.close(code=1008)
        return
    params = websocket.query_params
    external = (params.get("external_user_id") or "").strip()[:120]
    hour = params.get("hour")
    if not external or (hour is not None and not (hour.isdigit() and 0 <= int(hour) <= 23)):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    if not is_ready():
        await websocket.close(code=1013, reason="Service is starting")
        return
    running = running_tests()
    if running >= MAX_SESSIONS:
        await websocket.close(code=1013, reason=f"Server is full ({running} tests running)")
        return
    session = ExamSession(send=websocket.send_json, hour=int(hour) if hour is not None else None)
    session.external_user_id = external
    session.device = (params.get("device") or "")[:40]
    await _serve(websocket, session, service=True)


def _guard(request: Request):
    """The error response when the request is not allowed (bad or missing key), else None."""
    return svc.auth_error(svc.check_bearer(request.headers.get("authorization")))


@app.get("/v1/tests/{test_id}")
def v1_test(test_id: str, request: Request):
    if (denied := _guard(request)) is not None:
        return denied
    live = SESSIONS.get(test_id) if svc.TEST_ID.match(test_id) else None
    if live is not None:
        stamps = [e["at"] for e in live.log if "at" in e]
        return {"id": live.test_id, "external_user_id": live.external_user_id, "status": live.status, "started_at": stamps[0] if stamps else None,
                "ended_at": None, "end_reason": "", "phase": live.phase}
    path = svc.run_file(test_id)
    if path is None:
        return svc.error(404, "not_found", "No such test")
    return svc.summary(svc.load_record(path))


@app.get("/v1/tests/{test_id}/result")
def v1_result(test_id: str, request: Request):
    if (denied := _guard(request)) is not None:
        return denied
    if test_id in SESSIONS:
        return svc.error(404, "not_finished", "The test is still running")
    path = svc.run_file(test_id)
    if path is None:
        return svc.error(404, "not_found", "No such test")
    return JSONResponse(svc.load_record(path))


@app.get("/v1/tests/{test_id}/audio")
def v1_audio(test_id: str, request: Request):
    if (denied := _guard(request)) is not None:
        return denied
    path = svc.run_file(test_id)
    wav = path.with_suffix(".wav") if path else None
    if wav is None or not wav.exists():
        return svc.error(404, "not_found", "No recording for this test")
    return FileResponse(wav, media_type="audio/wav")


# ---- monitoring page: the service as a whole (worker/monitor.py) ------------------------------------------------------
MONITOR_COOKIE = "monitor"


def _monitor_verdict(request: Request, *, from_link_ok: bool = False) -> tuple[str, bool]:
    """('ok' | 'no_key' | 'bad', came_from_the_link). Key: `Authorization: Bearer`, the cookie, or (page only) ?key= which sets the cookie.
    With no MONITOR_KEY the page stays closed, except in mock mode (no real tests, nothing to protect)."""
    import hmac

    want = os.getenv("MONITOR_KEY", "")
    if not want:
        return ("ok", False) if MOCK else ("no_key", False)
    scheme, _, bearer = (request.headers.get("authorization") or "").partition(" ")
    offered = [(bearer.strip(), False)] if scheme.lower() == "bearer" else []
    offered.append((request.cookies.get(MONITOR_COOKIE, ""), False))
    if from_link_ok:
        offered.append((request.query_params.get("key", ""), True))
    for value, link in offered:
        if value and hmac.compare_digest(value.encode(), want.encode()):
            return "ok", link
    return "bad", False


def _monitor_denied(verdict: str):
    from fastapi.responses import PlainTextResponse

    if verdict == "no_key":
        return PlainTextResponse("The monitoring page is closed: set MONITOR_KEY on the server.", status_code=503)
    return PlainTextResponse("Monitor key needed. Open /monitor?key=<your key> once.", status_code=401, headers={"WWW-Authenticate": "Bearer"})


def _monitor_guard(request: Request):
    """The refusal for a request to a monitoring data route (key in `Authorization: Bearer` or the cookie), or None when allowed."""
    verdict, _ = _monitor_verdict(request)
    return None if verdict == "ok" else _monitor_denied(verdict)


@app.get("/monitor")
def monitor_page(request: Request):
    verdict, from_link = _monitor_verdict(request, from_link_ok=True)
    if verdict != "ok":
        return _monitor_denied(verdict)
    response = FileResponse(WEB / "monitor.html")
    if from_link:
        response.set_cookie(MONITOR_COOKIE, os.getenv("MONITOR_KEY", ""), httponly=True, samesite="lax", max_age=86400, path="/")
    return response


@app.get("/api/monitor")
def monitor_data(request: Request):
    verdict, _ = _monitor_verdict(request)
    if verdict != "ok":
        return _monitor_denied(verdict)
    return mon.snapshot(sessions=SESSIONS, runs_dir=sess.RUNS, max_tests=MAX_SESSIONS, ready=is_ready(), models_error=READY["error"],
                        mock=MOCK, version=svc.API_VERSION, captions=caption_budget.BUDGET.stats())


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
