"""How long the examiner waits after a candidate's answer before speaking.

Bangladeshi candidates (and most learners) think aloud: a 2-3 second silence in the middle of an
answer is normal, so a fixed 1-2 s pause makes the examiner jump in with the next question. The
wait therefore adapts to what was said:

  - short answer ("Yes.", "I live in Dhaka.")           -> they usually go on to explain: wait longer
  - ends mid-sentence ("...and", "...because", "I mean") -> wait longer
  - "let me think", "how can I say", "just a moment"     -> they asked for time: wait much longer
  - long, complete sentence                              -> they are probably done: wait a little less

The wait counts from the moment the transcript arrives; the voice-activity detector and the
recogniser have already used about a second before that.
"""
from __future__ import annotations

import re

from worker.examiner.speech import looks_unfinished

# "Give me a moment" in the ways learners say it.
THINKING = re.compile(
    r"\b(let me think|let me see|wait a (?:moment|minute|second)|just a (?:moment|minute|second)|"
    r"one (?:moment|minute|second)|give me (?:a )?(?:moment|minute|second|time)|how (?:can|do|to) i say|how to say|"
    r"what (?:is|do you call) it|i am thinking|i'm thinking|let me recall|let me remember)\b", re.I)

SHORT_WORDS = 5          # an answer this short is probably the start of a longer one
LONG_WORDS = 25


def wait_seconds(text: str, base: float, *, short_extra: float, unfinished_extra: float, think_extra: float,
                 max_wait: float, adaptive: bool = True) -> float:
    """Seconds to wait after `text` (the candidate's answer so far) before the examiner speaks."""
    words = len(text.split())
    wait = base
    unfinished = looks_unfinished(text)
    if adaptive:
        if words <= SHORT_WORDS:
            wait += short_extra
        if unfinished:
            wait += unfinished_extra
        if words <= 14 and THINKING.search(text):
            wait += think_extra
        elif words >= LONG_WORDS and not unfinished and text.rstrip().endswith((".", "?", "!")):
            wait *= 0.75
    elif unfinished:
        wait += unfinished_extra
    return min(wait, max_wait)
