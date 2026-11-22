"""Small human touches between the candidate's answer and the next question.

A real examiner says "Okay." or "Thank you." between questions; a machine that goes straight from the
answer to the next question sounds abrupt. The company rules forbid praise and comments on answers
("Great", "Interesting", "I see"), so only neutral acknowledgements are used here, never an opinion.
Which one is chosen depends on how much the candidate said, and the same one is never used twice in a row.
"""
from __future__ import annotations

import random

# neutral, British, no judgement of the answer
SHORT = ["Okay.", "Right.", "Alright."]
MEDIUM = ["Okay.", "Right.", "All right.", "Okay, thank you."]
LONG = ["Okay, thank you.", "Thank you.", "All right, thank you.", "Right, thank you."]
NEW_TOPIC = ["Thank you.", "Okay, thank you.", "All right, thank you."]


class AckPicker:
    def __init__(self, rng: random.Random, probability: float = 0.65):
        self.rng, self.probability, self._last = rng, probability, ""

    def pick(self, answer: str, topic_change: bool = False) -> str:
        """An acknowledgement to put before the next question, or '' (not every turn gets one)."""
        if self.probability <= 0:
            return ""
        if not topic_change and self.rng.random() >= self.probability:
            return ""
        words = len(answer.split())
        pool = NEW_TOPIC if topic_change else SHORT if words <= 5 else LONG if words >= 25 else MEDIUM
        choices = [p for p in pool if p != self._last] or pool
        self._last = self.rng.choice(choices)
        return self._last
