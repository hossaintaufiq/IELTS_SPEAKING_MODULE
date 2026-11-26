"""Overload safety: say "not now" before the GPU is in trouble, instead of letting the examiner go quiet.

The first GPU test (docs/GPU_TEST_2026-11-24.md) showed what overload looks like on one 24 GB card: up to about 26 tests at once nothing
failed; at 29 the reply delay doubled and GPU memory reached 23.6 of 24 GB; from 32 the examiner stopped answering about half the answers
while the sessions stayed connected. Afterwards GPU memory stayed at 23 GB with no test running, and the next test was slower.

This module keeps that from reaching a student. A new test is refused (WebSocket close 1013, the caller retries or routes elsewhere) when

  full        the number of running tests reached MAX_SESSIONS (which is itself kept at or below SAFE_MAX_SESSIONS, default 20)
  gpu_memory  free GPU memory is below GPU_MIN_FREE_MB (default 1500)
  slow        the recent reply delay is too high: the 95th percentile of the last REPLY_WINDOW_S seconds (default 60), with at least
              REPLY_MIN_SAMPLES replies (default 10), is above SLOW_P95_S (default 12); it clears again below SLOW_CLEAR_P95_S (default 8)
  restarting  the service is about to restart itself to give the GPU memory back (see watch_step)

Tests that are already running are never touched. Every number above is a first guess from one measurement series: the next GPU session
tunes them (/api/monitor shows the live values under "load").

Memory that stays high after an overload: when no test has run for a while the service first asks Python and PyTorch to release what they
can (`gpu_cleanup`); if the card is still more than RECYCLE_EXTRA_MB (default 3000) above what it used when the models had just been
loaded (read before the first test is accepted),
and RECYCLE_ON_LEAK=1, it exits with code 75 and the start script starts it again (models reload; /health says `ready: false` meanwhile).
It never does this while a test is running, and a fresh start measures a fresh baseline, so it cannot restart in a loop.
"""
from __future__ import annotations

import gc
import logging
import math
import os
import subprocess
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass

log = logging.getLogger("speaking.load")

RESTART_EXIT_CODE = 75
GPU_READING_MAX_AGE_S = 30.0         # an older reading is treated as unknown (the guard then does not block on it)


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def safe_max_sessions(requested: int) -> int:
    """MAX_SESSIONS, kept at or below SAFE_MAX_SESSIONS (default 20; the 24 GB card broke at 29). ALLOW_UNSAFE_MAX_SESSIONS=1 lifts it
    (the load test uses it to find the breaking point on purpose)."""
    ceiling = int(_float("SAFE_MAX_SESSIONS", 20))
    if requested > ceiling and os.getenv("ALLOW_UNSAFE_MAX_SESSIONS") != "1":
        log.warning("MAX_SESSIONS=%d is above the safe ceiling %d, using %d (ALLOW_UNSAFE_MAX_SESSIONS=1 to override)", requested, ceiling, ceiling)
        return ceiling
    return requested


def read_gpu_memory() -> tuple[int, int] | None:
    """(used MB, total MB) of GPU `GPU_INDEX` (default 0) from nvidia-smi, or None when there is no NVIDIA GPU or it does not answer."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits", "-i", os.getenv("GPU_INDEX", "0")],
                             capture_output=True, text=True, timeout=5, check=True).stdout
        used, total = (int(float(x)) for x in out.strip().splitlines()[0].split(","))
        return (used, total) if total > 0 else None
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def gpu_cleanup() -> None:
    """Hand back what Python and PyTorch are holding (if PyTorch is loaded at all). Models and the LLM stay."""
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            log.exception("torch.cuda.empty_cache failed")


@dataclass(frozen=True)
class Decision:
    ok: bool
    reason: str = ""           # "" | full | gpu_memory | slow | restarting
    message: str = ""          # the WebSocket close reason


class LoadGuard:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._delays: deque[tuple[float, float]] = deque()
        self._slow = False
        self._gpu: tuple[int, int] | None = None
        self._gpu_at = 0.0
        self.refused: Counter = Counter()
        self.restarting = False
        # for watch_step
        self.baseline_mb: int | None = None
        self._had_test = False              # a test has been admitted or seen: from then on the memory in use is no longer "clean"
        self._idle_since: float | None = None
        self._cleaned = False

    # ---- settings (read when used, so they can be changed without a restart in tests) ------------
    @staticmethod
    def window_s() -> float:
        return max(5.0, _float("REPLY_WINDOW_S", 60))

    @staticmethod
    def min_samples() -> int:
        return max(3, int(_float("REPLY_MIN_SAMPLES", 10)))

    @staticmethod
    def slow_p95_s() -> float:
        return _float("SLOW_P95_S", 12.0)

    @staticmethod
    def slow_clear_s() -> float:
        return min(_float("SLOW_CLEAR_P95_S", 8.0), LoadGuard.slow_p95_s())

    @staticmethod
    def gpu_min_free_mb() -> int:
        return int(_float("GPU_MIN_FREE_MB", 1500))

    # ---- reply delay -----------------------------------------------------------------------------
    def record_delay(self, seconds: float) -> None:
        """One reply: the time from the candidate stopping to the examiner's first audio."""
        if seconds >= 0:
            self._delays.append((self.clock(), seconds))

    def reply_p95(self) -> tuple[float | None, int]:
        """(95th percentile, number of replies) over the last window."""
        cutoff = self.clock() - self.window_s()
        while self._delays and self._delays[0][0] < cutoff:
            self._delays.popleft()
        values = sorted(s for _, s in self._delays)
        if not values:
            return None, 0
        return values[max(0, math.ceil(0.95 * len(values)) - 1)], len(values)

    def slow(self) -> bool:
        p95, n = self.reply_p95()
        if n < self.min_samples() or p95 is None:
            self._slow = False
        elif p95 > self.slow_p95_s():
            if not self._slow:
                log.warning("replies are slow (p95 %.1f s over %d replies): new tests are refused until they recover", p95, n)
            self._slow = True
        elif p95 <= self.slow_clear_s():
            self._slow = False
        return self._slow

    # ---- GPU memory ------------------------------------------------------------------------------
    def update_gpu(self, reading: tuple[int, int] | None) -> None:
        self._gpu, self._gpu_at = reading, self.clock()

    def gpu(self) -> tuple[int, int] | None:
        return self._gpu if self._gpu is not None and self.clock() - self._gpu_at <= GPU_READING_MAX_AGE_S else None

    def gpu_low(self) -> bool:
        reading = self.gpu()
        return reading is not None and reading[1] - reading[0] < self.gpu_min_free_mb()

    # ---- the decision ----------------------------------------------------------------------------
    def admit(self, running: int, max_sessions: int) -> Decision:
        """May one more test start? Cheap: no I/O (the GPU is read by the watcher, not here)."""
        if self.restarting:
            d = Decision(False, "restarting", "Service is restarting, try again in a minute")
        elif running >= max_sessions:
            d = Decision(False, "full", f"Server is full ({running} tests running)")
        elif self.gpu_low():
            d = Decision(False, "gpu_memory", "Server is busy, try again in a minute")
        elif self.slow():
            d = Decision(False, "slow", "Server is busy, try again in a minute")
        else:
            self._had_test = True
            return Decision(True)
        self.refused[d.reason] += 1
        return d

    def accepting(self, running: int, max_sessions: int) -> Decision:
        """Like admit, without counting a refusal: what /health reports."""
        before, had_test = Counter(self.refused), self._had_test
        d = self.admit(running, max_sessions)
        self.refused, self._had_test = before, had_test
        return d

    # ---- the watcher: memory that is not given back ----------------------------------------------
    def record_baseline(self, reading: tuple[int, int] | None) -> None:
        """The memory in use when the models have just been loaded: what "clean" means. The server calls this before it accepts
        the first test. It is kept once set, and never taken after a test has run, because memory a test leaves behind is exactly
        what the restart is for."""
        if reading is None or self.baseline_mb is not None or self._had_test:
            return
        self.baseline_mb = reading[0]
        log.info("GPU memory baseline %d MB", self.baseline_mb)

    def watch_step(self, running: int, reading: tuple[int, int] | None, *, ready: bool, recycle: bool | None = None, cleanup=gpu_cleanup) -> str | None:
        """One look at the GPU, every few seconds. Returns "recycle" when the service should restart itself, else None."""
        now = self.clock()
        self.update_gpu(reading)
        if running > 0:
            self._had_test = True
            self._idle_since, self._cleaned = None, False
            return None
        if self._idle_since is None:
            self._idle_since = now
        idle = now - self._idle_since
        if reading is None or not ready:
            return None
        used = reading[0]
        if self.baseline_mb is None:
            if idle >= _float("BASELINE_IDLE_S", 30):         # only if the start-up reading failed, and still no test has run
                self.record_baseline(reading)
            return None
        if not self._cleaned and idle >= _float("CLEANUP_IDLE_S", 20):
            self._cleaned = True
            cleanup()
            return None                                       # judge on the next reading, after the cleanup had its effect
        leaked = used - self.baseline_mb
        if (self._cleaned and idle >= _float("RECYCLE_IDLE_S", 60) and leaked >= _float("RECYCLE_EXTRA_MB", 3000)
                and (os.getenv("RECYCLE_ON_LEAK") == "1" if recycle is None else recycle)):
            self.restarting = True                            # from this moment no test is admitted (see admit)
            log.warning("GPU memory is %d MB above its start-up level with no test running: restarting the service to free it", leaked)
            return "recycle"
        return None

    def stats(self) -> dict:
        p95, n = self.reply_p95()
        gpu = self.gpu()
        return {"slow": self._slow, "reply_p95_s": None if p95 is None else round(p95, 2), "replies_in_window": n,
                "slow_above_s": self.slow_p95_s(), "gpu_used_mb": gpu[0] if gpu else None, "gpu_total_mb": gpu[1] if gpu else None,
                "gpu_min_free_mb": self.gpu_min_free_mb(), "gpu_baseline_mb": self.baseline_mb, "restarting": self.restarting,
                "refused": dict(self.refused)}


GUARD = LoadGuard()
