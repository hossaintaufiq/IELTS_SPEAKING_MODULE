"""Keeps live captions from taking the GPU away from the real answers.

A caption is a nicety: the final transcript comes from the main speech model. But every speaking student re-decodes their last few
seconds every second or so, so with many students captions can become the biggest load on the GPU and delay the examiner's reply.
Three limits, all settable by environment variable (the load test decides the right values):

  CAPTIONS=off              no captions at all (the small model is not even loaded)
  CAPTION_WINDOW_S=8        only the last N seconds of speech are re-decoded (was 15)
  CAPTION_INTERVAL_S=1.2    seconds between caption updates (was 0.9)
  CAPTION_MAX_CONCURRENT=2  at most N caption decodes at the same moment, in the whole server; a caption that finds them all busy is
                            skipped (the next one covers it). Real answers are never skipped.

Used from the event loop only, so it needs no lock.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("speaking.captions")


def enabled() -> bool:
    return os.getenv("CAPTIONS", "on").strip().lower() not in ("off", "0", "false", "no")


def window_s() -> float:
    return max(1.0, float(os.getenv("CAPTION_WINDOW_S", "8")))


def interval_s() -> float:
    return max(0.3, float(os.getenv("CAPTION_INTERVAL_S", "1.2")))


class CaptionBudget:
    def __init__(self, max_concurrent: int | None = None, warn_every: int = 50):
        self.max_concurrent = max(1, int(os.getenv("CAPTION_MAX_CONCURRENT", "2")) if max_concurrent is None else max_concurrent)
        self.warn_every = warn_every
        self.in_flight = self.decoded = self.skipped = 0

    def try_acquire(self) -> bool:
        """True if a caption decode may start now. Call release() when it ends."""
        if self.in_flight >= self.max_concurrent:
            self.skipped += 1
            if self.skipped % self.warn_every == 0:      # a WARNING reaches the monitoring page's failures feed
                log.warning("live captions are being skipped because the GPU is busy (%d skipped so far, %d decoded)", self.skipped, self.decoded)
            return False
        self.in_flight += 1
        return True

    def release(self) -> None:
        self.in_flight = max(0, self.in_flight - 1)
        self.decoded += 1

    def stats(self) -> dict:
        return {"enabled": enabled(), "window_s": window_s(), "interval_s": interval_s(), "max_concurrent": self.max_concurrent,
                "in_flight": self.in_flight, "decoded": self.decoded, "skipped": self.skipped}


BUDGET = CaptionBudget()
