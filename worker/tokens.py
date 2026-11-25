"""Short-lived signed tokens, so a student's browser can open a test without ever holding an API key.

Flow: ieltsup's server asks `POST /v1/tokens` (with its API key) for one candidate; it hands the token to that candidate's browser; the
browser opens `wss://.../v1/session?token=...`. The token says who the candidate is (`external_user_id`, `hour`) so the browser cannot
claim to be someone else, and it is good for ONE connection within `TOKEN_TTL_S` seconds (default 120), so a copy found in a URL, a proxy
log or a screenshot is of no use a minute later. The test itself can then run as long as it needs.

Format: `base64url(json payload) + "." + base64url(HMAC-SHA256(TOKEN_SECRET, payload part))`. No state is needed to check a signature;
the only state is the list of tokens already used, kept in memory (a restart forgets it, which can re-open a token for the rest of
its short life, never longer). To revoke every token at once, change TOKEN_SECRET and restart.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

SECRET_MIN_LEN = 32
TTL_DEFAULT_S = 120
TTL_MAX_S = 600
MAX_TOKEN_CHARS = 1024          # a real token is about 200 characters; anything bigger is not parsed at all
VERSION = 1


class TokenError(Exception):
    """`code` is what the caller is told: token_invalid, token_expired or token_used."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Claims:
    jti: str
    external_user_id: str
    hour: int | None
    exp: float


def secret() -> bytes | None:
    """TOKEN_SECRET, or None when it is missing or too short to be safe."""
    value = os.getenv("TOKEN_SECRET", "")
    return value.encode() if len(value) >= SECRET_MIN_LEN else None


def ttl_s() -> int:
    try:
        value = int(os.getenv("TOKEN_TTL_S", TTL_DEFAULT_S))
    except ValueError:
        value = TTL_DEFAULT_S
    return max(10, min(value, TTL_MAX_S))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(key: bytes, part: str) -> str:
    return _b64(hmac.new(key, part.encode(), hashlib.sha256).digest())


def mint(external_user_id: str, hour: int | None = None, *, now: float | None = None) -> dict:
    """A new token for one candidate. Raises RuntimeError when TOKEN_SECRET is not configured."""
    key = secret()
    if key is None:
        raise RuntimeError("TOKEN_SECRET is not set (at least 32 characters)")
    issued = time.time() if now is None else now
    ttl = ttl_s()
    payload = {"v": VERSION, "jti": secrets.token_urlsafe(12), "sub": external_user_id, "iat": int(issued), "exp": int(issued) + ttl}
    if hour is not None:
        payload["hour"] = hour
    part = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return {"token": f"{part}.{_sign(key, part)}", "expires_at": payload["exp"], "expires_in": ttl}


def verify(token: str, *, now: float | None = None) -> Claims:
    """The claims of a genuine, unexpired token. Raises TokenError otherwise. Does not mark it used (see UsedTokens)."""
    key = secret()
    if key is None or not isinstance(token, str) or len(token) > MAX_TOKEN_CHARS or token.count(".") != 1:
        raise TokenError("token_invalid")
    part, _, signature = token.partition(".")
    if not hmac.compare_digest(signature.encode(), _sign(key, part).encode()):        # signature first: nothing unsigned is ever read
        raise TokenError("token_invalid")
    try:
        payload = json.loads(_unb64(part))
        jti, sub, exp, hour = payload["jti"], payload["sub"], float(payload["exp"]), payload.get("hour")
        if payload.get("v") != VERSION or not isinstance(jti, str) or not isinstance(sub, str) or not sub:
            raise ValueError
        if hour is not None and (not isinstance(hour, int) or isinstance(hour, bool) or not 0 <= hour <= 23):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise TokenError("token_invalid") from None
    if (time.time() if now is None else now) >= exp:
        raise TokenError("token_expired")
    return Claims(jti=jti, external_user_id=sub, hour=hour, exp=exp)


class UsedTokens:
    """Tokens already spent. `consume` is atomic (no await inside), so two sockets with one token cannot both win."""

    def __init__(self):
        self._seen: dict[str, float] = {}

    def consume(self, claims: Claims, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        self._seen = {j: e for j, e in self._seen.items() if e > current}       # an expired token is refused anyway: forget it
        if claims.jti in self._seen:
            return False
        self._seen[claims.jti] = claims.exp
        return True

    def __len__(self) -> int:
        return len(self._seen)


USED = UsedTokens()
