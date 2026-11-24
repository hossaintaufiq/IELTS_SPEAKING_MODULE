"""Control-plane API for the Node app (draft contract: docs/API_CONTRACT.md).

STATUS: in-memory store and FakeProvisioner only. No database, no real GPU, no webhooks sent, no
audio WebSocket yet. Good enough to agree the contract with the Node team and to test capacity
and token logic.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from control_plane.gpu_provisioner.base import CapacityError, FakeProvisioner, GpuProvisioner, LeaseState

SERVICE_KEY = os.getenv("SERVICE_API_KEY", "dev-service-key")
TOKEN_SECRET = os.getenv("TOKEN_SECRET", "dev-token-secret").encode()
TOKEN_TTL_S = 300


def sign_token(payload: dict, secret: bytes = TOKEN_SECRET) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str, secret: bytes = TOKEN_SECRET, now: float | None = None) -> dict:
    try:
        body, sig = token.rsplit(".", 1)
        good = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            raise ValueError("bad signature")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception as e:  # any malformed token is simply invalid
        raise ValueError("invalid token") from e
    if (now if now is not None else time.time()) > payload["exp"]:
        raise ValueError("token expired")
    return payload


class LeaseIn(BaseModel):
    seats: int = Field(ge=1, le=64)
    duration_s: int = Field(ge=60, le=4 * 3600)


class ExtendIn(BaseModel):
    extra_s: int = Field(ge=60, le=3600)


class SessionIn(BaseModel):
    lease_id: str
    external_user_id: str = Field(min_length=1, max_length=128)


def create_app(provisioner: GpuProvisioner | None = None) -> FastAPI:
    app = FastAPI(title="Speaking Service")
    prov = provisioner or FakeProvisioner(max_seats=12)
    sessions: dict[str, dict] = {}

    def auth(authorization: str = Header(default="")):
        ok = hmac.compare_digest(authorization, f"Bearer {SERVICE_KEY}")
        if not ok:
            raise HTTPException(401, "invalid service key")

    def lease_view(lease):
        return {"lease_id": lease.id, "state": lease.state.value, "seats": lease.seats,
                "expires_at": lease.expires_at, "worker_url": lease.worker_url}

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/leases", status_code=201, dependencies=[Depends(auth)])
    def create_lease(body: LeaseIn):
        try:
            return lease_view(prov.acquire(body.seats, body.duration_s))
        except CapacityError as e:
            raise HTTPException(409, str(e), headers={"Retry-After": "60"})

    @app.get("/leases/{lease_id}", dependencies=[Depends(auth)])
    def get_lease(lease_id: str):
        try:
            return lease_view(prov.poll(lease_id))
        except KeyError:
            raise HTTPException(404, "unknown lease")

    @app.post("/leases/{lease_id}/extend", dependencies=[Depends(auth)])
    def extend_lease(lease_id: str, body: ExtendIn):
        try:
            return lease_view(prov.extend(lease_id, body.extra_s))
        except KeyError:
            raise HTTPException(404, "unknown lease")
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.delete("/leases/{lease_id}", dependencies=[Depends(auth)])
    def delete_lease(lease_id: str):
        try:
            return lease_view(prov.release(lease_id))
        except KeyError:
            raise HTTPException(404, "unknown lease")

    @app.post("/sessions", status_code=201, dependencies=[Depends(auth)])
    def create_session(body: SessionIn):
        try:
            lease = prov.poll(body.lease_id)
        except KeyError:
            raise HTTPException(404, "unknown lease")
        if lease.state != LeaseState.READY:
            raise HTTPException(409, f"lease is {lease.state.value}, not ready", headers={"Retry-After": "10"})
        active = sum(1 for s in sessions.values() if s["lease_id"] == lease.id and s["state"] == "active")
        if active >= lease.seats:
            raise HTTPException(429, "all seats in use", headers={"Retry-After": "30"})
        sid = str(uuid.uuid4())
        exp = time.time() + TOKEN_TTL_S
        sessions[sid] = {"session_id": sid, "lease_id": lease.id,
                         "external_user_id": body.external_user_id, "state": "active"}
        token = sign_token({"sid": sid, "lease": lease.id, "exp": exp})
        return {"session_id": sid, "ws_token": token, "ws_url": f"{lease.worker_url}/ws/{sid}"}

    @app.get("/sessions/{session_id}", dependencies=[Depends(auth)])
    def get_session(session_id: str):
        s = sessions.get(session_id)
        if not s:
            raise HTTPException(404, "unknown session")
        return s

    return app


app = create_app()
