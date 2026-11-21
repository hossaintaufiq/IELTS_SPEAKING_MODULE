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


# Questions aimed at the examiner instead of answering: "Are you an AI?", "What's your name?", "How am I doing?"
_OFF_TOPIC = [re.compile(p, re.I) for p in (
    r"\b(are|r) you (an? )?(ai|a\.i\.|artificial|robot|bot|machine|computer|program|human|real|person|chat ?gpt|gpt|alive)\b",
    r"\bare you (a )?(man|woman|boy|girl|male|female|teacher|examiner|native)\b",
    r"\b(what|what's|whats) (is )?your (name|age|job|surname|nationality|religion|favou?rite)\b",
    r"\bwho (are you|made you|created you|built you|programmed you|trained you)\b",
    r"\bwhat are you\b",
    r"\bhow old are you\b",
    r"\bwhere (are you from|do you live|were you born)\b",
    r"\b(do|did|have|can|will|would|are) you (like|love|have|speak|know|work|live|get|feel|think|ever|enjoy|want|any|also)\b",
    r"\bwhat about you\b|\band you\s*\?|\bhow about you\b|\byour opinion\b|\bwhat do you think\b",
    r"\bmy (score|band|marks?|result|results|grade)\b|\bhow am i doing\b|\bwas (that|it) (good|ok|okay|correct|right|fine)\b|"
    r"\bis (that|it) (good|ok|okay|correct|right|fine)\b|\bdid i (do|answer|pass|speak)\b|\bhow many (marks|bands|points)\b",
    r"\b(can|could|will|would) you (help|tell|give|show|explain|teach|answer|recommend|suggest)\b",
    r"\btell me (about|something about) yourself\b|\bwhich company\b|\bwho (owns|runs) (this|you)\b",
)]
_CALL_ME = re.compile(
    r"\b(?:call(?:s)? me|(?:i am|i'm|i was|i'm being) called|i go by|(?:everyone|everybody|people|friends|they) calls? me|"
    r"known as|my nickname is|my short name is|my pet name is|my friends call me)\s+([A-Za-z][A-Za-z'-]+)", re.I)
_NOT_NAMES = {"later", "back", "now", "tomorrow", "please", "again", "anytime", "whatever", "when", "if", "and", "or", "a", "an", "the"}


def is_off_topic_question(text: str) -> bool:
    """True if the candidate asks the examiner something instead of answering (and it is not a repeat request)."""
    t = text.strip()
    if len(t.split()) > 14 or is_repeat_request(t):
        return False
    return any(p.search(t) for p in _OFF_TOPIC)


def extract_call_name(text: str) -> str:
    """The name from "you can call me Rahim" / "everyone calls me Rahim" ("" if none)."""
    m = _CALL_ME.search(text)
    if not m or m.group(1).lower() in _NOT_NAMES:
        return ""
    return m.group(1).capitalize()


def is_repeat_request(text: str) -> bool:
    """True only if the candidate really asked the examiner to repeat or explain the question."""
    t = text.strip()
    return len(t.split()) <= 12 and bool(_REPEAT.search(t) or re.fullmatch(r"(what|huh)\??", t.strip(" ."), re.I))
