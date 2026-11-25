"""The public/internal split (worker/public.py): the public port serves the service API and /health, nothing else."""
import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import worker.public as public
import worker.server as server

PRIVATE_PATHS = ["/", "/monitor", "/api/monitor", "/api/runs", "/api/runs/run_20261122_071217", "/api/live", "/api/serverlog/web", "/logs",
                 "/static/app.js", "/docs", "/redoc", "/openapi.json", "/v1", "/healthz", "/health/x"]


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setattr(server, "MOCK", True)       # mock mode opens the monitor and the bench: if the gate leaked, these would answer 200
    return TestClient(public.PublicGate(server.app))


def test_health_and_the_service_api_reach_the_application(gate):
    assert gate.get("/health").json()["version"] == "1"
    assert gate.get("/v1/tests/1").status_code in (401, 503)       # the application answered (no API key), not the gate's 404


@pytest.mark.parametrize("path", PRIVATE_PATHS)
def test_everything_else_does_not_exist_on_the_public_port(gate, path):
    r = gate.get(path)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert TestClient(server.app).get(path).status_code != 404 or path in ("/v1", "/healthz", "/health/x")    # it is the gate that hides it


@pytest.mark.parametrize("path", ["/v1/../monitor", "/v1//x", "/v1/..", "/v1\..\monitor", "//monitor", "/health/../monitor"])
def test_tricky_paths_are_refused(gate, path):
    assert gate.get(path).status_code == 404


def test_the_bench_microphone_socket_is_not_public(gate):
    with pytest.raises(Exception):
        with gate.websocket_connect("/ws?device=x") as ws:
            ws.receive_text()
    with TestClient(server.app).websocket_connect("/ws?device=x"):      # the same socket on the internal app does open
        pass


def test_the_service_socket_still_reaches_the_application(gate, monkeypatch):
    monkeypatch.setenv("SERVICE_API_KEYS", "k1")
    with gate.websocket_connect("/v1/session?external_user_id=u1", headers={"Authorization": "Bearer k1"}) as ws:
        assert ws.receive_json()["type"] == "test"                  # the application opened a test: the gate let the socket through
    with pytest.raises(Exception):
        with gate.websocket_connect("/v1/session?external_user_id=u1") as ws:       # without the key the application still refuses it
            ws.receive_text()


def test_a_new_route_is_private_until_it_is_listed():
    """Guard against drift: these, and only these, routes of the application are public."""
    published = {r.path for r in server.app.routes if getattr(r, "path", None) and public.is_public(r.path.split("{")[0].rstrip("/") + ("/" if "{" in r.path else ""))}
    assert published == {"/health", "/v1/session", "/v1/tokens", "/v1/tests/{test_id}", "/v1/tests/{test_id}/result", "/v1/tests/{test_id}/audio"}


def test_the_internal_app_listens_on_loopback_only(monkeypatch):
    monkeypatch.delenv("INTERNAL_HOST", raising=False)
    assert public.internal_address() == ("127.0.0.1", 8081)
    monkeypatch.setenv("INTERNAL_HOST", "0.0.0.0")
    with pytest.raises(SystemExit, match="would put the monitor"):
        public.internal_address()
    monkeypatch.setenv("INTERNAL_ALLOW_REMOTE", "1")
    assert public.internal_address()[0] == "0.0.0.0"


# ---- the real thing: two ports from one process -------------------------------------------------------
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(env_extra: dict, log=subprocess.DEVNULL) -> subprocess.Popen:
    env = {**os.environ, "HOST": "127.0.0.1", **env_extra}
    return subprocess.Popen([sys.executable, "-m", "worker.server"], env=env, stdout=log, stderr=log)


def wait_up(url: str, proc: subprocess.Popen, seconds: float = 20):
    end = time.time() + seconds
    while time.time() < end:
        assert proc.poll() is None, "the server stopped"
        try:
            return httpx.get(url, timeout=1)
        except httpx.HTTPError:
            time.sleep(0.2)
    raise AssertionError("the server did not come up")


def test_two_ports_one_process():
    pytest.importorskip("uvicorn")
    pub, internal = free_port(), free_port()
    proc = start({"MOCK": "1", "PORT": str(pub), "INTERNAL_PORT": str(internal)})
    try:
        assert wait_up(f"http://127.0.0.1:{pub}/health", proc).json()["ok"] is True
        wait_up(f"http://127.0.0.1:{internal}/health", proc)
        assert httpx.get(f"http://127.0.0.1:{pub}/").status_code == 404                  # the bench page is not on the public port
        assert httpx.get(f"http://127.0.0.1:{pub}/monitor").status_code == 404
        assert httpx.get(f"http://127.0.0.1:{internal}/").status_code == 200             # ... but is on the internal one
        assert httpx.get(f"http://127.0.0.1:{internal}/monitor").status_code == 200
        assert httpx.get(f"http://127.0.0.1:{pub}/v1/tests/1").status_code in (401, 503)
    finally:
        proc.terminate()
        proc.wait(timeout=15)


def test_the_single_port_switch_keeps_the_old_behaviour():
    pytest.importorskip("uvicorn")
    port = free_port()
    proc = start({"MOCK": "1", "PORT": str(port), "SINGLE_PORT": "1"})
    try:
        wait_up(f"http://127.0.0.1:{port}/health", proc)
        assert httpx.get(f"http://127.0.0.1:{port}/").status_code == 200
    finally:
        proc.terminate()
        proc.wait(timeout=15)


def test_a_real_service_without_keys_never_serves_the_public_port():
    pytest.importorskip("uvicorn")
    pub, internal = free_port(), free_port()
    env = {"PORT": str(pub), "INTERNAL_PORT": str(internal)}
    for name in ("MOCK", "SERVICE_API_KEYS", "MONITOR_KEY", "SINGLE_PORT"):
        env[name] = ""
    proc = start(env)
    try:
        assert proc.wait(timeout=60) == 3                  # the internal app refused to start (no keys), so the whole service stops
    finally:
        if proc.poll() is None:
            proc.kill()


# ---- a token never reaches a log ----------------------------------------------------------------------
def test_the_log_filter_hides_tokens_and_leaves_other_lines_alone():
    f = public.RedactTokens()

    def out(msg, *args):
        record = logging.LogRecord("uvicorn.error", logging.INFO, "x", 1, msg, args, None)
        f.filter(record)
        return record.getMessage()

    assert out('%s - "WebSocket %s" [accepted]', "1.2.3.4:5", "/v1/session?token=abc.def_-9&device=Laptop") ==         '1.2.3.4:5 - "WebSocket /v1/session?token=REDACTED&device=Laptop" [accepted]'
    assert out("plain line, 100% fine") == "plain line, 100% fine"
    assert out("GET /health 200") == "GET /health 200"


@pytest.mark.parametrize("single", [False, True])
def test_a_browser_token_works_over_a_real_socket_and_stays_out_of_the_log(tmp_path, single):
    pytest.importorskip("uvicorn")
    websockets = pytest.importorskip("websockets")
    pub, internal = free_port(), free_port()
    env = {"MOCK": "1", "PORT": str(pub), "INTERNAL_PORT": str(internal), "SERVICE_API_KEYS": "k1", "TOKEN_SECRET": "z" * 40,
           "PYTHONUNBUFFERED": "1", **({"SINGLE_PORT": "1"} if single else {})}
    logfile = tmp_path / "server.log"
    with open(logfile, "w") as log:
        proc = start(env, log)
        try:
            wait_up(f"http://127.0.0.1:{pub}/health", proc)
            minted = httpx.post(f"http://127.0.0.1:{pub}/v1/tokens", json={"external_user_id": "stu-1", "hour": 8},
                                headers={"Authorization": "Bearer k1"}).json()

            async def first_message(token):
                async with websockets.connect(f"ws://127.0.0.1:{pub}/v1/session?token={token}") as ws:
                    return json.loads(await asyncio.wait_for(ws.recv(), 10))

            assert asyncio.run(first_message(minted["token"]))["type"] == "test"
            assert asyncio.run(first_message(minted["token"]))["code"] == "token_used"       # one token, one test
        finally:
            proc.terminate()
            proc.wait(timeout=15)
    text = logfile.read_text(errors="replace")
    assert "WebSocket /v1/session" in text                    # the connection was logged ...
    assert minted["token"] not in text and "token=REDACTED" in text         # ... without its token
