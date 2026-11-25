"""Short-lived browser tokens (worker/tokens.py) and how the service uses them: POST /v1/tokens and /v1/session?token=..."""
import base64
import json

import pytest
from fastapi.testclient import TestClient

import worker.server as server
import worker.session as sess
import worker.tokens as tk

SECRET = "s" * 40
KEY = {"Authorization": "Bearer k1"}


@pytest.fixture(autouse=True)
def configured(monkeypatch, tmp_path):
    monkeypatch.setenv("TOKEN_SECRET", SECRET)
    monkeypatch.setenv("SERVICE_API_KEYS", "k1")
    monkeypatch.delenv("TOKEN_TTL_S", raising=False)
    monkeypatch.setattr(tk, "USED", tk.UsedTokens())
    monkeypatch.setattr(server, "MOCK", True)
    monkeypatch.setattr(server, "SESSIONS", {})
    monkeypatch.setattr(sess, "RUNS", tmp_path)


def b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


# ---- the token itself ----------------------------------------------------------------------------------
def test_a_token_carries_who_it_is_for_and_expires():
    minted = tk.mint("student-7", 9, now=1000)
    assert minted["expires_in"] == 120 and minted["expires_at"] == 1120
    claims = tk.verify(minted["token"], now=1119)
    assert (claims.external_user_id, claims.hour, claims.exp) == ("student-7", 9, 1120)
    with pytest.raises(tk.TokenError) as e:
        tk.verify(minted["token"], now=1120)
    assert e.value.code == "token_expired"


def test_hour_is_optional():
    assert tk.verify(tk.mint("u", None, now=1)["token"], now=2).hour is None


def test_the_lifetime_is_configurable_but_bounded(monkeypatch):
    monkeypatch.setenv("TOKEN_TTL_S", "30")
    assert tk.mint("u", now=0)["expires_in"] == 30
    monkeypatch.setenv("TOKEN_TTL_S", "86400")
    assert tk.mint("u", now=0)["expires_in"] == tk.TTL_MAX_S
    monkeypatch.setenv("TOKEN_TTL_S", "1")
    assert tk.mint("u", now=0)["expires_in"] == 10
    monkeypatch.setenv("TOKEN_TTL_S", "soon")
    assert tk.mint("u", now=0)["expires_in"] == tk.TTL_DEFAULT_S


def test_a_changed_or_forged_token_is_refused():
    good = tk.mint("student-7", 9, now=1000)["token"]
    part, sig = good.split(".")
    payload = json.loads(base64.urlsafe_b64decode(part + "=="))
    forged_payload = b64({**payload, "sub": "someone-else"})
    bad_tokens = (f"{forged_payload}.{sig}",                     # payload changed, signature kept
                  f"{part}.{sig[:-2]}AA",                        # signature changed
                  f"{part}.", f".{sig}", part, "", "a.b.c", "x" * 2000, f"{b64({'sub': 'u'})}.{sig}")
    for bad in bad_tokens:
        with pytest.raises(tk.TokenError) as e:
            tk.verify(bad, now=1001)
        assert e.value.code == "token_invalid", bad
    assert tk.verify(good, now=1001)


def test_a_token_from_another_secret_is_refused(monkeypatch):
    token = tk.mint("u", now=0)["token"]
    monkeypatch.setenv("TOKEN_SECRET", "t" * 40)
    with pytest.raises(tk.TokenError, match="token_invalid"):
        tk.verify(token, now=1)


def test_a_correctly_signed_but_wrong_shaped_token_is_refused():
    def signed(payload):
        part = b64(payload)
        return f"{part}.{tk._sign(SECRET.encode(), part)}"

    base = {"v": 1, "jti": "a", "sub": "u", "exp": 10 ** 10}
    assert tk.verify(signed(base), now=1).external_user_id == "u"
    wrong = ({**base, "v": 2}, {**base, "sub": ""}, {**base, "sub": 5}, {**base, "hour": 24}, {**base, "hour": True}, {**base, "hour": "9"},
             {k: v for k, v in base.items() if k != "jti"}, {**base, "exp": "soon"})
    for bad in wrong:
        with pytest.raises(tk.TokenError, match="token_invalid"):
            tk.verify(signed(bad), now=1)


def test_without_a_secret_nothing_is_minted_or_accepted(monkeypatch):
    good = tk.mint("u", now=0)["token"]
    monkeypatch.setenv("TOKEN_SECRET", "too short")
    with pytest.raises(RuntimeError):
        tk.mint("u")
    with pytest.raises(tk.TokenError, match="token_invalid"):
        tk.verify(good, now=1)


def test_a_token_can_be_spent_once_and_the_list_forgets_old_ones():
    used = tk.UsedTokens()
    a = tk.verify(tk.mint("u", now=100)["token"], now=101)
    assert used.consume(a, now=101) is True and used.consume(a, now=102) is False
    assert len(used) == 1
    b = tk.verify(tk.mint("v", now=500)["token"], now=501)
    assert used.consume(b, now=501) and len(used) == 1          # the first one expired, so it was dropped


# ---- POST /v1/tokens -----------------------------------------------------------------------------------
def test_minting_needs_the_api_key():
    c = TestClient(server.app)
    assert c.post("/v1/tokens", json={"external_user_id": "u"}).status_code == 401
    assert c.post("/v1/tokens", json={"external_user_id": "u"}, headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = c.post("/v1/tokens", json={"external_user_id": " u1 ", "hour": 7}, headers=KEY)
    assert ok.status_code == 200 and ok.headers["cache-control"] == "no-store"
    assert tk.verify(ok.json()["token"]).external_user_id == "u1"        # trimmed


def test_a_token_is_not_a_key():
    c = TestClient(server.app)
    token = c.post("/v1/tokens", json={"external_user_id": "u"}, headers=KEY).json()["token"]
    assert c.post("/v1/tokens", json={"external_user_id": "u"}, headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert c.get("/v1/tests/1", headers={"Authorization": f"Bearer {token}"}).status_code == 401      # results stay server-only


BAD_BODIES = [{}, {"external_user_id": ""}, {"external_user_id": "  "}, {"external_user_id": 5}, {"external_user_id": "x" * 121},
              {"external_user_id": "u", "hour": 24}, {"external_user_id": "u", "hour": "9"}, {"external_user_id": "u", "hour": True},
              [], "text", None]


@pytest.mark.parametrize("body", BAD_BODIES)
def test_minting_refuses_bad_input(body):
    r = TestClient(server.app).post("/v1/tokens", json=body, headers=KEY)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


def test_minting_refuses_a_body_that_is_not_json():
    r = TestClient(server.app).post("/v1/tokens", content=b"not json", headers=KEY)
    assert r.status_code == 400


def test_minting_without_a_secret_is_a_clear_503(monkeypatch):
    monkeypatch.delenv("TOKEN_SECRET")
    r = TestClient(server.app).post("/v1/tokens", json={"external_user_id": "u"}, headers=KEY)
    assert r.status_code == 503 and r.json()["error"]["code"] == "no_token_secret"


# ---- /v1/session?token= --------------------------------------------------------------------------------
def mint(c, **body):
    return c.post("/v1/tokens", json={"external_user_id": "student-7", **body}, headers=KEY).json()["token"]


def first_message(c, url, **kw):
    with c.websocket_connect(url, **kw) as ws:
        return ws.receive_json()


def test_a_browser_opens_a_test_with_a_token_and_no_key():
    c = TestClient(server.app)
    first = first_message(c, f"/v1/session?token={mint(c, hour=9)}")
    assert first["type"] == "test" and first["id"]


def test_the_test_belongs_to_the_candidate_named_in_the_token(monkeypatch):
    c = TestClient(server.app)
    seen = {}
    real = server.ExamSession

    def spy(*a, **kw):
        s = real(*a, **kw)
        seen["session"] = s
        return s

    monkeypatch.setattr(server, "ExamSession", spy)
    # the URL tries to name someone else and another hour: the token wins
    assert first_message(c, f"/v1/session?token={mint(c, hour=9)}&external_user_id=someone-else&hour=3")["type"] == "test"
    assert seen["session"].external_user_id == "student-7" and seen["session"].hour == 9


def test_a_token_opens_one_test_only():
    c = TestClient(server.app)
    token = mint(c)
    assert first_message(c, f"/v1/session?token={token}")["type"] == "test"
    again = first_message(c, f"/v1/session?token={token}")
    assert again["type"] == "error" and again["code"] == "token_used"


@pytest.mark.parametrize("bad", ["", "abc", "a.b", "x" * 3000])
def test_a_bad_token_is_told_why_and_nothing_starts(bad):
    c = TestClient(server.app)
    first = first_message(c, f"/v1/session?token={bad}")
    assert first["type"] == "error" and first["code"] == "token_invalid" and not server.SESSIONS


def test_an_expired_token_says_so(monkeypatch):
    c = TestClient(server.app)
    token = mint(c)
    real = tk.time.time
    monkeypatch.setattr(tk.time, "time", lambda: real() + 121)
    assert first_message(c, f"/v1/session?token={token}")["code"] == "token_expired"


def test_a_refused_start_does_not_spend_the_token(monkeypatch):
    c = TestClient(server.app)
    token = mint(c)
    monkeypatch.setattr(server, "MAX_SESSIONS", 0)                      # the service is full: closed with 1013 at once
    with pytest.raises(Exception):
        first_message(c, f"/v1/session?token={token}")
    monkeypatch.setattr(server, "MAX_SESSIONS", 6)
    assert first_message(c, f"/v1/session?token={token}")["type"] == "test"      # the same token still works once there is room


def test_the_server_to_server_key_still_works():
    c = TestClient(server.app)
    assert first_message(c, "/v1/session?external_user_id=u1&hour=9", headers=KEY)["type"] == "test"
    with pytest.raises(Exception):
        first_message(c, "/v1/session?external_user_id=u1")             # neither key nor token: refused at the upgrade


def test_the_token_works_on_the_public_port_too():
    import worker.public as public

    c = TestClient(public.PublicGate(server.app))
    token = c.post("/v1/tokens", json={"external_user_id": "u"}, headers=KEY).json()["token"]
    assert first_message(c, f"/v1/session?token={token}")["type"] == "test"
