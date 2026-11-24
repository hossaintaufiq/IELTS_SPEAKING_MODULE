"""Pieces of the service API (docs/API_CONTRACT_V1.md) that do not need the voice models: API-key check and saved-test lookup.

Keys come from SERVICE_API_KEYS (comma separated, one per caller, so one can be revoked on its own). With no key configured the /v1
routes refuse every request: a service that was started without keys must not be open to anyone who finds the address.
"""
from __future__ import annotations

import hmac
import json
import os
import re
from pathlib import Path

from fastapi.responses import JSONResponse

from worker import session as sess

API_VERSION = "1"
TEST_ID = re.compile(r"^\d{1,8}$")      # an ExamSession.test_id; it becomes part of a file name, so nothing else is accepted


def configured_keys() -> list[str]:
    return [k.strip() for k in os.getenv("SERVICE_API_KEYS", "").split(",") if k.strip()]


def check_bearer(header: str | None) -> str:
    """'ok' | 'no_keys' (service has no key configured) | 'bad' (missing, malformed or wrong key)."""
    keys = configured_keys()
    if not keys:
        return "no_keys"
    scheme, _, token = (header or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return "bad"
    token = token.strip()
    ok = False
    for key in keys:                    # compare against every key (no early exit), in constant time
        ok |= hmac.compare_digest(token.encode(), key.encode())
    return "ok" if ok else "bad"


def error(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


def auth_error(verdict: str) -> JSONResponse | None:
    if verdict == "ok":
        return None
    if verdict == "no_keys":
        return error(503, "no_keys_configured", "The service has no API key configured")
    return error(401, "unauthorized", "Missing or invalid API key", {"WWW-Authenticate": "Bearer"})


def run_file(test_id: str) -> Path | None:
    """The saved record of a finished or aborted test, or None."""
    if not TEST_ID.match(test_id) or not sess.RUNS.exists():
        return None
    found = sorted(sess.RUNS.glob(f"run_*_{test_id}.json"))
    return found[-1] if found else None


def summary(record: dict) -> dict:
    return {"id": record.get("test_id"), "external_user_id": record.get("external_user_id", ""), "status": record.get("status", "aborted"),
            "started_at": record.get("started_at"), "ended_at": record.get("ended_at"), "end_reason": record.get("end_reason", "")}


def load_record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
