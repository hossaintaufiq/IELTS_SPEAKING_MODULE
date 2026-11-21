"""One live speaking test: runs the Part 1/2/3 flow on top of the voice pipeline.

The browser sends mic audio (binary) and control messages (JSON: start / next_part / end).
This class turns those into pipeline actions (scripted speech, LLM instructions), keeps the
transcript and timings, and writes a run log so quality can be reviewed and tuned.

STATUS: logic is unit-tested with fakes. The Pipecat behaviours it relies on (TTSSpeakFrame,
LLMMessagesAppendFrame, muting by dropping audio) are NOT verified on a live pipeline yet.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Awaitable, Callable

from worker.examiner import prompts
from worker.examiner.flow import FlowConfig, Phase, TestFlow

BANK = Path(__file__).resolve().parent.parent / "question_bank" / "questions.json"
RUNS = Path(__file__).resolve().parent.parent / "runs"

SCRIPT = {
    "intro": "Good morning. My name is Sarah, and I'll be your examiner today. Could you tell me your full name, please?",
    "part2_intro": ("Thank you. That is the end of Part 1. Now, I'm going to give you a topic, and I'd like you to talk about it "
                    "for one to two minutes. You have one minute to prepare, and you can make notes. Here is your topic."),
    "part2_start": "All right. Please begin speaking now. Remember, you should talk for one to two minutes.",
    "end": "Thank you. That is the end of the speaking test.",
}

Send = Callable[[dict], Awaitable[None]]


class ExamSession:
    def __init__(self, send: Send, cfg: FlowConfig | None = None, clock=time.monotonic, seed: int | None = None):
        self.send, self.clock = send, clock
        self.flow = TestFlow(cfg, clock=clock)
        self.bank = json.loads(BANK.read_text(encoding="utf-8"))
        rnd = random.Random(seed)
        self.topics = rnd.sample(self.bank["part1_topics"], k=min(3, len(self.bank["part1_topics"])))
        self.card = rnd.choice(self.bank["part2_cue_cards"])
        self.muted = True        # mic audio is ignored until the test starts, and during prep
        self.hold = False        # Part 2 monologue: collect transcripts instead of answering each pause
        self.held: list[str] = []
        self.started = False
        self.task = None         # pipecat PipelineTask, set by the server
        self.context = None      # LLMContext, set by the server
        self.log: list[dict] = []
        self.t0 = clock()
        self._ticker: asyncio.Task | None = None

    # ---- events to the browser + the run log -------------------------------------------------
    async def emit(self, event: dict) -> None:
        event = {**event, "t": round(self.clock() - self.t0, 2)}
        self.log.append(event)
        await self.send(event)

    async def say(self, text: str) -> None:
        """Scripted examiner line: spoken by TTS and remembered in the LLM context."""
        from pipecat.frames.frames import TTSSpeakFrame

        await self.emit({"type": "transcript", "role": "examiner", "text": text, "scripted": True})
        await self.task.queue_frames([TTSSpeakFrame(text, append_to_context=True)])

    async def instruct(self, system_text: str, run_llm: bool = False, user_text: str | None = None) -> None:
        from pipecat.frames.frames import LLMMessagesAppendFrame

        msgs = [{"role": "system", "content": system_text}]
        if user_text:
            msgs.append({"role": "user", "content": user_text})
        await self.task.queue_frames([LLMMessagesAppendFrame(messages=msgs, run_llm=run_llm)])

    # ---- control from the browser ------------------------------------------------------------
    async def handle_control(self, msg: dict) -> None:
        action = msg.get("action")
        if action == "start" and not self.started:
            await self.start()
        elif action == "next_part" and self.started:
            await self.advance()
        elif action == "end":
            await self.finish()

    async def start(self) -> None:
        self.started = True
        await self.instruct(self._part1_instructions())
        await self.emit({"type": "phase", "phase": Phase.INTRO.value, "limit": None})
        self.muted = False
        await self.say(SCRIPT["intro"])
        self._ticker = asyncio.create_task(self._tick_loop())

    def _part1_instructions(self) -> str:
        lines = "\n".join(f"- {t['topic']}: " + " / ".join(t["questions"]) for t in self.topics)
        return ("PART 1. After the candidate gives their name, say 'Thank you. Now I'd like to ask you some questions about yourself.' "
                "Then ask Part 1 questions, one at a time, working through these topics in order. You may rephrase and add a natural "
                "follow-up if an answer is very short, but do not stay on one topic for more than three questions.\n" + lines)

    async def advance(self) -> None:
        prev = self.flow.phase
        new = self.flow.advance()
        await self._enter(prev, new)

    async def _enter(self, prev: Phase, new: Phase) -> None:
        await self.emit({"type": "phase", "phase": new.value, "limit": self._limit(new),
                         "cue_card": self.card if new in (Phase.PART2_PREP, Phase.PART2_SPEAK) else None})
        if new == Phase.PART1:
            await self.instruct("Part 1 is starting now. Continue with Part 1 questions.", run_llm=False)
        elif new == Phase.PART2_PREP:
            self.muted = True
            await self.instruct("Part 1 is over. Do not ask any more Part 1 questions. Say nothing until instructed.")
            await self.say(SCRIPT["part2_intro"])
        elif new == Phase.PART2_SPEAK:
            self.muted, self.hold, self.held = False, True, []
            await self.say(SCRIPT["part2_start"])
        elif new == Phase.PART2_FOLLOWUP:
            self.hold = False
            talk = " ".join(self.held).strip() or "(the candidate said very little)"
            self.held = []
            await self.instruct(prompts.PART2_FOLLOWUP, run_llm=True, user_text=talk)
        elif new == Phase.PART3:
            qs = " / ".join(self.card["part3"])
            await self.instruct(prompts.PART3 + f"\nPart 2 topic was: {self.card['prompt']} Example Part 3 questions: {qs}",
                                run_llm=True, user_text="(Part 3 begins. Introduce it in one short sentence and ask your first question.)")
        elif new == Phase.DONE:
            self.muted = True
            await self.say(SCRIPT["end"])
            await self.finish()

    def _limit(self, phase: Phase) -> int | None:
        c = self.flow.cfg
        return {Phase.PART1: c.part1_s, Phase.PART2_PREP: c.part2_prep_s,
                Phase.PART2_SPEAK: c.part2_speak_s, Phase.PART3: c.part3_s}.get(phase)

    async def _tick_loop(self) -> None:
        try:
            while self.flow.phase != Phase.DONE:
                await asyncio.sleep(0.5)
                prev = self.flow.phase
                new = self.flow.tick()
                limit = self._limit(new)
                await self.send({"type": "timer", "phase": new.value, "elapsed": round(self.flow.elapsed(), 1), "limit": limit})
                if new != prev:
                    await self._enter(prev, new)
        except asyncio.CancelledError:
            pass

    # ---- transcript hooks used by the pipeline taps ------------------------------------------
    async def on_user_text(self, text: str) -> bool:
        """Return True if the text should continue into the LLM, False if it was held for Part 2."""
        await self.emit({"type": "transcript", "role": "user", "text": text})
        if self.hold:
            self.held.append(text)
            return False
        return True

    async def on_examiner_text(self, text: str) -> None:
        await self.emit({"type": "transcript", "role": "examiner", "text": text})

    async def on_latency(self, seconds: float) -> None:
        await self.emit({"type": "latency", "seconds": round(seconds, 2)})

    # ---- end ---------------------------------------------------------------------------------
    def abort(self) -> Path | None:
        """Connection dropped: stop timers and save what we have. No events are sent."""
        if self._ticker:
            self._ticker.cancel()
        self.muted = True
        return self.save()

    async def finish(self) -> Path | None:
        if self._ticker:
            self._ticker.cancel()
        self.muted = True
        await self.emit({"type": "done"})
        return self.save()

    def save(self) -> Path | None:
        if not self.log:
            return None
        RUNS.mkdir(exist_ok=True)
        path = RUNS / f"run_{time.strftime('%Y%m%d_%H%M%S')}.json"
        lat = [e["seconds"] for e in self.log if e["type"] == "latency"]
        path.write_text(json.dumps({"topics": [t["topic"] for t in self.topics], "card": self.card["id"],
                                    "latencies_s": lat, "events": self.log}, indent=2), encoding="utf-8")
        return path
