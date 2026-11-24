"""Has the candidate already answered this question in something they said earlier?

The question bank is asked in order. When the LLM is not used (or fails), the bank must not ask "What time do you
usually get up?" right after the candidate said "I wake up at 6 a.m." This is a deliberately cautious check: it only
says "already answered" when it is fairly sure, because wrongly skipping a question costs less than asking it twice.
"""
from __future__ import annotations

import re

_TIME_QUESTION = re.compile(r"\bwhat time\b|\bwhen do you (?:usually |normally )?(?:get up|wake up|go to bed|go to sleep|start|finish)\b", re.I)
_CLOCK_TIME = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?\s?m\.?|p\.?\s?m\.?|o'?clock)|\bat \d{1,2}(?::\d{2})?\b", re.I)

_STOP = set("""what when where which who whom whose why how does have your with like would could should ever much many some thing
  things kind most other more than that this those these they them from been into about there their usually often really
  sometimes always never enjoy think feel want""".split())
OVERLAP = 0.6          # share of the question's own content words that must already appear in what they said
MIN_WORDS = 3          # and the question must have at least this many content words, or the check is too weak to trust


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def content_words(text: str) -> list[str]:
    words = re.findall(r"[a-z']+", text.lower())
    return list(dict.fromkeys(_stem(w) for w in words if len(w) >= 4 and w not in _STOP))


def already_answered(question: str, candidate_text: str) -> bool:
    """True if `candidate_text` (everything the candidate has said so far) clearly covers `question`."""
    if not candidate_text.strip():
        return False
    if _TIME_QUESTION.search(question) and _CLOCK_TIME.search(candidate_text):
        return True                                           # "What time do you get up?" ... "I wake up at 6 a.m."
    q = content_words(question)
    if len(q) < MIN_WORDS:
        return False
    said = set(content_words(candidate_text))
    return sum(1 for w in q if w in said) / len(q) >= OVERLAP
