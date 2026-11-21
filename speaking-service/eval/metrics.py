"""Evaluation metrics: word error rate for STT and latency percentiles for the pipeline."""
from __future__ import annotations

import re
from dataclasses import dataclass


def normalize(text: str) -> list[str]:
    """Lowercase, drop punctuation (keep apostrophes), split into words."""
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split()


@dataclass
class WerResult:
    wer: float
    substitutions: int
    deletions: int
    insertions: int
    ref_words: int


def wer(reference: str, hypothesis: str) -> WerResult:
    ref, hyp = normalize(reference), normalize(hypothesis)
    # Each cell: (cost, subs, dels, ins) for aligning ref[:i] with hyp[:j].
    prev = [(j, 0, 0, j) for j in range(len(hyp) + 1)]
    for i in range(1, len(ref) + 1):
        cur = [(i, 0, i, 0)]
        for j in range(1, len(hyp) + 1):
            if ref[i - 1] == hyp[j - 1]:
                cur.append(prev[j - 1])
                continue
            s, d, n = prev[j - 1], prev[j], cur[j - 1]
            cur.append(min(
                (s[0] + 1, s[1] + 1, s[2], s[3]),
                (d[0] + 1, d[1], d[2] + 1, d[3]),
                (n[0] + 1, n[1], n[2], n[3] + 1),
            ))
        prev = cur
    cost, subs, dels, ins = prev[-1]
    rate = cost / len(ref) if ref else float(bool(hyp))
    return WerResult(rate, subs, dels, ins, len(ref))


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile, p in [0, 100]."""
    if not values:
        raise ValueError("no values")
    xs = sorted(values)
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def latency_summary(samples_s: list[float]) -> dict[str, float]:
    return {
        "n": len(samples_s),
        "p50": percentile(samples_s, 50),
        "p95": percentile(samples_s, 95),
        "max": max(samples_s),
    }
