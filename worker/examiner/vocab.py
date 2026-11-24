"""Words the examiner may safely repeat back to the candidate.

The candidate's words come from speech recognition, which sometimes writes a wrong or invented word ("chicken mariadi" for
"chicken biryani"). A follow-up that repeats such a word back sounds foolish and confuses the candidate. So a question may use
a specific word from the candidate's answer only when that word is a clear, ordinary English word or a known local word.
When it is not, the question must be general (about the topic, not about that word).

"Known" means: a word in question_bank/common_words.txt (about 13,000 everyday English words, from the open `wordfreq`
list), a word used in the question bank itself, or one of the local names the recogniser is told about (rickshaw, biryani,
Savar...). The check only looks at words that the question has in common with what the candidate said: the examiner's own
wording is not in doubt.
"""
from __future__ import annotations

import re
from pathlib import Path

WORDS_PATH = Path(__file__).resolve().parent.parent.parent / "question_bank" / "common_words.txt"
MIN_LETTERS = 4                      # shorter words are almost always ordinary ("tea", "bus", "home")

# local names the recogniser is already told about (worker/stt.py FIXED); kept here so this module needs no model libraries
LOCAL = """bangladesh bangladeshi bangla dhaka chattogram chittagong sylhet rajshahi khulna barishal sundarbans rickshaw eid pohela boishakh
brac buet mirpur dhanmondi gulshan uttara mohammadpur narayanganj gazipur mymensingh comilla cumilla biryani fuchka pitha bhorta khichuri
hilsa puja ramadan metro bkash bashundhara banani motijheel farmgate savar minar ekushey kacchi tehari lungi panjabi adda
waterlogging loadshedding monsoon cyclone kichuri khichri ilish hilsha phuchka fuska chotpoti haleem borhani kabaddi kabadi jamdani nakshi dhaka's""".split()

_known: set[str] | None = None


def _forms(word: str) -> set[str]:
    """The word and its plausible base forms (plural, past tense, -ing, British/American spelling)."""
    forms = {word}
    for suffix, repl in (("ies", "y"), ("es", ""), ("s", ""), ("ed", ""), ("ing", ""), ("ly", ""), ("ing", "e"), ("ed", "e")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            forms.add(word[: -len(suffix)] + repl)
    if len(word) > 5 and word[-3] == word[-4] and word.endswith(("ing", "ed")):      # running -> runn -> run
        forms.add(word[: -3 if word.endswith("ing") else -2][:-1])
    for a, b in (("our", "or"), ("ise", "ize"), ("yse", "yze"), ("tre", "ter"), ("ogue", "og"), ("ence", "ense")):
        forms |= {w.replace(a, b) for w in list(forms) if a in w} | {w.replace(b, a) for w in list(forms) if b in w}
    return forms


def _load() -> set[str]:
    global _known
    if _known is None:
        words = set(LOCAL)
        if WORDS_PATH.exists():
            words |= {w.strip() for w in WORDS_PATH.read_text(encoding="utf-8").splitlines() if w.strip()}
        try:                                             # every word the question bank itself uses is, by definition, fine
            from worker.examiner.rules import load_bank
            bank = load_bank()
            text = " ".join(q["text"] for t in bank["part1"] for q in t["questions"])
            text += " ".join(" ".join([c["prompt"], c["closing"], *c["bullets"], *c["part3"]]) for c in bank["cueCards"])
            words |= set(re.findall(r"[a-z]+", text.lower()))
        except Exception:
            pass
        _known = words
    return _known


def is_known(word: str) -> bool:
    known = _load()
    return any(f in known for f in _forms(word.lower()))


def unverified_echoes(question: str, said: list[str]) -> list[str]:
    """Words the question repeats from what the candidate said that are not known words (possibly misheard)."""
    heard: set[str] = set()
    for text in said:
        for w in re.findall(r"[a-z]+", text.lower()):
            heard |= _forms(w)                           # "rickshaws" said, "rickshaw" asked: the same word
    out = []
    for w in dict.fromkeys(re.findall(r"[A-Za-z]+", question)):
        lw = w.lower()
        if len(lw) >= MIN_LETTERS and _forms(lw) & heard and not is_known(lw):
            out.append(lw)
    return out
