"""Looks at the service from the outside, the way ieltsup's browsers and server will, and says whether the public address is fit to hand over.

    python -m eval.check_public --base https://speaking-staging.example.org --origin https://ieltsup.org --api-key $KEY

It checks, in this order: the address is https with a good certificate; /health answers and the service is ready; every internal page and
route (test bench, monitor, run log, server log, API docs, the bench microphone socket) does NOT exist on this address; the service API
refuses a missing or wrong key; a listed website can read /health and an unlisted one cannot; the key-protected calls send no CORS headers;
responses carry the security headers and are not cacheable; and, with --api-key, a real browser round trip: a token is minted, the socket
opens with it (sent with the page's Origin), the token works once, and a wrong website is refused.

With --api-key it opens two test sockets and closes them at once without starting a test: no examiner speaks, nothing is saved.
Exit code 0 when nothing failed (warnings are allowed), 1 otherwise. Needs: httpx, websockets.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import ssl
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

PRIVATE_PATHS = ["/", "/monitor", "/api/monitor", "/api/runs", "/api/live", "/api/serverlog/web", "/logs", "/static/app.js",
                 "/docs", "/redoc", "/openapi.json"]
EVIL_ORIGIN = "https://not-allowed.invalid"
CERT_WARN_DAYS = 14


@dataclass
class Result:
    name: str
    status: str            # PASS | FAIL | WARN | SKIP
    detail: str = ""


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.results.append(Result(name, status, detail))

    def check(self, name: str, ok: bool, detail: str = "", *, fail: str = "FAIL") -> bool:
        self.add(name, "PASS" if ok else fail, detail)
        return ok

    @property
    def failed(self) -> bool:
        return any(r.status == "FAIL" for r in self.results)

    def show(self) -> None:
        width = max((len(r.name) for r in self.results), default=10)
        for r in self.results:
            print(f"  {r.status:<4}  {r.name:<{width}}  {r.detail}")
        counts = {s: sum(1 for r in self.results if r.status == s) for s in ("PASS", "WARN", "SKIP", "FAIL")}
        print("\n" + ", ".join(f"{n} {s.lower()}" for s, n in counts.items() if n) + ("  ->  NOT READY" if self.failed else "  ->  OK"))


def certificate_days_left(host: str, port: int, timeout: float = 8.0) -> int:
    """Days until the certificate expires, checked with the system's trusted roots (raises ssl.SSLError when it is not trusted)."""
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as raw, context.wrap_socket(raw, server_hostname=host) as tls:
        expires = ssl.cert_time_to_seconds(tls.getpeercert()["notAfter"])
    return int((expires - time.time()) // 86400)


def ws_url(base: str, path: str) -> str:
    return ("wss" if base.startswith("https") else "ws") + base[base.index("://"):] + path


async def socket_outcome(url: str, *, origin: str | None = None, headers: dict | None = None, wait: float = 10.0) -> tuple[str, dict | None]:
    """('refused', None) when the upgrade is refused; ('open', first message) when it opens; ('error', {...}) on anything else."""
    import websockets

    try:
        async with websockets.connect(url, origin=origin, additional_headers=headers, open_timeout=wait, max_size=None) as ws:
            raw = await asyncio.wait_for(ws.recv(), wait)
            try:
                return "open", json.loads(raw)
            except (TypeError, ValueError):
                return "open", {"type": "binary"}
    except websockets.exceptions.InvalidStatus:
        return "refused", None
    except websockets.exceptions.ConnectionClosed as e:
        return "closed", {"code": e.rcvd.code if e.rcvd else None}
    except Exception as e:                                          # DNS, TLS, timeout ...
        return "error", {"error": f"{type(e).__name__}: {e}"[:160]}


def run(base: str, *, origin: str | None, api_key: str, allow_http: bool, timeout: float = 10.0) -> Report:
    import httpx

    report = Report()
    base = base.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        report.add("address", "FAIL", f"{base!r} is not an http(s) address")
        return report
    secure = parsed.scheme == "https"

    # 1. https and the certificate
    if secure:
        try:
            days = certificate_days_left(parsed.hostname, parsed.port or 443)
            report.add("https certificate", "PASS" if days >= CERT_WARN_DAYS else "WARN", f"trusted, {days} days left")
        except Exception as e:
            report.add("https certificate", "FAIL", f"{type(e).__name__}: {e}"[:160])
            return report                                           # nothing else can be trusted over a broken connection
    else:
        report.add("https certificate", "WARN" if allow_http else "FAIL", "the address is plain http" + ("" if allow_http else " (--allow-http for a local check)"))

    client = httpx.Client(base_url=base, timeout=timeout, follow_redirects=False)

    def get(path, **kw):
        try:
            return client.get(path, **kw)
        except httpx.HTTPError as e:
            report.add(f"GET {path}", "FAIL", f"{type(e).__name__}: {e}"[:160])
            return None

    # 2. health
    health = get("/health")
    if health is None:
        return report
    body = health.json() if health.headers.get("content-type", "").startswith("application/json") else {}
    report.check("GET /health", health.status_code == 200 and body.get("ok") is True and body.get("version") == "1", f"HTTP {health.status_code} {body}"[:140])
    report.add("service ready", "PASS" if body.get("ready") else "WARN", "models loaded" if body.get("ready") else "ready is false: models still loading")
    report.add("taking tests", "PASS" if body.get("accepting") else "WARN", "accepting" if body.get("accepting") else f"busy_reason={body.get('busy_reason')!r}")

    # 3. the internal pages do not exist here
    leaked = []
    for path in PRIVATE_PATHS:
        r = get(path)
        if r is not None and r.status_code != 404:
            leaked.append(f"{path} -> {r.status_code}")
    report.check("internal pages hidden", not leaked, ", ".join(leaked) or f"{len(PRIVATE_PATHS)} paths all 404")
    outcome, _ = asyncio.run(socket_outcome(ws_url(base, "/ws?device=check"), origin=origin))
    report.check("bench socket /ws closed", outcome == "refused", f"outcome: {outcome}" + ("" if outcome == "refused" else " (the test bench microphone socket must not be public)"))

    # 4. the service API wants a key
    no_key = client.post("/v1/tokens", json={"external_user_id": "check"})
    bad_key = client.post("/v1/tokens", json={"external_user_id": "check"}, headers={"Authorization": "Bearer wrong-key"})
    report.check("POST /v1/tokens without key", no_key.status_code == 401, f"HTTP {no_key.status_code}")
    report.check("POST /v1/tokens with a wrong key", bad_key.status_code == 401, f"HTTP {bad_key.status_code}")
    results = client.get("/v1/tests/1")
    report.check("GET /v1/tests/1 without key", results.status_code == 401, f"HTTP {results.status_code}")
    no_key_socket, _ = asyncio.run(socket_outcome(ws_url(base, "/v1/session?external_user_id=check"), origin=origin))
    report.check("socket without key or token", no_key_socket == "refused", f"outcome: {no_key_socket}")

    # 5. which websites may read the answers
    if origin:
        ok = get("/health", headers={"origin": origin})
        report.check("listed website can read /health", ok is not None and ok.headers.get("access-control-allow-origin") == origin,
                     f"access-control-allow-origin: {ok.headers.get('access-control-allow-origin') if ok is not None else None}")
        for kind, call in (("POST /v1/tokens", lambda: client.options("/v1/tokens", headers={"origin": origin, "access-control-request-method": "POST"})),
                           ("GET /v1/tests/1", lambda: client.get("/v1/tests/1", headers={"origin": origin}))):
            r = call()
            report.check(f"{kind} not readable from a page", "access-control-allow-origin" not in r.headers, "no CORS headers" if "access-control-allow-origin" not in r.headers else "CORS header present!")
    else:
        report.add("listed website can read /health", "SKIP", "give --origin")
    evil = get("/health", headers={"origin": EVIL_ORIGIN})
    report.check("unlisted website cannot read /health", evil is not None and "access-control-allow-origin" not in evil.headers, EVIL_ORIGIN)

    # 6. headers
    missing = [h for h in ("x-content-type-options", "referrer-policy", "cache-control") if h not in health.headers]
    if secure and "strict-transport-security" not in health.headers:
        missing.append("strict-transport-security")
    report.check("security headers", not missing and "no-store" in health.headers.get("cache-control", ""), ("missing: " + ", ".join(missing)) if missing else "present, not cacheable")

    # 7. a real browser round trip
    if not api_key:
        report.add("browser round trip", "SKIP", "give --api-key to mint a token and open a socket")
        return report
    auth = {"Authorization": f"Bearer {api_key}"}
    minted = client.post("/v1/tokens", json={"external_user_id": "check-public", "hour": 9}, headers=auth)
    if not report.check("POST /v1/tokens with the key", minted.status_code == 200 and "token" in minted.json(), f"HTTP {minted.status_code}"):
        return report
    token = minted.json()["token"]
    report.check("token response not cacheable", "no-store" in minted.headers.get("cache-control", ""), minted.headers.get("cache-control", "(none)"))
    url = ws_url(base, f"/v1/session?token={token}")
    first, message = asyncio.run(socket_outcome(url, origin=origin))
    report.check("socket opens with a token", first == "open" and (message or {}).get("type") == "test", f"{first}: {message}"[:140])
    again, message = asyncio.run(socket_outcome(url, origin=origin))
    report.check("a token works only once", again == "open" and (message or {}).get("code") == "token_used", f"{again}: {message}"[:140])
    if origin:
        fresh = client.post("/v1/tokens", json={"external_user_id": "check-public"}, headers=auth).json()["token"]
        wrong, message = asyncio.run(socket_outcome(ws_url(base, f"/v1/session?token={fresh}"), origin=EVIL_ORIGIN))
        report.check("unlisted website refused", wrong == "open" and (message or {}).get("code") == "origin_not_allowed", f"{wrong}: {message}"[:140])
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Check the public address of the speaking service from the outside.")
    p.add_argument("--base", required=True, help="the public address, e.g. https://speaking-staging.example.org")
    p.add_argument("--origin", default="", help="a website that is in ALLOWED_ORIGINS (what ieltsup's page sends), e.g. https://ieltsup.org")
    p.add_argument("--api-key", default="", help="a key from SERVICE_API_KEYS: also test the token and socket round trip")
    p.add_argument("--allow-http", action="store_true", help="accept a plain http address (a local check only)")
    args = p.parse_args(argv)
    report = run(args.base, origin=args.origin or None, api_key=args.api_key, allow_http=args.allow_http)
    print(f"\nPublic address check: {args.base}\n")
    report.show()
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
