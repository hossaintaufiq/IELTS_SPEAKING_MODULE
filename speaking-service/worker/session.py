"""One live speaking test, driven by the company's examiner rules (worker/examiner/rules.py).

The browser sends mic audio (binary) and control messages (JSON: start / next_part / end).
The voice pipeline reports each finished candidate answer to `on_candidate_turn`; this class decides
what the examiner says next (fixed script lines, bank questions, or LLM-written questions that follow
the candidate's answer), speaks it through TTS, and keeps the transcript and a run log.

STATUS: logic is unit-tested with a fake LLM and task. The Pipecat side (TTSSpeakFrame, turn events)
was checked on the GPU box for the earlier version; this rule-driven flow is new.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Awaitable, Callable

from worker.examiner import rules
from worker.examiner.llm import generate_json
from worker.examiner.rules import SCRIPT, NextQuestionInput

RUNS = Path(__file__).resolve().parent.parent / "runs"
Send = Callable[[dict], Awaitable[None]]

# Phases shown in the UI
INTRO, NAME, PART1, PART2_INTRO, PART2_PREP, PART2_SPEAK, PART2_FOLLOWUP, PART3, DONE = (
    "intro", "name", "part1", "part2_intro", "part2_prep", "part2_speak", "part2_followup", "part3", "done")
ORDER = [INTRO, NAME, PART1, PART2_INTRO, PART2_PREP, PART2_SPEAK, PART2_FOLLOWUP, PART3, DONE]


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, default))


def timings() -> dict:
    """Company timings (brief.ts). Override with env vars to shorten a test run."""
    t = rules.TIMING
    return {"p1_min": _env_int("PART1_MIN_S", t["part1"]["min"]), "p1_max": _env_int("PART1_MAX_S", t["part1"]["max"]),
            "prep": _env_int("PART2_PREP_S", t["part2"]["prepare"]), "speak": _env_int("PART2_SPEAK_S", t["part2"]["speak"]),
            "p3_min": _env_int("PART3_MIN_S", t["part3"]["min"]), "p3_max": _env_int("PART3_MAX_S", t["part3"]["max"])}


def extract_name(text: str) -> str:
    """Best-effort 'what can I call you' from a spoken answer. Empty if unsure."""
    m = re.search(r"(?:call me|my name is|i am|i'm|it's|this is)\s+([A-Za-z][A-Za-z'-]+)", text, re.I)
    if m:
        return m.group(1).capitalize()
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    return words[0].capitalize() if 0 < len(words) <= 2 else ""


class ExamSession:
    def __init__(self, send: Send, clock=time.monotonic, seed: int | None = None, llm=generate_json,
                 plan: dict | None = None, hour: int | None = None):
        self.send, self.clock, self.llm = send, clock, llm
        self.cfg = timings()
        rng = random.Random(seed)
        self.plan = plan or rules.choose_plan(rng=rng)
        self.hour = time.localtime().tm_hour if hour is None else hour
        self.test_id = str(rng.random())[2:10]
        self.phase = INTRO
        self.muted = True             # mic ignored before start and during Part 2 preparation
        self.bot_speaking = False     # examiner audio is playing: ignore the mic (no talking over the examiner)
        self._bot_since = 0.0
        self.quiet_until = 0.0        # short tail after the examiner stops, so its echo dies away
        self.started = False
        self.task = None              # pipecat PipelineTask, set by the server
        self.log: list[dict] = []
        self.mic_chunks, self.mic_rms = 0, 0.0
        self._mic_pcm = bytearray()   # received mic audio, saved with the run so input level can be checked
        self.t0 = clock()
        self._phase_start = clock()
        self._ticker: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        # conversation state
        self.history: list[tuple[str, str]] = []
        self.asked: list[str] = []
        self.known: list[str] = []
        self.name = ""
        self.topic_idx = 0
        self.q_in_topic = 0           # questions asked on the current Part 1 topic
        self.q_target = 3
        self.last_question = ""
        self.part3_q = 0
        self.long_turn: list[str] = []
        self.long_turn_last = 0.0
        self.tell_more_done = False

    # ---- events to the browser + the run log -----------------------------------------------------
    def listening_blocked(self) -> bool:
        """True while the examiner is speaking (plus a short tail): mic audio is dropped so the examiner
        never hears and answers itself through the speakers."""
        if self.bot_speaking and self.clock() - self._bot_since > 30:   # a missed 'stopped' signal must never lock the mic
            self.bot_speaking = False
        return self.bot_speaking or self.clock() < self.quiet_until

    def bot_started(self) -> None:
        self.bot_speaking = True
        self._bot_since = self.clock()

    def bot_stopped(self, tail: float = 0.7) -> None:
        self.bot_speaking = False
        self.quiet_until = self.clock() + tail

    def note_audio(self, data: bytes) -> None:
        import array
        a = array.array("h", data[: len(data) // 2 * 2])
        self.mic_chunks += 1
        if len(self._mic_pcm) < 16000 * 2 * 600:
            self._mic_pcm.extend(data)
        if a:
            self.mic_rms = max((sum(x * x for x in a) / len(a)) ** 0.5 / 32768, self.mic_rms * 0.85)

    async def emit(self, event: dict) -> None:
        event = {**event, "t": round(self.clock() - self.t0, 2)}
        self.log.append(event)
        await self.send(event)

    async def say(self, text: str) -> None:
        """Examiner line: shown in the transcript and spoken by TTS."""
        from pipecat.frames.frames import TTSSpeakFrame

        self.history.append(("examiner", text))
        await self.emit({"type": "transcript", "role": "examiner", "text": text})
        await self.task.queue_frames([TTSSpeakFrame(text)])

    async def set_phase(self, phase: str, **extra) -> None:
        self.phase, self._phase_start = phase, self.clock()
        await self.emit({"type": "phase", "phase": phase, "limit": self._limit(phase), **extra})

    def _limit(self, phase: str) -> int | None:
        c = self.cfg
        return {PART1: c["p1_max"], PART2_PREP: c["prep"], PART2_SPEAK: c["speak"], PART3: c["p3_max"]}.get(phase)

    def elapsed(self) -> float:
        return self.clock() - self._phase_start

    # ---- control from the browser ----------------------------------------------------------------
    async def handle_control(self, msg: dict) -> None:
        action = msg.get("action")
        if action == "start" and not self.started:
            await self.start()
        elif action == "next_part" and self.started:
            async with self._lock:
                await self.skip_part()
        elif action == "end":
            await self.finish()

    async def start(self) -> None:
        self.started, self.muted = True, False
        await self.set_phase(INTRO)
        await self.say(SCRIPT["greeting"](rules.EXAMINER, rules.time_of_day(self.hour)))
        self._ticker = asyncio.create_task(self._tick_loop())

    # ---- the candidate finished an answer --------------------------------------------------------
    async def on_candidate_turn(self, text: str) -> None:
        text = text.strip()
        if not text or self.phase == DONE:
            return
        await self.emit({"type": "transcript", "role": "user", "text": text})
        async with self._lock:
            self.history.append(("candidate", text))
            p = self.phase
            if p == INTRO:
                await self.set_phase(NAME)
                await self.say(SCRIPT["callName"])
            elif p == NAME:
                self.name = extract_name(text)
                if self.name:
                    self.known.append(f"likes to be called {self.name}")
                lead = f"Thank you, {self.name}." if self.name else "Thank you."
                await self.start_part1(lead + " " + SCRIPT["part1Intro"])
            elif p == PART1:
                await self.part1_next(text)
            elif p == PART2_INTRO:
                await self.show_card()
            elif p == PART2_SPEAK:
                self.long_turn.append(text)
                self.long_turn_last = self.clock()
            elif p == PART2_FOLLOWUP:
                await self.start_part3()
            elif p == PART3:
                await self.part3_next(text)

    # ---- Part 1 ----------------------------------------------------------------------------------
    def _topic(self) -> dict:
        return self.plan["part1"][self.topic_idx]

    async def start_part1(self, lead: str) -> None:
        await self.set_phase(PART1)
        self.topic_idx, self.q_in_topic = 0, 0
        await self.ask_bank_question(first_topic=True, lead=lead)

    async def ask_bank_question(self, first_topic: bool, lead: str = "") -> None:
        t = self._topic()
        self.q_target = random.choice([3, 4])
        opener = (SCRIPT["topicFirst"] if first_topic else SCRIPT["topicNext"]) + f" {rules.lower_first(t['topic'])}."
        q = t["questions"][0]["text"]
        self.q_in_topic = 1
        self.asked.append(q)
        self.last_question = q
        await self.say(" ".join(x for x in (lead, opener, q) if x))

    async def part1_next(self, answer: str) -> None:
        c, el = self.cfg, self.elapsed()
        topic_done = self.q_in_topic >= self.q_target
        if el >= c["p1_max"] or (el >= c["p1_min"] and topic_done):
            await self.start_part2_intro()
            return
        if topic_done:
            if self.topic_idx + 1 >= len(self.plan["part1"]):
                await self.start_part2_intro()
                return
            self.topic_idx += 1
            await self.ask_bank_question(first_topic=False)
            return
        t = self._topic()
        inp = NextQuestionInput(
            part=1, topic=t["topic"], frames=[q["text"] for q in t["questions"]], asked=list(self.asked),
            question_number=self.q_in_topic + 1, questions_on_topic=self.q_target, history=list(self.history),
            fallback=t["questions"][min(self.q_in_topic, len(t["questions"]) - 1)]["text"], known=list(self.known))
        nq = await rules.next_question(inp, self.llm, self.test_id)
        self.known.extend(f for f in nq.facts if f not in self.known)
        if nq.reply != "repeat":
            self.q_in_topic += 1
            self.asked.append(rules.question_part(nq.say))
            self.last_question = rules.question_part(nq.say)
        await self.say(nq.say)

    # ---- Part 2 ----------------------------------------------------------------------------------
    async def start_part2_intro(self) -> None:
        await self.set_phase(PART2_INTRO)
        await self.say("Thank you. " + SCRIPT["part2Intro"])

    async def show_card(self) -> None:
        card = self.plan["cueCard"]
        self.muted = True
        await self.set_phase(PART2_PREP, cue_card={"prompt": card["prompt"], "bullets": card["bullets"], "closing": card["closing"]})
        await self.say(f"{SCRIPT['part2Topic']} {rules.lower_first(card['prompt'])}")

    async def start_long_turn(self) -> None:
        self.muted = False
        self.long_turn, self.long_turn_last, self.tell_more_done = [], 0.0, False
        card = self.plan["cueCard"]
        await self.set_phase(PART2_SPEAK, cue_card={"prompt": card["prompt"], "bullets": card["bullets"], "closing": card["closing"]})
        await self.say(SCRIPT["part2Start"])

    async def end_long_turn(self) -> None:
        """Time is up (or they finished): 'Thank you.' and one short question about what they said."""
        talk = " ".join(self.long_turn).strip()
        if talk:
            self.history.append(("candidate", talk))
        await self.set_phase(PART2_FOLLOWUP)
        prompt = (f'Part 2 has just ended. The candidate talked about: "{self.plan["cueCard"]["prompt"]}".\n'
                  f"What they said: {talk or '(very little)'}\n"
                  "Ask ONE short question (under 20 words, ending with a question mark) about something specific they said. "
                  'Reply as JSON: {"say": "<the question>"}')
        js = await self.llm(rules.SYSTEM, prompt)
        q = rules.clean(js["say"]) if js and isinstance(js.get("say"), str) else ""
        if not q.endswith("?") or rules.BANNED.search(q) or q.count("?") != 1:
            q = SCRIPT["tellMeMore"]                 # safe line from the company script
        await self.say(f"{SCRIPT['part2Stop']} {q}")

    # ---- Part 3 ----------------------------------------------------------------------------------
    async def start_part3(self) -> None:
        card = self.plan["cueCard"]
        await self.set_phase(PART3)
        subject = card["topic"]
        first = self.plan["part3"]["questions"][0]
        self.part3_q = 1
        self.asked.append(first)
        self.last_question = first
        await self.say(f"{SCRIPT['part3Intro'](subject)} {SCRIPT['part3First']} {rules.lower_first(self.plan['part3']['topic'])}. {first}")

    async def part3_next(self, answer: str) -> None:
        c, el = self.cfg, self.elapsed()
        if el >= c["p3_max"] or (el >= c["p3_min"] and self.part3_q >= 4):
            await self.close()
            return
        qs = self.plan["part3"]["questions"]
        inp = NextQuestionInput(
            part=3, topic=self.plan["part3"]["topic"], frames=qs, asked=list(self.asked), question_number=self.part3_q + 1,
            questions_on_topic=8, history=list(self.history), cue_card=self.plan["cueCard"]["prompt"],
            fallback=qs[min(self.part3_q, len(qs) - 1)], known=list(self.known))
        nq = await rules.next_question(inp, self.llm, self.test_id)
        self.known.extend(f for f in nq.facts if f not in self.known)
        if nq.reply == "repeat":
            nq.say = await rules.rephrase_question(self.last_question, self.llm)
        else:
            self.part3_q += 1
            self.asked.append(rules.question_part(nq.say))
            self.last_question = rules.question_part(nq.say)
        await self.say(nq.say)

    async def close(self) -> None:
        await self.say(SCRIPT["closing"])
        await self.set_phase(DONE)
        self.muted = True
        await self.finish()

    # ---- skip button + timers --------------------------------------------------------------------
    async def skip_part(self) -> None:
        p = self.phase
        if p in (INTRO, NAME):
            self.name = self.name or ""
            await self.start_part1(SCRIPT["part1Intro"])
        elif p == PART1:
            await self.start_part2_intro()
        elif p == PART2_INTRO:
            await self.show_card()
        elif p == PART2_PREP:
            await self.start_long_turn()
        elif p == PART2_SPEAK:
            await self.end_long_turn()
        elif p == PART2_FOLLOWUP:
            await self.start_part3()
        elif p == PART3:
            await self.close()

    async def _tick_loop(self) -> None:
        try:
            while self.phase != DONE:
                await asyncio.sleep(0.5)
                limit = self._limit(self.phase)
                await self.send({"type": "timer", "phase": self.phase, "elapsed": round(self.elapsed(), 1), "limit": limit,
                                 "mic_chunks": self.mic_chunks, "mic_rms": round(self.mic_rms, 4)})
                async with self._lock:
                    await self._on_tick(limit)
        except asyncio.CancelledError:
            pass

    async def _on_tick(self, limit) -> None:
        if self.phase == PART2_PREP and self.elapsed() >= limit:
            await self.start_long_turn()
        elif self.phase == PART2_SPEAK:
            if self.elapsed() >= limit:
                await self.end_long_turn()
            elif self.long_turn and not self.tell_more_done and self.clock() - self.long_turn_last > 8:
                self.tell_more_done = True            # they stopped early: ask for more, once
                await self.say(SCRIPT["tellMeMore"])

    # ---- hooks used by the pipeline taps ---------------------------------------------------------
    async def on_latency(self, seconds: float) -> None:
        await self.emit({"type": "latency", "seconds": round(seconds, 2)})

    # ---- end -------------------------------------------------------------------------------------
    async def finish(self) -> Path | None:
        if self._ticker:
            self._ticker.cancel()
        self.muted = True
        await self.emit({"type": "done"})
        return self.save()

    def abort(self) -> Path | None:
        """Connection dropped: stop timers and save what we have. No events are sent."""
        if self._ticker:
            self._ticker.cancel()
        self.muted = True
        return self.save()

    def save(self) -> Path | None:
        if not self.log:
            return None
        RUNS.mkdir(exist_ok=True)
        path = RUNS / f"run_{time.strftime('%Y%m%d_%H%M%S')}.json"
        lat = [e["seconds"] for e in self.log if e["type"] == "latency"]
        mic = {}
        if self._mic_pcm:
            import array, wave
            a = array.array("h", bytes(self._mic_pcm[: len(self._mic_pcm) // 2 * 2]))
            mic = {"mic_seconds": round(len(a) / 16000, 1), "mic_peak": round(max(abs(x) for x in a) / 32768, 4),
                   "mic_rms": round((sum(x * x for x in a) / len(a)) ** 0.5 / 32768, 4)}
            with wave.open(str(path.with_suffix(".wav")), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(self._mic_pcm))
        path.write_text(json.dumps({**mic, 
            "topics": [t["topic"] for t in self.plan["part1"]], "card": self.plan["cueCard"]["prompt"],
            "name": self.name, "known_facts": self.known, "mic_chunks_received": self.mic_chunks,
            "latencies_s": lat, "events": self.log}, indent=2), encoding="utf-8")
        return path
