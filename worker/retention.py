"""How long saved tests are kept (decision D9).

Each test leaves a record (runs/run_<date>_<time>_<id>.json, with the transcript) and the candidate's recording (.wav). They are
deleted RETENTION_DAYS after they were saved (default 30; 0 keeps them for ever). The age comes from the date in the file name, so
copying or restoring files does not reset it. Only files named like that, directly in the runs folder, are ever touched.

Server logs are not covered here: they are limited by the way the service is run.
"""
from __future__ import annotations

import logging
import math
import os
import re
import time
from pathlib import Path

log = logging.getLogger("speaking.retention")

DEFAULT_DAYS = 30.0
PURGE_EVERY_S = 3600
RUN_FILE = re.compile(r"^run_(\d{8}_\d{6})(?:_\d{1,8})?\.(?:json|wav)$")


def retention_days() -> float:
    """RETENTION_DAYS; 0 means keep for ever. A value that cannot be understood also keeps everything: deleting is not undone."""
    text = os.getenv("RETENTION_DAYS", "").strip()
    if not text:
        return DEFAULT_DAYS
    try:
        days = float(text)
    except ValueError:
        days = math.nan
    if not days >= 0:                                     # negative, or not a number at all
        log.warning("RETENTION_DAYS=%r is not a number of days: nothing is deleted", text)
        return 0.0
    return days


def purge(runs: Path, days: float, now: float | None = None) -> list[str]:
    """Delete the saved tests older than `days`. Returns the names of the deleted files."""
    if days <= 0 or not runs.is_dir():
        return []
    cutoff = (time.time() if now is None else now) - days * 86400
    deleted = []
    for path in sorted(runs.iterdir()):
        match = RUN_FILE.match(path.name)
        if not match or not path.is_file():
            continue
        try:
            saved = time.mktime(time.strptime(match[1], "%Y%m%d_%H%M%S"))
            if saved >= cutoff:
                continue
            path.unlink()
        except (ValueError, OverflowError):               # digits that are not a date: not one of ours
            continue
        except OSError as e:
            log.warning("could not delete %s: %s", path.name, e)
            continue
        deleted.append(path.name)
    return deleted
