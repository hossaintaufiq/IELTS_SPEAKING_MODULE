"""Telling "I want to finish the test" from an ordinary answer, and reading the answer to "finish or continue?".

Only short utterances count: a long answer that happens to contain the word "end" is still an answer.
"""
from __future__ import annotations

import re

_FINISH_REQUEST = [re.compile(p, re.I) for p in (
    # "finish the test", "I want to end this exam", "stop the speaking test"
    r"\b(?:finish|end|stop|quit|terminate|complete|cancel)\b.{0,25}\b(?:test|exam|examination|interview|session)\b",
    # "let's finish", "I want to finish", "I would like to stop", "I need to leave"
    r"\b(?:i|we)\s*(?:want|wanna|would like|'d like|need|have|am going|'m going)\s*(?:to\s*)?(?:finish|end|stop|quit|leave)\b",
    r"\blet'?s\s*(?:finish|end|stop|quit|call it)\b",
    r"\b(?:finish|end|stop)\s*(?:it|this)?\s*now\b|\bfinish\s*(?:it|this)\b",
    # "I don't want to continue", "I do not want to go on"
    r"\b(?:i|we)\s*(?:don'?t|do not|no longer)\s*want\s*to\s*(?:continue|go on|carry on|do this|take (?:this|the))\b",
    # "can I stop?", "could we finish?"
    r"\b(?:can|could|may)\s*(?:i|we)\s*(?:please\s*)?(?:stop|finish|end|leave|quit)\b",
    # "I'm done." (only when that is the whole answer), "that's enough"
    r"^\W*(?:i'?m|i am|we are|we're)\s*(?:done|finished)(?:\s*(?:now|with (?:this|the test|it)))?\W*$",
    r"\bthat'?s enough\b",
)]


def is_finish_request(text: str) -> bool:
    t = text.strip()
    if re.match(r"^(?:what|how|when|where|why|who|which)\b", t, re.I):      # a question about the test is not a request to stop it
        return False
    return len(t.split()) <= 16 and any(p.search(t) for p in _FINISH_REQUEST)


_NEGATED_FINISH = re.compile(r"\b(?:not|don'?t|do not|never)\s+(?:want to\s+|wish to\s+|like to\s+)?(?:finish|end|stop|quit|leave)\b", re.I)
_CONTINUE_WORDS = re.compile(r"\b(?:continue|go on|carry on|keep going|proceed|resume|go ahead|let'?s go)\b", re.I)
_FINISH_WORDS = re.compile(r"\b(?:finish|finished|end|stop|quit|leave|over|enough|done)\b", re.I)
_PLAIN_NO = re.compile(r"^\W*(?:no|nope|nah)\b", re.I)


def _last(rx: re.Pattern, text: str) -> int:
    ms = list(rx.finditer(text))
    return ms[-1].start() if ms else -1


def finish_answer(text: str) -> str:
    """The reply to "Do you want to finish the speaking test, or would you like to continue?":
    'finish', 'continue', or 'unclear' (a bare "yes" could mean either). When both words are said, the later one wins."""
    t = text.strip()
    if _NEGATED_FINISH.search(t):
        return "continue"
    f, c = _last(_FINISH_WORDS, t), _last(_CONTINUE_WORDS, t)
    if f < 0 and c < 0:
        return "continue" if _PLAIN_NO.match(t) else "unclear"
    return "finish" if f > c else "continue"


# ---- "That's all." at the end of the Part 2 talk (a candidate who is finished must be allowed to say so) -------------
_DONE_TALKING = re.compile(
    r"\b(?:that'?s|that is) (?:all|it|everything|about it)\b|\bi(?:'ve| have| am|'m) (?:finished|done)\b|"
    r"\b(?:nothing|no) (?:more|else)\b|\bthat'?s the end\b", re.I)
_AFTER_DONE = {"now", "thank", "thanks", "you", "sir", "madam", "please", "so", "for", "listening", "and", "that's", "all", "ok", "okay"}


def is_done_talking(text: str) -> bool:
    """True if the talk ends with a phrase like "that's all" / "I'm finished" / "nothing more" (optionally "thank you sir")."""
    t = text.strip()
    if len(t.split()) < 2:
        return False
    for m in _DONE_TALKING.finditer(t):
        after = re.findall(r"[a-z']+", t[m.end():].lower())
        if len(after) <= 3 and all(w in _AFTER_DONE for w in after):
            return True
    return False
