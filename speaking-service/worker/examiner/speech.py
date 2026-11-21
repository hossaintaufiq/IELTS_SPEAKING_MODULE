"""Judging what the speech recogniser handed us: noise, unfinished sentences, repeat requests.

Whisper invents short phrases on silence and background noise ("you", "Thank you.", "Thanks for
watching"). A candidate who pauses mid-sentence ends in a connecting word ("...and"), and the
examiner should wait for them. And only a real request ("Sorry?", "Can you repeat that?") may make
the examiner repeat a question.
"""
from __future__ import annotations

import re

# Phrases Whisper typically hallucinates on silence/noise. "yes", "no", "okay" are real answers, so not here.
HALLUCINATIONS = {
    "you", "thank you", "thanks", "thanks for watching", "thank you for watching", "thank you so much",
    "bye", "bye bye", "goodbye", "hmm", "mm", "mhm", "uh", "um", "ah", "oh", "huh", "the", "i", "so",
    "please subscribe", "subtitles by the amara.org community",
}
_HALLU_PATTERNS = re.compile(r"^(subtitles? by|translated by|transcribed by|www\.|https?://|\[|\(|♪|music)", re.I)

# Words a speaker says when they are not done yet.
UNFINISHED_LAST_WORDS = {
    "and", "but", "because", "so", "or", "then", "also", "like", "that", "which", "when", "if", "um", "uh", "er",
    "well", "the", "a", "an", "to", "of", "my", "is", "are", "was", "with", "for", "in", "on", "at", "as",
}

_REPEAT = re.compile(
    r"\b(sorry|pardon|repeat|say (?:that|it) again|once more|come again|didn'?t (?:hear|catch|get|understand)|"
    r"did not (?:hear|catch|understand)|can'?t hear|what do you mean|what was (?:the|that)|could you (?:say|repeat)|"
    r"can you (?:say|repeat)|i don'?t understand|not clear|what did you say)\b", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' .]", "", text.lower())).strip(" .")


def is_noise(text: str) -> bool:
    """True for empty text and for the stock phrases Whisper hallucinates on silence or noise."""
    raw = text.strip()
    n = _norm(raw)
    return not n or n in HALLUCINATIONS or bool(_HALLU_PATTERNS.match(raw))


def looks_unfinished(text: str) -> bool:
    """True if the candidate probably has more to say (ends mid-sentence)."""
    raw = text.strip()
    if raw.endswith((",", "-", "–", "…", "...")):
        return True
    words = _norm(raw).split()
    return bool(words) and words[-1] in UNFINISHED_LAST_WORDS


def is_repeat_request(text: str) -> bool:
    """True only if the candidate really asked the examiner to repeat or explain the question."""
    t = text.strip()
    return len(t.split()) <= 12 and bool(_REPEAT.search(t) or re.fullmatch(r"(what|huh)\??", t.strip(" ."), re.I))
