"""Small human touches between the candidate's answer and the next question.

A real examiner says "Okay." or "Thank you." between questions; a machine that goes straight from the
answer to the next question sounds abrupt. The company rules forbid praise and comments on answers
("Great", "Interesting", "I see"), so only neutral acknowledgements are used here, never an opinion.
Which one is chosen depends on how much the candidate said, and the same one is never used twice in a row.
"""
from __future__ import annotations

import random

# Neutral and sparing: a real examiner mostly just asks the next question. Only "Okay." and "Thank you.", never "Right.",
# "Alright" or "All right" (those sounded like a verdict on the answer), and never a comment on the answer.
SHORT = ["Okay.", "Thank you."]
MEDIUM = ["Okay.", "Thank you."]
LONG = ["Thank you.", "Okay."]
NEW_TOPIC = ["Thank you.", "Okay, thank you."]
TOPIC_PROBABILITY = 0.5      # at a change of topic an acknowledgement is natural, but still not every time


class AckPicker:
    def __init__(self, rng: random.Random, probability: float = 0.12, min_gap: int = 0):
        """probability: chance of an acknowledgement on an ordinary turn. min_gap: at least this many turns without one
        between two acknowledgements (so they never come in a run)."""
        self.rng, self.probability, self.min_gap, self._last = rng, probability, min_gap, ""
        self._since = 10 ** 6          # turns since the last acknowledgement

    def pick(self, answer: str, topic_change: bool = False) -> str:
        """An acknowledgement to put before the next question, or '' (most turns get none)."""
        if self.probability <= 0:
            return ""
        self._since += 1
        chance = max(self.probability, TOPIC_PROBABILITY) if topic_change else self.probability
        if self._since <= self.min_gap or self.rng.random() >= chance:
            return ""
        words = len(answer.split())
        pool = NEW_TOPIC if topic_change else SHORT if words <= 5 else LONG if words >= 25 else MEDIUM
        choices = [p for p in pool if p != self._last] or pool
        self._last = self.rng.choice(choices)
        self._since = 0
        return self._last
