"""The public face of the service, and the way it is started: two ports, one process.

The service has two kinds of callers:

* **public**: ieltsup's server and their students' browsers. They may reach exactly the service API (`/v1/...`, see
  docs/API_CONTRACT_V1.md) and `/health`. Nothing else.
* **internal**: us. The test bench page, its microphone socket (`/ws`), the monitor, the run log and the server log. They show or use
  student speech and the GPU, so they listen on the loopback address only (reach them through an SSH tunnel).

Both ports serve the same application in the same process, so they share the running tests, the loaded models and the GPU. The public
port is that application behind `PublicGate`, which answers 404 to every path that is not on the allow-list, so a route added later
is private until someone decides to publish it here.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re

log = logging.getLogger("speaking.public")

PUBLIC_EXACT = frozenset({"/health"})
PUBLIC_PREFIXES = ("/v1/",)
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})

# ---- which websites may talk to the service from a browser -----------------------------------------------------------
# ALLOWED_ORIGINS: comma separated exact origins, e.g. "https://ieltsup.org,https://www.ieltsup.org". No wildcard, no path. Plain http
# is accepted only for localhost (development). Not set: no browser is allowed (a caller that sends no Origin header, such as
# ieltsup's server or our load test, is not a browser and is not affected).
ORIGIN_SHAPE = re.compile(r"^(https?)://([a-z0-9]([a-z0-9.-]*[a-z0-9])?|\[[0-9a-f:]+\])(:\d{1,5})?$")


def parse_origins(value: str) -> frozenset[str]:
    """The allowed origins in the form a browser sends them (lower case, default port left out). Raises ValueError on anything doubtful."""
    found = set()
    for raw in value.split(","):
        text = raw.strip().lower()
        if not text:
            continue
        match = ORIGIN_SHAPE.match(text)
        if not match:
            raise ValueError(f"ALLOWED_ORIGINS: {raw.strip()!r} is not an origin like https://example.org (no wildcard, path or trailing slash)")
        scheme, host, _, port = match.groups()
        if scheme == "http" and host not in LOOPBACK:
            raise ValueError(f"ALLOWED_ORIGINS: {raw.strip()!r} is plain http; only localhost may use http")
        if port == (":443" if scheme == "https" else ":80"):
            text = f"{scheme}://{host}"                  # a browser leaves the default port out of the Origin header
        found.add(text)
    return frozenset(found)


def allowed_origins() -> frozenset[str]:
    try:
        return parse_origins(os.getenv("ALLOWED_ORIGINS", ""))
    except ValueError:
        return frozenset()                                # a bad setting is refused at start-up; until then nothing is allowed


def origin_allowed(origin: str | None) -> bool:
    """True for a request without an Origin header (not a browser) and for a listed origin. The literal 'null' is never allowed."""
    return origin is None or origin.strip().lower() in allowed_origins()


def cors_headers(origin: str | None) -> list[tuple[bytes, bytes]]:
    """Response headers that let a listed website READ a public response. Never sent with credentials."""
    if origin is None or origin.strip().lower() not in allowed_origins():
        return [(b"vary", b"Origin")]
    return [(b"access-control-allow-origin", origin.strip().lower().encode()), (b"vary", b"Origin")]


TOKEN_IN_URL = re.compile(r"([?&]token=)[^\s&\"']+")


class RedactTokens(logging.Filter):
    """uvicorn logs the whole URL of a WebSocket, and ours carries the browser's token: keep it out of every log (and the monitor's copy)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if "token=" in message:
            record.msg, record.args = TOKEN_IN_URL.sub(r"\g<1>REDACTED", message), ()
        return True


def redact_tokens_in_logs() -> None:
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactTokens) for f in logger.filters):
            logger.addFilter(RedactTokens())


def is_public(path: str) -> bool:
    """True when `path` may be reached on the public port."""
    if "\\" in path or "//" in path or "/../" in path + "/" or path.endswith("/.."):
        return False                                    # nothing legitimate looks like this; do not rely on how the router reads it
    return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)


class PublicGate:
    """ASGI wrapper: lets the allow-listed paths through to `inner`, answers everything else as if it did not exist."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind == "lifespan":
            # The wrapped application starts and stops with the internal server (models load once, not twice).
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if is_public(scope.get("path", "")):
            if kind == "http" and scope.get("path") == "/health":
                return await self._health(scope, receive, send)       # the one route a page may read cross-site (is the service ready?)
            return await self.inner(scope, receive, send)
        if kind == "websocket":
            await receive()                                           # the connect message; closing before accepting is an HTTP 403
            return await send({"type": "websocket.close", "code": 1008})
        body = b'{"error":{"code":"not_found","message":"Not found"}}'
        await send({"type": "http.response.start", "status": 404,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def _health(self, scope, receive, send):
        origin = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"origin"), None)
        extra = cors_headers(origin)
        if scope.get("method") == "OPTIONS":                         # the browser's preflight for /health
            await send({"type": "http.response.start", "status": 204, "headers": [*extra, (b"access-control-allow-methods", b"GET"),
                                                                                  (b"access-control-max-age", b"600")]})
            return await send({"type": "http.response.body", "body": b""})

        async def with_cors(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.inner(scope, receive, with_cors)


def internal_address() -> tuple[str, int]:
    """Where the internal app listens. Anything but a loopback address needs an explicit INTERNAL_ALLOW_REMOTE=1."""
    host = os.getenv("INTERNAL_HOST", "127.0.0.1")
    port = int(os.getenv("INTERNAL_PORT", "8081"))
    if host not in LOOPBACK and os.getenv("INTERNAL_ALLOW_REMOTE") != "1":
        raise SystemExit(f"Refusing to start: INTERNAL_HOST={host} would put the monitor and test bench on the network. "
                         "Use 127.0.0.1 and an SSH tunnel, or set INTERNAL_ALLOW_REMOTE=1 if you really mean it.")
    return host, port


def serve_single(app, *, host: str, port: int) -> None:
    """The old one-port mode (SINGLE_PORT=1), still with tokens kept out of the log."""
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port))
    redact_tokens_in_logs()
    server.run()


async def serve_both(app, *, public_host: str, public_port: int, internal_host: str, internal_port: int) -> int:
    """Run the internal app and the public gate side by side until one stops. Returns the process exit code."""
    import uvicorn

    if (public_host, public_port) == (internal_host, internal_port) or public_port == internal_port:
        raise SystemExit(f"Refusing to start: PORT and INTERNAL_PORT are both {public_port}; they must differ.")
    internal = uvicorn.Server(uvicorn.Config(app, host=internal_host, port=internal_port))
    public = uvicorn.Server(uvicorn.Config(PublicGate(app), host=public_host, port=public_port,
                                          access_log=False))      # the access log prints the whole URL, and a socket's URL carries its token
    redact_tokens_in_logs()
    log.info("public  http://%s:%s  (only /v1 and /health)", public_host, public_port)
    log.info("internal http://%s:%s  (test bench, monitor, logs)", internal_host, internal_port)
    tasks = [asyncio.create_task(internal.serve()), asyncio.create_task(public.serve())]
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for server in (internal, public):
        server.should_exit = True
    await asyncio.gather(*tasks, return_exceptions=True)
    # The internal app owns the start-up checks (keys, models). If it never came up, the public port must not have served either.
    return 0 if internal.started else 3
