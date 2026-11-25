"""Which websites may use the service from a browser (ALLOWED_ORIGINS): the setting, the socket check and CORS on /health."""
import asyncio

import pytest
from fastapi.testclient import TestClient

import worker.public as public
import worker.server as server
import worker.session as sess
import worker.tokens as tk

KEY = {"Authorization": "Bearer k1"}
SITE = "https://ieltsup.org"


@pytest.fixture(autouse=True)
def configured(monkeypatch, tmp_path):
    monkeypatch.setenv("TOKEN_SECRET", "s" * 40)
    monkeypatch.setenv("SERVICE_API_KEYS", "k1")
    monkeypatch.setenv("ALLOWED_ORIGINS", f"{SITE}, https://www.ieltsup.org")
    monkeypatch.setattr(tk, "USED", tk.UsedTokens())
    monkeypatch.setattr(server, "MOCK", True)
    monkeypatch.setattr(server, "SESSIONS", {})
    monkeypatch.setattr(sess, "RUNS", tmp_path)


# ---- the setting ----------------------------------------------------------------------------------------
def test_origins_are_read_in_the_form_a_browser_sends_them():
    assert public.parse_origins(" HTTPS://IeltsUp.org , https://www.ieltsup.org:443,http://localhost:3000,,") == \
        {"https://ieltsup.org", "https://www.ieltsup.org", "http://localhost:3000"}
    assert public.parse_origins("") == frozenset()
    assert public.parse_origins("https://a.example:8443") == {"https://a.example:8443"}       # a non-default port is kept
    assert public.parse_origins("http://localhost:80") == {"http://localhost"}


@pytest.mark.parametrize("bad", ["*", "https://*.ieltsup.org", "ieltsup.org", "https://ieltsup.org/", "https://ieltsup.org/app", "https://",
                                 "http://ieltsup.org", "https://a b.org", "ftp://ieltsup.org", "https://ieltsup.org:99999999", "null"])
def test_a_doubtful_setting_is_refused(bad):
    with pytest.raises(ValueError, match="ALLOWED_ORIGINS"):
        public.parse_origins(bad)


def test_plain_http_is_for_localhost_only():
    assert public.parse_origins("http://localhost:3000,http://127.0.0.1:5173") == {"http://localhost:3000", "http://127.0.0.1:5173"}


def test_start_up_refuses_a_bad_setting_and_warns_when_none_is_set(monkeypatch, caplog):
    starters = [h for h in server.app.router.on_startup if h.__name__ == "_require_keys"]
    if not starters:
        pytest.skip("the app was imported in mock mode, so the check is not installed")
    monkeypatch.setattr(server, "MOCK", False)
    monkeypatch.setenv("MONITOR_KEY", "m")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
        asyncio.run(starters[0]())
    monkeypatch.setenv("ALLOWED_ORIGINS", "")
    with caplog.at_level("WARNING", logger="speaking.server"):
        asyncio.run(starters[0]())                        # still starts (server-to-server works) ...
    assert "no browser can open a test" in caplog.text    # ... and says so
    monkeypatch.setenv("ALLOWED_ORIGINS", SITE)
    caplog.clear()
    asyncio.run(starters[0]())
    assert "no browser" not in caplog.text


# ---- the socket -----------------------------------------------------------------------------------------
def first_message(c, url, **kw):
    with c.websocket_connect(url, **kw) as ws:
        return ws.receive_json()


def token(c):
    return c.post("/v1/tokens", json={"external_user_id": "u"}, headers=KEY).json()["token"]


@pytest.mark.parametrize("origin", [SITE, "https://www.ieltsup.org", "HTTPS://IELTSUP.ORG"])
def test_a_listed_website_opens_a_test(origin):
    c = TestClient(server.app)
    assert first_message(c, f"/v1/session?token={token(c)}", headers={"origin": origin})["type"] == "test"


@pytest.mark.parametrize("origin", ["https://evil.example", "https://ieltsup.org.evil.example", "https://evilieltsup.org", "http://ieltsup.org",
                                    "https://ieltsup.org:8443", "https://sub.ieltsup.org", "null", ""])
def test_any_other_website_is_refused_and_told_why(origin):
    c = TestClient(server.app)
    t = token(c)
    first = first_message(c, f"/v1/session?token={t}", headers={"origin": origin})
    assert first["type"] == "error" and first["code"] == "origin_not_allowed" and not server.SESSIONS
    assert first_message(c, f"/v1/session?token={t}", headers={"origin": SITE})["type"] == "test"      # the refusal did not spend the token


def test_a_refused_origin_cannot_use_an_api_key_either():
    c = TestClient(server.app)
    first = first_message(c, "/v1/session?external_user_id=u", headers={**KEY, "origin": "https://evil.example"})
    assert first["code"] == "origin_not_allowed"


def test_a_caller_without_an_origin_is_not_a_browser_and_is_unaffected(monkeypatch):
    c = TestClient(server.app)
    assert first_message(c, "/v1/session?external_user_id=u", headers=KEY)["type"] == "test"
    monkeypatch.delenv("ALLOWED_ORIGINS")
    assert first_message(c, "/v1/session?external_user_id=u", headers=KEY)["type"] == "test"


def test_with_no_setting_no_browser_is_allowed(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS")
    c = TestClient(server.app)
    assert first_message(c, f"/v1/session?token={token(c)}", headers={"origin": SITE})["code"] == "origin_not_allowed"


# ---- CORS on the public port: /health only ----------------------------------------------------------------
@pytest.fixture
def gate():
    return TestClient(public.PublicGate(server.app))


def test_a_listed_website_may_read_health(gate):
    r = gate.get("/health", headers={"origin": SITE})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == SITE and "Origin" in r.headers["vary"]
    assert "access-control-allow-credentials" not in r.headers


def test_another_website_may_not_read_health(gate):
    r = gate.get("/health", headers={"origin": "https://evil.example"})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers          # the browser will hide the answer from that page
    assert "access-control-allow-origin" not in gate.get("/health").headers


def test_the_preflight_for_health(gate):
    ok = gate.options("/health", headers={"origin": SITE, "access-control-request-method": "GET"})
    assert ok.status_code == 204 and ok.headers["access-control-allow-origin"] == SITE and ok.headers["access-control-allow-methods"] == "GET"
    no = gate.options("/health", headers={"origin": "https://evil.example", "access-control-request-method": "GET"})
    assert no.status_code == 204 and "access-control-allow-origin" not in no.headers


@pytest.mark.parametrize("method,path", [("post", "/v1/tokens"), ("get", "/v1/tests/1"), ("get", "/v1/tests/1/result"), ("get", "/v1/tests/1/audio"),
                                         ("options", "/v1/tokens")])
def test_the_key_protected_calls_are_never_readable_from_a_browser_page(gate, method, path):
    r = getattr(gate, method)(path, headers={"origin": SITE, **KEY})
    assert "access-control-allow-origin" not in r.headers          # these are for ieltsup's server; a page must not read them


def test_the_internal_app_has_no_cors_at_all():
    r = TestClient(server.app).get("/health", headers={"origin": SITE})
    assert "access-control-allow-origin" not in r.headers


# ---- the real thing: a real socket with an Origin header, as a browser sends it ----------------------------
def test_a_real_socket_from_a_listed_and_an_unlisted_website():
    import json

    import httpx

    from tests.test_public import free_port, start, wait_up

    pytest.importorskip("uvicorn")
    websockets = pytest.importorskip("websockets")
    pub = free_port()
    proc = start({"MOCK": "1", "PORT": str(pub), "INTERNAL_PORT": str(free_port()), "SERVICE_API_KEYS": "k1", "TOKEN_SECRET": "z" * 40,
                  "ALLOWED_ORIGINS": SITE})
    try:
        wait_up(f"http://127.0.0.1:{pub}/health", proc)
        health = httpx.get(f"http://127.0.0.1:{pub}/health", headers={"origin": SITE})
        assert health.headers["access-control-allow-origin"] == SITE
        assert "access-control-allow-origin" not in httpx.get(f"http://127.0.0.1:{pub}/health", headers={"origin": "https://evil.example"}).headers

        async def first(origin):
            minted = httpx.post(f"http://127.0.0.1:{pub}/v1/tokens", json={"external_user_id": "u"}, headers=KEY).json()
            async with websockets.connect(f"ws://127.0.0.1:{pub}/v1/session?token={minted['token']}", origin=origin) as ws:
                return json.loads(await asyncio.wait_for(ws.recv(), 10))

        assert asyncio.run(first(SITE))["type"] == "test"
        assert asyncio.run(first("https://evil.example"))["code"] == "origin_not_allowed"
    finally:
        proc.terminate()
        proc.wait(timeout=15)
