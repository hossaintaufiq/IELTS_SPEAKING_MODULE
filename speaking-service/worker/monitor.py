"""What the monitoring page shows: the service as a whole (health, capacity), the tests running now, the recent tests, latency and failures.

Read only. It never touches a running test, and it never returns what anyone said: ids, phases, timings and error text only.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from pathlib import Path

STARTED = time.time()
SLOW_REPLY_S = float(os.getenv("MONITOR_SLOW_S", "3.0"))      # a reply slower than this (candidate stops -> first examiner audio) counts as slow
RECENT_RUNS = 100                                              # how many saved tests are read for the recent list and the latency figures


# ---- failures feed: warnings and errors logged by the service --------------------------------------------------
class RingHandler(logging.Handler):
    """Keeps the last warnings/errors of the 'speaking' loggers in memory, newest last."""

    def __init__(self, size: int = 200):
        super().__init__(level=logging.WARNING)
        self.rows: deque[dict] = deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
            if record.exc_info and record.exc_info[0]:
                text += f" [{record.exc_info[0].__name__}: {record.exc_info[1]}]"
            self.rows.append({"at": round(record.created, 2), "level": record.levelname, "source": record.name, "message": text[:300]})
        except Exception:        # logging must never break the service
            pass


FAILURES = RingHandler()


def install_failure_log() -> None:
    """Attach the ring to the 'speaking' logger once (the server imports this at start-up; tests may call it again)."""
    root = logging.getLogger("speaking")
    if FAILURES not in root.handlers:
        root.addHandler(FAILURES)        # the handler itself keeps only WARNING and above


def recent_failures(limit: int = 50) -> list[dict]:
    return list(FAILURES.rows)[-limit:][::-1]


# ---- numbers -------------------------------------------------------------------------------------------------
def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (p in 0-100); None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * p // 100))          # ceil without importing math
    return round(ordered[int(rank) - 1], 2)


def latency_stats(values: list[float]) -> dict:
    return {"n": len(values), "p50": percentile(values, 50), "p95": percentile(values, 95), "max": round(max(values), 2) if values else None,
            "slow": sum(1 for v in values if v > SLOW_REPLY_S), "slow_over_s": SLOW_REPLY_S}


# ---- live tests ----------------------------------------------------------------------------------------------
def live_rows(sessions: dict) -> list[dict]:
    rows = []
    for test_id, s in sessions.items():
        lat = [e["seconds"] for e in getattr(s, "log", []) if e.get("type") == "latency"]
        errors = [e for e in getattr(s, "log", []) if e.get("type") == "note" and str(e.get("text", "")).startswith("error in")]
        rows.append({
            "id": test_id, "user": getattr(s, "external_user_id", "") or "", "device": getattr(s, "device", "") or "",
            "status": getattr(s, "status", ""), "phase": getattr(s, "phase", ""), "started": bool(getattr(s, "started", False)),
            "elapsed_s": round(s.clock() - s.t0, 1), "mic_rms": round(float(getattr(s, "mic_rms", 0.0)), 4),
            "mic_chunks": getattr(s, "mic_chunks", 0), "last_reply_s": lat[-1] if lat else None,
            "slow_replies": sum(1 for v in lat if v > SLOW_REPLY_S), "errors": len(errors), "llm_error": getattr(s, "llm_error", "") or "",
        })
    rows.sort(key=lambda r: -r["elapsed_s"])
    return rows


# ---- saved tests ---------------------------------------------------------------------------------------------
_CACHE: dict[str, tuple[float, dict]] = {}       # file -> (modified time, summary): a saved test never changes, so it is read once


def summarise_run(record: dict, name: str) -> dict:
    events = record.get("events") or []
    lat = [float(x) for x in record.get("latencies_s") or []]
    errors = [e for e in events if e.get("type") == "note" and str(e.get("text", "")).startswith("error in")]
    stamps = [e["at"] for e in events if "at" in e]
    started = record.get("started_at") or (stamps[0] if stamps else None)
    ended = record.get("ended_at") or (stamps[-1] if stamps else None)
    status = record.get("status") or "unknown"       # saved before the service shell existed: no status
    slow = sum(1 for v in lat if v > SLOW_REPLY_S)
    problems = []
    if status in ("aborted", "failed"):
        problems.append(status)
    if errors:
        problems.append(f"{len(errors)} error{'s' if len(errors) > 1 else ''}")
    if slow:
        problems.append(f"{slow} slow repl{'ies' if slow > 1 else 'y'}")
    if record.get("mic_seconds") is not None and record.get("mic_rms", 1) < 0.003:
        problems.append("silent microphone")
    return {
        "run": name, "id": record.get("test_id") or name.rsplit("_", 1)[-1], "user": record.get("external_user_id", "") or "",
        "device": record.get("device", "") or "", "status": status, "end_reason": record.get("end_reason", "") or "",
        "started_at": started, "ended_at": ended, "duration_s": round(ended - started, 1) if started and ended else None,
        "latency": latency_stats(lat), "errors": len(errors), "problems": problems, "failed": bool(problems),
    }


def recent_runs(runs_dir: Path, limit: int = RECENT_RUNS) -> tuple[list[dict], list[float]]:
    """(summaries, every reply delay in them), newest first. Unreadable files are skipped, not fatal."""
    if not runs_dir.exists():
        return [], []
    files = sorted(runs_dir.glob("run_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:limit]
    seen: set[str] = set()
    out, delays = [], []
    for f in files:
        mtime = f.stat().st_mtime
        cached = _CACHE.get(str(f))
        if cached is None or cached[0] != mtime:
            try:
                record = json.loads(f.read_text(encoding="utf-8"))
                cached = (mtime, {"summary": summarise_run(record, f.stem), "delays": [float(x) for x in record.get("latencies_s") or []]})
            except (OSError, ValueError, TypeError):
                continue
            _CACHE[str(f)] = cached
        item = cached[1]
        if item["summary"]["id"] in seen:            # a finished test is saved twice (at the end and when the socket closes): list it once
            continue
        seen.add(item["summary"]["id"])
        out.append(item["summary"])
        delays.extend(item["delays"])
    return out, delays


def snapshot(*, sessions: dict, runs_dir: Path, max_tests: int, ready: bool, models_error: str, mock: bool, version: str,
             captions: dict | None = None) -> dict:
    runs, delays = recent_runs(runs_dir)
    counts = {"completed": 0, "aborted": 0, "failed": 0, "unknown": 0}
    for r in runs:
        counts[r["status"] if r["status"] in counts else "unknown"] += 1
    live = live_rows(sessions)
    return {
        "now": round(time.time(), 2),
        "server": {"ready": ready, "models_error": models_error, "mock": mock, "version": version, "uptime_s": round(time.time() - STARTED),
                   "running": sum(1 for r in live if r["phase"] != "done"), "max_tests": max_tests},
        "live": live,
        "latency": latency_stats(delays),
        "counts": counts,
        "recent": runs,
        "failures": recent_failures(),
        "captions": captions or {},       # live-caption limits and how many updates were decoded or skipped (worker/caption_budget.py)
    }
