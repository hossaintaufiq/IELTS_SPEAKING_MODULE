"""IELTS Speaking test flow: intro -> Part 1 -> Part 2 (prep, monologue, follow-up) -> Part 3.

Pure state machine with an injectable clock, so it can be tested without audio or models.
Durations are planning defaults (the official test is 11-14 minutes) and live in FlowConfig.
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass


class Phase(str, enum.Enum):
    INTRO = "intro"
    PART1 = "part1"
    PART2_PREP = "part2_prep"
    PART2_SPEAK = "part2_speak"
    PART2_FOLLOWUP = "part2_followup"
    PART3 = "part3"
    DONE = "done"


@dataclass
class FlowConfig:
    part1_s: int = 270          # about 4.5 min
    part2_prep_s: int = 60
    part2_speak_s: int = 120
    part3_s: int = 270


ORDER = [Phase.INTRO, Phase.PART1, Phase.PART2_PREP, Phase.PART2_SPEAK,
         Phase.PART2_FOLLOWUP, Phase.PART3, Phase.DONE]

# Phases whose examiner speech is scripted (pre-rendered audio, no LLM or TTS call).
SCRIPTED = {Phase.INTRO, Phase.PART1, Phase.PART2_PREP}


class TestFlow:
    __test__ = False  # not a pytest class

    def __init__(self, cfg: FlowConfig | None = None, clock=time.monotonic):
        self.cfg, self._clock = cfg or FlowConfig(), clock
        self.phase = Phase.INTRO
        self._phase_start = clock()

    def elapsed(self) -> float:
        return self._clock() - self._phase_start

    def _go(self, phase: Phase) -> None:
        self.phase, self._phase_start = phase, self._clock()

    def examiner_mode(self) -> str:
        """'scripted' plays pre-rendered audio, 'llm' generates, 'silent' waits for the candidate."""
        if self.phase in (Phase.DONE, Phase.PART2_SPEAK):
            return "silent"
        return "scripted" if self.phase in SCRIPTED else "llm"

    def advance(self) -> Phase:
        """Move to the next phase on a natural boundary (for example the intro finished)."""
        self._go(ORDER[min(ORDER.index(self.phase) + 1, len(ORDER) - 1)])
        return self.phase

    def tick(self) -> Phase:
        """Call periodically; moves on when the current phase's time budget is spent."""
        limit = {
            Phase.PART1: self.cfg.part1_s,
            Phase.PART2_PREP: self.cfg.part2_prep_s,
            Phase.PART2_SPEAK: self.cfg.part2_speak_s,
            Phase.PART3: self.cfg.part3_s,
        }.get(self.phase)
        if limit is not None and self.elapsed() >= limit:
            self.advance()
        return self.phase
