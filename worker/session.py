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
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import Awaitable, Callable

from worker.examiner import llm as llm_module
from worker.examiner import rules
from worker.examiner.llm import generate_json
from worker.examiner.answered import content_words
from worker.examiner.intents import finish_answer, is_done_talking, is_finish_request
from worker.examiner.naturalness import AckPicker
from worker import load_guard
from worker.examiner.pacing import wait_seconds
from worker.examiner.rules import SCRIPT, NextQuestionInput
from worker.examiner.vocab import unverified_echoes
from worker.examiner.speech import (extract_call_name, is_noise, is_off_topic_question, is_repeat_request,
                                    looks_unfinished, strip_foreign)

RUNS = Path(__file__).resolve().parent.parent / "runs"
log = logging.getLogger("speaking.session")
Send = Callable[[dict], Awaitable[None]]

# Phases shown in the UI
INTRO, NAME, PART1, PART2_INTRO, PART2_PREP, PART2_SPEAK, PART2_FOLLOWUP, PART3, DONE = (
    "intro", "name", "part1", "part2_intro", "part2_prep", "part2_speak", "part2_followup", "part3", "done")
ORDER = [INTRO, NAME, PART1, PART2_INTRO, PART2_PREP, PART2_SPEAK, PART2_FOLLOWUP, PART3, DONE]


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, default))


def timings() -> dict:
    """The pacing of one test, which may run up to 16 minutes: about 5 minutes of Part 1 (never more than 5 min 40 s),
    a Part 2 of about 4 minutes (1 min preparation, up to 2 min talk, the examiner's lines) and about 5 minutes of Part 3
    (same cap). The number of questions follows the time, not the other way round. Override with environment variables."""
    t = rules.TIMING
    return {"p1_min": _env_int("PART1_MIN_S", 270), "p1_max": _env_int("PART1_MAX_S", 340),
            "prep": _env_int("PART2_PREP_S", t["part2"]["prepare"]), "speak": _env_int("PART2_SPEAK_S", t["part2"]["speak"]),
            "p3_min": _env_int("PART3_MIN_S", 270), "p3_max": _env_int("PART3_MAX_S", 340),
            "total_max": _env_int("TEST_MAX_S", 960)}


CORE_TOPICS = 3            # Part 1 plans three topics, the rest of the plan is reserve for when the answers are short and time is left
MIN_Q_PER_TOPIC = 3        # a topic always gets at least this many real questions (follow-ups do not count); more if the time fits
MIN_TOPIC_SLICE_S = 60
RESERVE_SLICE_S = 50


# examiner.ts: "a short follow-up that pushes them to develop it" for Part 3
PART3_FOLLOW_UPS = ["Why do you think that is?", "Can you give an example?"]

STUCK_VOICE_S = 20         # "speech started" with no "speech stopped" is believed this long after the microphone last carried sound
VOICE_RMS = 0.012          # a microphone chunk at least this loud carries speech (quiet laptop microphones: about 0.02 to 0.03)
LINE_START_MAX_S = 45      # how long a queued line may take to start sounding before the silence timers stop waiting for it
P2_REAL_WORDS = 4          # fewer words than this in the long turn is not "speaking" (stray noise, a lone "okay")
P2_ENOUGH_WORDS = 12       # fewer than this and no question is made up about it: straight on to Part 3
DONE_TALKING_PAUSE_S = 1.5   # after "that's all" the examiner waits this long in case they go on, then thanks them
LATE_BEFORE_S = 6.0          # ...or began up to this long before the question ended (they talked over it)
LATE_CUE_VOICE_S = 4.5       # a turn that opens with "so / and / also / because" is allowed more time: it is plainly a continuation
CONTINUATION_CUE = re.compile(r"^(?:so|and|also|because|but|then|plus|moreover|besides)\b", re.I)
LATE_VOICE_S = 1.8           # a long turn that starts this soon after the examiner's question may still be the end of the previous answer
ANSWER_CAP_QUIET_S = 2.0     # an over-long answer is only cut while the candidate is still talking (voice heard in the last 2 s)
QUIET_BEFORE_REPLY_S = 1.0   # the examiner never starts speaking until the candidate's voice has been quiet this long
VOICE_GRACE_S = 2.0        # after hearing the candidate, the Part 2 silence prompts wait at least this long
P2_FINISH_SENTENCE_S = 10  # at the two-minute mark a candidate who is still speaking may finish what they are saying, for up to this long
P2_TRANSCRIPT_WAIT_S = 2.5 # ...and the examiner waits this long after their voice stops, so the last words are transcribed and not lost
PART3_GRACE_S = 25         # Part 3 time is up and the candidate is silent: close the test after this long
NAME_GIVEN = re.compile(r"\b(?:my (?:full )?name is|i am|i'm|this is|it is|it's)\s+[A-Za-z]{2,}", re.I)
META_TALK = re.compile(r"\b(conversation|discussion|you (?:say|said|mention\w*|told|talked?)|talk(?:ed|ing)? about|topic)\b", re.I)
_QSTOP = {"what", "about", "would", "could", "your", "that", "this", "there", "their", "with", "have", "does", "tell",
          "much", "more", "also", "other", "think", "like", "when", "which", "from", "been", "were", "them", "they",
          "then", "these", "those", "some", "time", "why", "how", "mention", "mentioned", "said", "talk", "talked"}


def nq_origin(nq) -> str:
    """'ai:new' | 'ai:reworded' | 'ai:bank' (the LLM picked a bank question) | 'ai:redirect' | 'script:fallback'."""
    return f"{nq.source}:{nq.origin}"


def _grounded(question: str, talk: str, card: str) -> bool:
    """A follow-up question must be built from something the candidate said (or the topic), never from nothing."""
    have = set(re.findall(r"[a-z']{4,}", f"{talk} {card}".lower()))
    return any(w in have for w in re.findall(r"[a-z']{4,}", question.lower()) if w not in _QSTOP)


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
        self.send, self.clock = send, clock
        self.cfg = timings()
        rng = random.Random(seed)
        self.plan = plan or rules.choose_plan(rng=rng)
        self.hour = time.localtime().tm_hour if hour is None else hour
        self.test_id = str(rng.random())[2:10]
        self.device = ""              # a label for the device taking this test (several can run at once)
        self.external_user_id = ""    # the caller's own id for the candidate (service API); opaque to us
        self.end_reason = ""          # why the test ended: completed, ended_by_candidate, off_topic, no_response, skipped_to_end, aborted
        self.status = "created"       # created -> running -> completed | aborted
        self.phase = INTRO
        self.muted = True             # mic ignored before start and during Part 2 preparation
        self.bot_speaking = False     # examiner audio is playing: ignore the mic (no talking over the examiner)
        self._bot_since = 0.0
        self.quiet_until = 0.0        # short tail after the examiner stops, so its echo dies away
        self.started = False
        self.task = None              # pipecat PipelineTask, set by the server
        self.stt = None               # speech service; told the examiner's latest line as a recognition hint
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
        self.q_target = 5                  # only used to word the prompt; the number of questions follows the time
        self.last_question = ""
        self.part3_q = 0
        self.long_turn: list[str] = []
        self.long_turn_last = 0.0
        self.p2_nudges = 0                 # prompts given in this long turn: 1 = ask once, 2 = reminder (never more)
        self._bot_stopped_at = 0.0
        # Part 2 silence: seconds of quiet before the examiner prompts (never started / stopped early) and before the reminder
        # Silence in the long turn: prompt (7 s, or 5 s if they stopped early), "you still have time" (+7 s), then move on (+7 s).
        # Never started talking: prompt after 6 s, "you still have time" 5 s later, move on 5 s after that.
        self.p2_silence_s = float(os.getenv("PART2_SILENCE_S", "6"))
        self.p2_remind_s = float(os.getenv("PART2_REMIND_S", "5"))
        self.p2_giveup_s = float(os.getenv("PART2_GIVEUP_S", "5"))
        # Was talking and stops: ONE gentle "you still have time" after 4 s, then 6 s more before moving on. The examiner never
        # asks "anything more?": a candidate is given the time to finish, and can say "that's all" to end the talk.
        self.p2_early_s = float(os.getenv("PART2_EARLY_STOP_S", "4"))
        self.p2_early_giveup_s = float(os.getenv("PART2_EARLY_GIVEUP_S", "6"))
        self._p2_time_said = False         # the "you still have time" line has been spoken in this long turn
        self._end_task: asyncio.Task | None = None
        self.await_audio = False          # real server: wait for the examiner's last line to finish playing before ending
        # patience: seconds of quiet (after the turn-end detector) before the examiner answers
        # The clock starts when the transcript arrives (the VAD and recogniser have already used about a second).
        self.pause_s = float(os.getenv("ANSWER_PAUSE_S", "2.2"))            # Part 1
        self.p3_pause_s = float(os.getenv("PART3_PAUSE_S", "3.0"))          # Part 3: longer, more thinking
        self.other_pause_s = float(os.getenv("OTHER_PAUSE_S", "1.8"))       # name, "do you understand?"
        self.extra_s = float(os.getenv("INCOMPLETE_EXTRA_S", "2.0"))        # more patience after "...and", "...because"
        self.short_extra_s = float(os.getenv("SHORT_ANSWER_EXTRA_S", "1.5"))  # "Yes." usually goes on to an explanation
        self.think_extra_s = float(os.getenv("THINKING_EXTRA_S", "4.0"))    # "let me think", "how can I say"
        self.max_wait_s = float(os.getenv("MAX_WAIT_S", "10.0"))
        self.adaptive_wait = os.getenv("ADAPTIVE_WAIT", "1") == "1"
        self.acks = AckPicker(rng, float(os.getenv("EXAMINER_ACK_PROB", "0.12")), int(os.getenv("EXAMINER_ACK_GAP", "3")))
        self._raw_llm = llm
        self.llm_error = ""
        self.llm = self._interruptible_llm
        self._interruptible = False        # True while the LLM is writing the next question: more speech may still change it
        self._tick_errors = 0
        self.topic_t0, self.topic_slice = 0.0, 90.0   # when the current Part 1 topic began, and how long it may take
        self._last_was_probe = False       # the previous examiner turn was a follow-up ("Why is that?"): never two in a row
        self._probes_in_topic = 0          # follow-ups asked on the current Part 1 topic: at most one
        self._since_probe = 99             # questions asked since the last follow-up: at least two between follow-ups
        self._p1_probes = 0                # follow-ups in the whole of Part 1: at most three
        self.confirm_end = False           # the examiner asked "finish or continue?" and is waiting for the answer
        self.finish_unclear = 0
        self.off_topic_count = 0           # irrelevant questions so far: 1st reminder, 2nd warning, 3rd ends the test
        self.off_topic_limit = int(os.getenv("OFFTOPIC_LIMIT", "3"))
        self._pending: list[str] = []
        self._pause_task: asyncio.Task | None = None
        self._responding = False
        self._user_active, self._user_active_since = False, 0.0
        # One answer must not run on for ever: past this many seconds of talking the examiner ends it politely and moves on.
        # Generous on purpose (the candidate must be able to finish), and only while they are still talking.
        self.answer_cap = {PART1: float(os.getenv("PART1_MAX_ANSWER_S", "60")), PART3: float(os.getenv("PART3_MAX_ANSWER_S", "90"))}
        self._answer_since: float | None = None      # when the candidate began the answer in progress (first voice after the examiner spoke)
        self._cut_next = False                       # the next examiner line is the polite "let's move on" after an over-long answer
        self._late_continuation = False             # the next turn is the end of the PREVIOUS answer, not an answer to the question just asked
        self._line_due: float | None = None          # when the line still waiting to be heard was queued
        self._last_loud_at = -1e9                    # when a microphone chunk last carried sound loud enough to be speech
        self._last_voice_at = -1e9                  # when the voice detector last heard the candidate

    # ---- events to the browser + the run log -----------------------------------------------------
    def listening_blocked(self) -> bool:
        """True while the examiner is speaking (plus a short tail): mic audio is dropped so the examiner
        never hears and answers itself through the speakers."""
        if self.bot_speaking and self.clock() - self._bot_since > 30:   # a missed 'stopped' signal must never lock the mic
            self.bot_speaking = False
        return self.bot_speaking or self.clock() < self.quiet_until

    def _line_waiting(self) -> bool:
        """The examiner has a line that is still being turned into speech."""
        return self._line_due is not None and self.clock() - self._line_due < LINE_START_MAX_S

    def bot_started(self) -> None:
        self._line_due = None
        self.bot_speaking = True
        self._bot_since = self.clock()

    def bot_stopped(self, tail: float = 0.7) -> None:
        self.bot_speaking = False
        self._answer_since = None
        self._bot_stopped_at = self.clock()
        self.quiet_until = self.clock() + tail

    def note_audio(self, data: bytes) -> None:
        import array
        a = array.array("h", data[: len(data) // 2 * 2])
        self.mic_chunks += 1
        if len(self._mic_pcm) < 16000 * 2 * 600:
            self._mic_pcm.extend(data)
        if a:
            rms = (sum(x * x for x in a) / len(a)) ** 0.5 / 32768
            if rms >= VOICE_RMS:
                self._last_loud_at = self.clock()
            self.mic_rms = max(rms, self.mic_rms * 0.85)

    async def emit(self, event: dict) -> None:
        event = {**event, "t": round(self.clock() - self.t0, 2), "at": round(time.time(), 2)}   # "at" (wall clock) lines up several devices
        self.log.append(event)
        if event.get("type") in ("transcript", "note", "ignored", "phase", "done"):
            # one line per event in the server log, tagged with the device, so every device can be followed (and filtered) there too
            what = event.get("role") or event.get("type")
            text = event.get("text") or event.get("phase") or ""
            log.info("[%s] %s %s: %s", self.device or self.test_id[:4], event.get("phase") or "-", what, str(text)[:200])
        await self.send(event)

    async def say(self, text: str, origin: str = "script", why: str = "") -> None:
        """Examiner line: shown in the transcript and spoken by TTS. `origin` says where the words came from
        (script, bank, ai:new, ai:reworded, ai:bank, script:fallback, ...) and shows in the run log."""
        from pipecat.frames.frames import TTSSpeakFrame

        self.history.append(("examiner", text))
        self._answer_since = None
        if self.await_audio:
            self._line_due = self.clock()           # until it is heard: a slow voice must not count as the candidate's silence
        if self.stt is not None:
            self.stt.question_hint = text
        await self.emit({"type": "transcript", "role": "examiner", "text": text, "origin": origin, **({"why": why} if why else {})})
        await self.task.queue_frames([TTSSpeakFrame(text)])

    async def set_phase(self, phase: str, **extra) -> None:
        self.phase, self._phase_start = phase, self.clock()
        self.confirm_end = False                    # a pending "finish or continue?" belongs to the part it was asked in
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
        elif action == "skip_prep" and self.started:
            async with self._lock:
                if self.phase == PART2_PREP:        # checked under the lock: the minute may just have run out on its own
                    await self.start_long_turn()
        elif action == "end":
            if self.started and self.phase != DONE:
                self._drop_pending()
                async with self._lock:
                    await self.close(reason="ended_by_candidate")   # the examiner thanks the candidate and ends the test, as in the real exam
            else:
                self.end_reason = self.end_reason or "ended_by_candidate"
                await self.finish()

    async def start(self) -> None:
        self.started, self.muted, self.status = True, False, "running"
        await self.set_phase(INTRO)
        self.last_question = "Can you tell me your full name, please?"      # re-asked after an off-test question
        await self.say(SCRIPT["greeting"](rules.EXAMINER, rules.time_of_day(self.hour)))
        self._ticker = asyncio.create_task(self._tick_loop())

    # ---- the candidate finished an answer --------------------------------------------------------
    def vad_started(self) -> None:
        self._user_active, self._user_active_since = True, self.clock()
        self._last_voice_at = self.clock()
        if self._answer_since is None and self.phase in (PART1, PART3) and not self.bot_speaking and not self.muted:
            self._answer_since = self.clock()
        if self._responding and self._interruptible and self._pause_task:
            # They started talking again while the next question was being written: their answer was not finished.
            # Take the question back (the answer is restored) and wait for the whole answer.
            self._pause_task.cancel()
            self._pause_task = asyncio.create_task(self._answer_after_pause())

    def vad_stopped(self) -> None:
        self._user_active = False
        self._last_voice_at = self.clock()           # their voice was heard right up to now (a transcript only follows later)

    def _speaking_now(self) -> bool:
        # A missed "stopped" signal must not make the examiner wait forever. But a candidate who talks for a long time without a
        # pause (common in the Part 2 long turn) sends no new signal either, so while the microphone still carries sound they are talking.
        return self._user_active and self.clock() - max(self._user_active_since, self._last_loud_at) < STUCK_VOICE_S

    async def on_candidate_turn(self, text: str) -> None:
        """A speech turn was finished. The examiner does NOT answer yet: it waits for the candidate's
        natural pause, and merges turns that arrive in pieces, so it never cuts an answer short."""
        text = strip_foreign(text.strip())          # another language's stock phrase at the end is not the candidate's
        if not text or self.phase == DONE:
            return
        if is_noise(text):                          # "ummm", Whisper hallucination on noise/silence: not an answer
            await self.emit({"type": "ignored", "text": text, "why": "noise"})
            if self._pending and not self._responding and self.phase != PART2_SPEAK:
                self._restart_wait()                # they are still thinking aloud: keep waiting
            return
        await self.emit({"type": "transcript", "role": "user", "text": text})
        done_talking = self.phase == PART2_SPEAK and is_done_talking(text)       # "that's all" ends the TALK, not the test
        if self.phase == PART2_SPEAK and not self.confirm_end and (done_talking or not is_finish_request(text)):
            # long turn: collect, the examiner stays silent (a request to finish the test is handled like any other turn)
            was_talking = self._p2_started()
            self.long_turn.append(text)
            if was_talking or len(text.split()) >= 3:     # a stray one- or two-word fragment from silence does not count as speaking
                self.long_turn_last = self.clock()
            if done_talking:
                self._end_task = asyncio.create_task(self._end_talk_soon())
            return
        if self._is_late_continuation(text):
            self._late_continuation = True
            await self.emit({"type": "note", "text": "the candidate was still finishing the previous answer: it is added to that answer, not taken as the reply to the new question"})
        self._pending.append(text)
        if self._responding:
            if self._interruptible and self._pause_task:
                # More speech arrived while the next question was still being written: the answer was not finished.
                # Take the question back (it is restored below) and wait for the whole answer instead.
                self._pause_task.cancel()
                self._pause_task = asyncio.create_task(self._answer_after_pause())
            return
        self._restart_wait()

    def _is_late_continuation(self, text: str) -> bool:
        """The candidate was still answering the PREVIOUS question when the examiner asked the next one. Their words start right
        after the new question, say nothing about it, and carry on from what they said before. They must not be taken as the answer
        to the new question (which would make the examiner ask a third one on top)."""
        if self.phase not in (PART1, PART3) or not self.last_question or self._pending or not self._bot_stopped_at:
            return False
        words = text.split()
        gap = self._user_active_since - self._bot_stopped_at         # negative: they were already talking when the question ended
        cue = bool(CONTINUATION_CUE.match(text.strip()))             # "So rickshaws feel more practical.", "And also..."
        if len(words) < (3 if cue else 10) or not -LATE_BEFORE_S <= gap < (LATE_CUE_VOICE_S if cue else LATE_VOICE_S):
            return False
        prev = next((t for who, t in reversed(self.history) if who == "candidate"), "")
        asked = {w for w in content_words(self.last_question)}
        said = set(content_words(text))
        return bool(prev) and not (said & asked) and bool(said & set(content_words(prev)))

    def _restart_wait(self) -> None:
        if self._pause_task and not self._responding:
            self._pause_task.cancel()               # more speech arrived: restart the wait
        self._pause_task = asyncio.create_task(self._answer_after_pause())

    def test_mode(self) -> None:
        """No waiting and no acknowledgements: exact, instant behaviour for unit tests."""
        self.pause_s = self.p3_pause_s = self.other_pause_s = self.extra_s = 0.0
        self.short_extra_s = self.think_extra_s = 0.0
        self.max_wait_s = 60.0
        self.acks.probability = 0.0

    def _why(self, nq) -> str:
        """Why a fallback question was used. For an LLM failure, say what actually went wrong."""
        if nq.why.startswith("the LLM did not answer") and self.llm_error:
            return f"the LLM did not answer: {self.llm_error}"
        return nq.why

    async def _interruptible_llm(self, *args, **kwargs):
        self._interruptible = True
        try:
            out = await self._raw_llm(*args, **kwargs)
            if not out:
                self.llm_error = llm_module.last_error
            return out
        finally:
            self._interruptible = False

    def _wait_for(self, text: str) -> float:
        base = {PART1: self.pause_s, PART3: self.p3_pause_s}.get(self.phase, self.other_pause_s)
        return wait_seconds(text, base, short_extra=self.short_extra_s if self.phase in (PART1, PART3, PART2_FOLLOWUP) else 0.0,
                            unfinished_extra=self.extra_s, think_extra=self.think_extra_s,
                            max_wait=self.max_wait_s, adaptive=self.adaptive_wait)

    async def settle(self) -> None:
        """Wait until the examiner has answered what was said so far (used by tests)."""
        while self._pause_task and not self._pause_task.done():
            await asyncio.wait([self._pause_task])

    async def _answer_after_pause(self) -> None:
        try:
            await asyncio.sleep(self._wait_for(" ".join(self._pending)))
            # They may only be breathing or searching for a word: the examiner speaks only after their voice has been quiet for
            # QUIET_BEFORE_REPLY_S, and keeps waiting for as long as they are talking.
            while self._speaking_now() or self.clock() - self._last_voice_at < QUIET_BEFORE_REPLY_S:
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            return
        text, self._pending = " ".join(self._pending).strip(), []
        if not text or self.phase == DONE:
            return
        self._responding = True
        try:
            async with self._lock:
                await self._respond(text)
        except Exception as e:                      # a bug or a TTS hiccup must not leave the candidate talking to nobody
            log.exception("examiner turn failed")
            await self.emit({"type": "note", "text": f"error in this turn: {type(e).__name__}: {e}"[:300]})
            try:
                await self.say(SCRIPT["recover"])
            except Exception:
                log.exception("could not even say the recovery line")
        except asyncio.CancelledError:
            # Only ever cancelled while the LLM was writing the question (see on_candidate_turn): nothing was
            # spoken or changed yet, so give the answer back and let the new wait include what came after it.
            if self.history and self.history[-1] == ("candidate", text):
                self.history.pop()
            self._pending.insert(0, text)
        finally:
            self._responding = False

    # ---- "I want to finish the test" and irrelevant questions -------------------------------------------
    async def _ask_to_finish(self) -> None:
        """They asked to stop: do not just end it, ask whether they really want to finish or carry on."""
        self.confirm_end, self.finish_unclear = True, 0
        await self.emit({"type": "note", "text": "asked to finish: the examiner asks finish or continue"})
        await self.say(SCRIPT["finishAsk"])

    async def _answer_finish_question(self, text: str) -> None:
        choice = finish_answer(text)
        await self.emit({"type": "note", "text": f"answer to finish-or-continue: {choice}"})
        if choice == "unclear" and self.finish_unclear == 0:
            self.finish_unclear = 1                 # a bare "yes" could mean either: ask once more, plainly
            await self.say(SCRIPT["finishUnclear"])
            return
        self.confirm_end = False
        if choice == "finish":
            await self.close(SCRIPT["finishDone"], reason="ended_by_candidate")
        elif self.phase == PART2_SPEAK:             # continue (or still unclear): back to the talk, the clock restarts
            self.long_turn_last, self.p2_nudges, self._p2_time_said = self.clock(), 0, False
            await self.say(SCRIPT["finishContinueTalk"])
        else:
            await self.say(f"{SCRIPT['finishContinue']} {self.last_question}".strip())

    async def _handle_off_topic(self) -> None:
        """An irrelevant question ("Are you an AI?", "Can I change the topic?"): the 1st gets a reminder and the question
        again, the 2nd the same plus a warning, the 3rd ends the test."""
        self.off_topic_count += 1
        n, limit = self.off_topic_count, self.off_topic_limit
        await self.emit({"type": "note", "text": f"irrelevant question {n} of {limit}" + (": ending the test" if n >= limit else "")})
        if n >= limit:
            await self.close(SCRIPT["offTopicEnd"], reason="off_topic")
        elif n == limit - 1:
            await self.say(f"{SCRIPT['offTopic']} {SCRIPT['offTopicWarn']} {self.last_question}".strip())
        else:
            await self.say(f"{SCRIPT['offTopic']} {self.last_question}".strip())

    async def _respond(self, text: str) -> None:
        if self._late_continuation:
            # The end of the previous answer: join it to that answer, then, once they are really done, ask the new question again
            # (they were talking over it and may not have heard it). No new question is made up.
            self._late_continuation = False
            i = max((k for k, (who, _t) in enumerate(self.history) if who == "candidate"), default=None)
            if i is not None:
                self.history[i] = ("candidate", f"{self.history[i][1]} {text}")
            await self.say(self.last_question, origin="repeat")
            return
        self.history.append(("candidate", text))
        p = self.phase
        gave_name = p in (INTRO, NAME) and bool(extract_call_name(text) or (p == NAME and extract_name(text))
                                                or (p == INTRO and NAME_GIVEN.search(text)))         # "I'm Rahim Ahmed, what's your name?" is not a strike
        if self.confirm_end:
            await self._answer_finish_question(text)
        elif is_finish_request(text) and p not in (DONE, PART2_PREP):
            await self._ask_to_finish()
        elif p in (PART1, PART3) and is_repeat_request(text) and self.last_question:
            await self.repeat_question()            # they asked for it: say it again (simpler words in Part 3)
        elif p in (INTRO, NAME, PART1, PART2_FOLLOWUP, PART3) and not gave_name and self.last_question \
                and is_off_topic_question(text):
            # "Are you an AI?", "What's your name?", "How am I doing?": never answered; remind them and re-ask
            await self._handle_off_topic()
        elif p == INTRO:
            called = extract_call_name(text)
            if called:                              # "You can call me Rahim": do not ask "what can I call you?" again
                self.name = called
                self.known.append(f"likes to be called {called}")
                await self.start_part1(f"Thank you, {called}. " + SCRIPT["part1Intro"])
            else:
                await self.set_phase(NAME)
                self.last_question = SCRIPT["callName"].replace("Thank you. ", "")
                await self.say(SCRIPT["callName"])
        elif p == NAME:
            self.name = extract_call_name(text) or extract_name(text)
            if self.name:
                self.known.append(f"likes to be called {self.name}")
            lead = f"Thank you, {self.name}." if self.name else "Thank you."
            await self.start_part1(lead + " " + SCRIPT["part1Intro"])
        elif p == PART1:
            await self.part1_next(text)
        elif p == PART2_INTRO:
            await self.show_card()
        elif p == PART2_FOLLOWUP:
            await self.start_part3()
        elif p == PART3:
            await self.part3_next(text)

    def ack(self, answer: str, topic_change: bool = False) -> str:
        """Neutral acknowledgement ("Okay.", "Thank you.") to put before the next question; often empty."""
        a = self.acks.pick(answer, topic_change)
        return f"{a} " if a else ""

    async def repeat_question(self) -> None:
        """Only reached when the candidate really asked: Part 1 word for word, Part 3 in simpler words."""
        q = self.last_question
        if self.phase == PART3:
            q = await rules.rephrase_question(q, self.llm)
        await self.say(q, origin="rephrase" if self.phase == PART3 else "repeat")

    # ---- Part 1 ----------------------------------------------------------------------------------
    def _topic(self) -> dict:
        return self.plan["part1"][self.topic_idx]

    async def start_part1(self, lead: str) -> None:
        await self.set_phase(PART1)
        self.topic_idx, self.q_in_topic = 0, 0
        await self.ask_bank_question(first_topic=True, lead=lead)

    async def ask_bank_question(self, first_topic: bool, lead: str = "") -> None:
        t = self._topic()
        self.topic_t0 = self.elapsed()
        self.topic_slice = self._slice_for_topic()
        self._last_was_probe = False
        self._probes_in_topic = 0
        self._since_probe += 1
        await self.emit({"type": "note", "text": f"Part 1 topic {self.topic_idx + 1} ({t['topic']}): about {self.topic_slice:.0f} s"
                                                 f" of {self.cfg['p1_max']} s, {self.elapsed():.0f} s used"})
        opener = (SCRIPT["topicFirst"] if first_topic else SCRIPT["topicNext"]) + f" {rules.lower_first(t['topic'])}."
        q = t["questions"][0]["text"]
        self.q_in_topic = 1
        self.asked.append(q)
        self.last_question = q
        await self.say(" ".join(x for x in (lead, opener, q) if x), origin="bank")

    def _p1_target(self) -> float:
        return (self.cfg["p1_min"] + self.cfg["p1_max"]) / 2

    def _slice_for_topic(self) -> float:
        """How long this topic may take: the time left in Part 1 shared between the main topics still to come."""
        if self.topic_idx >= CORE_TOPICS:
            return RESERVE_SLICE_S
        return max(MIN_TOPIC_SLICE_S, (self._p1_target() - self.elapsed()) / (CORE_TOPICS - self.topic_idx))

    def _topic_done(self) -> bool:
        """Time (not a question count) ends a topic: its share is used up, or the answers have dried up."""
        if self.q_in_topic < MIN_Q_PER_TOPIC:
            return False
        if self.elapsed() - self.topic_t0 >= self.topic_slice:
            return True
        said = [t for who, t in self.history if who == "candidate"][-2:]
        return self.q_in_topic >= 3 and len(said) == 2 and all(len(t.split()) <= 3 for t in said)

    def _probe_ok(self, part: int) -> bool:
        """Follow-ups ("Could you give me an example?") are an occasional touch, not a habit: never two in a row, at least two
        questions between them, at most one per Part 1 topic and three in the whole of Part 1."""
        if self._last_was_probe or self._since_probe < 2:
            return False
        return part == 3 or (self._probes_in_topic < 1 and self._p1_probes < 3)

    async def _ask_probe(self, nq) -> None:
        """A natural follow-up to a very short answer ("Why is that?"): no lead-in, and it does not count as a topic question."""
        self._last_was_probe = True
        self._probes_in_topic += 1
        self._p1_probes += 1 if self.phase == PART1 else 0
        self._since_probe = 0
        self.last_question = nq.say
        await self.say(nq.say, origin=nq_origin(nq), why=self._why(nq))

    async def part1_next(self, answer: str) -> None:
        c, el = self.cfg, self.elapsed()
        if el >= c["p1_max"] or (el >= self._p1_target() and self.q_in_topic >= MIN_Q_PER_TOPIC):
            await self.start_part2_intro()
            return
        probe = rules.wants_probe(answer, 1, self._probe_ok(1))
        if not probe and self._topic_done():
            await self.next_topic_or_part2(answer)
            return
        t = self._topic()
        frames = [q["text"] for q in t["questions"]]
        left = self.unasked(frames)
        if not left and not probe:                    # bank used up: move on, never repeat a question
            await self.next_topic_or_part2(answer)
            return
        inp = NextQuestionInput(
            part=1, topic=t["topic"], frames=frames, asked=list(self.asked),
            question_number=self.q_in_topic + 1, questions_on_topic=self.q_target, history=list(self.history),
            fallback=left[0] if left else "", known=list(self.known), probe_ok=self._probe_ok(1))
        nq = await rules.next_question(inp, self.llm, self.test_id)
        if nq.origin == "probe":
            await self._ask_probe(nq)
            return
        if not nq.say:
            await self.next_topic_or_part2(answer)
            return
        if nq.reply == "redirect":                    # off-test question: remind, re-ask (or warn, or end), do not advance
            await self._handle_off_topic()
            return
        self._last_was_probe = False
        self._since_probe += 1
        self.known.extend(f for f in nq.facts if f not in self.known)
        self.q_in_topic += 1
        self.asked.append(rules.question_part(nq.say))
        self.last_question = rules.question_part(nq.say)
        await self.say(self._lead(answer) + nq.say, origin=nq_origin(nq), why=self._why(nq))

    def unasked(self, frames: list[str]) -> list[str]:
        """Bank questions that have not been asked yet (or anything very similar)."""
        prev = [rules.question_part(a) for a in self.asked]
        return [f for f in frames if not any(rules.similarity(rules.question_part(f), p) >= 0.6 for p in prev)]

    async def next_topic_or_part2(self, answer: str = "") -> None:
        nxt = self.topic_idx + 1
        # after the three main topics a reserve topic is only worth starting if there is real time left
        if nxt >= len(self.plan["part1"]) or (nxt >= CORE_TOPICS and self.elapsed() >= self._p1_target() - 40):
            await self.start_part2_intro()
            return
        self.topic_idx = nxt
        await self.ask_bank_question(first_topic=False, lead=self._lead(answer, topic_change=True))

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
        self.long_turn, self.long_turn_last, self.p2_nudges = [], 0.0, 0
        self._p2_time_said = False
        card = self.plan["cueCard"]
        await self.set_phase(PART2_SPEAK, cue_card={"prompt": card["prompt"], "bullets": card["bullets"], "closing": card["closing"]})
        await self.say(SCRIPT["part2Start"])

    def _p2_started(self) -> bool:
        """True once the candidate has really said something in the long turn (not just a stray word or two)."""
        return sum(len(t.split()) for t in self.long_turn) >= P2_REAL_WORDS

    async def end_long_turn(self, gave_up: bool = False, time_up: bool = False, cut: bool = False) -> None:
        """The talk is over. 'Thank you.' and one short question about what they said.

        time_up: the two minutes ran out, so the examiner says so ("Thank you, your time is up."); cut: they were still speaking
        when even the extra time ran out ("I'm sorry to stop you, but your time is up.").
        If they said little or nothing, no question is made up about it: the examiner moves straight on to Part 3."""
        talk = " ".join(self.long_turn).strip()
        if talk:
            self.history.append(("candidate", talk))
        stop = SCRIPT["part2TimeUpCut"] if cut else SCRIPT["part2TimeUp"] if time_up else SCRIPT["part2Stop"]
        if len(talk.split()) < P2_ENOUGH_WORDS:
            if gave_up or not talk:
                await self.start_part3(lead=SCRIPT["part2Skip"])
            else:
                await self.start_part3(lead=f"{stop} {SCRIPT['part2MoveOn']}" if time_up else stop)
            return
        await self.set_phase(PART2_FOLLOWUP)
        card = self.plan["cueCard"]["prompt"]
        prompt = (f'Part 2 has just ended. The candidate talked about: "{card}".\n'
                  f"What they said (speech recognition, may contain errors): {talk}\n"
                  "Ask ONE short rounding-off question, as a real IELTS examiner does after Part 2 (under 12 words, ending with a "
                  "question mark). It must be about the MAIN subject of the topic, not a small incidental detail they happened to "
                  "mention (not a tea stall, a colour, a brand), be easy to answer in a sentence or two, and link to the candidate's "
                  'own life, habits, feelings or plans, for example "Do you often get stuck in traffic like that?", '
                  '"Do you still have it?", "Do you think you will go there again?", "Did you tell anyone about it?", '
                  '"Do many people in your country do this?". '
                  "Use only what they said; never add or assume any detail they did not mention, and never refer to "
                  'the conversation, the talk, or what they "said" or "mentioned". '
                  "Do not use a name or word they did not say. "
                  'Reply as JSON: {"say": "<the question>"}')
        js = await self.llm(rules.SYSTEM, prompt)
        q = rules.clean(js["say"]) if js and isinstance(js.get("say"), str) else ""
        follow_origin, follow_why = "ai:new", ""
        if (not q.endswith("?") or rules.BANNED.search(q) or q.count("?") != 1 or len(q.split()) > 14
                or META_TALK.search(q) or not _grounded(q, talk, card) or unverified_echoes(q, [talk])):
            why = "the LLM wrote nothing usable" if not q else "rejected: not a clean question or not about what was said"
            await self.emit({"type": "note", "text": f"no rounding-off question ({why}): thank them and go to Part 3"})
            await self.start_part3(lead=f"{stop} {SCRIPT['part2MoveOn']}" if time_up else stop)      # an invented or odd question is worse than none
            return
        self.last_question = q                       # so "continue" or an irrelevant question re-asks THIS question
        await self.say(f"{stop} {q}", origin=follow_origin, why=follow_why)

    # ---- Part 3 ----------------------------------------------------------------------------------
    async def start_part3(self, lead: str = "") -> None:
        card = self.plan["cueCard"]
        await self.set_phase(PART3)
        subject = card["topic"]
        first = self.plan["part3"]["questions"][0]
        self.part3_q = 1
        self._last_was_probe = False
        self.asked.append(first)
        self.last_question = first
        intro = f"{SCRIPT['part3Intro'](subject)} {SCRIPT['part3First']} {rules.lower_first(self.plan['part3']['topic'])}. {first}"
        await self.say(f"{lead} {intro}" if lead else intro, origin="bank")

    async def part3_next(self, answer: str) -> None:
        c, el = self.cfg, self.elapsed()
        total = self.clock() - self.t0
        target = (c["p3_min"] + c["p3_max"]) / 2
        if el >= c["p3_max"] or total >= c["total_max"] or (el >= target and self.part3_q >= 3):
            await self.close()
            return
        qs = self.plan["part3"]["questions"]
        probe = rules.wants_probe(answer, 3, self._probe_ok(3))
        # bank first; then the company's generic follow-ups; when nothing fresh is left, close the test
        left = self.unasked(qs) or self.unasked(PART3_FOLLOW_UPS)
        if not left and not probe:
            await self.close()
            return
        inp = NextQuestionInput(
            part=3, topic=self.plan["part3"]["topic"], frames=qs, asked=list(self.asked), question_number=self.part3_q + 1,
            questions_on_topic=8, history=list(self.history), cue_card=self.plan["cueCard"]["prompt"],
            fallback=left[0] if left else "", known=list(self.known), probe_ok=self._probe_ok(3))
        nq = await rules.next_question(inp, self.llm, self.test_id)
        if nq.origin == "probe":
            await self._ask_probe(nq)
            return
        if nq.reply == "redirect":                    # off-test question: remind, re-ask (or warn, or end), do not advance
            await self._handle_off_topic()
            return
        say = nq.say
        if not say:                                   # nothing suitable left in the bank: the company's generic follow-ups, then close
            generic = self.unasked(PART3_FOLLOW_UPS)
            say = generic[0] if generic else ""
        if not say:
            await self.close()
            return
        self._last_was_probe = False
        self._since_probe += 1
        self.known.extend(f for f in nq.facts if f not in self.known)
        self.part3_q += 1
        self.asked.append(rules.question_part(say))
        self.last_question = rules.question_part(say)
        await self.say(self._lead(answer) + say, origin=nq_origin(nq) if nq.say else "script:fallback", why=self._why(nq))

    async def close(self, line: str = "", reason: str = "completed") -> None:
        """Closing words ("Thank you. That is the end of the speaking test."), then the test is over.
        The page treats 'done' as the end, so it is sent only after the examiner has finished speaking.
        `reason` is sent with 'done' (the first reason given wins)."""
        self.end_reason = self.end_reason or reason
        self.muted, self.confirm_end = True, False
        await self.say(line or SCRIPT["closing"])
        await self._wait_for_speech_to_end()
        await self.set_phase(DONE)
        await self.finish()

    async def _wait_for_speech_to_end(self, start_within: float = 5.0, at_most: float = 25.0) -> None:
        if not self.await_audio:
            return
        t0 = self.clock()
        while not self.bot_speaking and self.clock() - t0 < start_within:
            await asyncio.sleep(0.1)
        while self.bot_speaking and self.clock() - t0 < at_most:
            await asyncio.sleep(0.1)
        await asyncio.sleep(1.0)                    # the browser still has about half a second of audio buffered

    # ---- skip button + timers --------------------------------------------------------------------
    def _drop_pending(self) -> None:
        """Forget an answer that was waiting for its pause (a skip or the end overrides it)."""
        if self._pause_task and not self._responding:
            self._pause_task.cancel()
        self._pending = []

    async def skip_part(self) -> None:
        self._drop_pending()
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
            await self.close(reason="skipped_to_end")

    async def _tick_loop(self) -> None:
        try:
            while self.phase != DONE:
                await asyncio.sleep(0.5)
                limit = self._limit(self.phase)
                try:
                    await self.send({"type": "timer", "phase": self.phase, "elapsed": round(self.elapsed(), 1), "limit": limit,
                                     "mic_chunks": self.mic_chunks, "mic_rms": round(self.mic_rms, 4)})
                    async with self._lock:
                        await self._on_tick(limit)
                except asyncio.CancelledError:
                    raise
                except Exception as e:              # one bad tick must not stop the timers for the rest of the test
                    log.exception("timer tick failed")
                    self._tick_errors += 1
                    if self._tick_errors in (1, 10, 100):
                        await self.emit({"type": "note", "text": f"error in a timer tick ({self._tick_errors}): {type(e).__name__}: {e}"[:300]})
        except asyncio.CancelledError:
            pass

    def _lead(self, answer: str, topic_change: bool = False) -> str:
        """What comes before the next question: the polite "let's move on" after an over-long answer, otherwise a (rare) acknowledgement."""
        if self._cut_next:
            self._cut_next = False
            return "Okay, thank you. " if topic_change else SCRIPT["moveOn"] + " "
        return self.ack(answer, topic_change)

    async def _check_answer_cap(self) -> bool:
        """An answer that goes on far too long, while the candidate is still talking: end it politely and ask the next question.
        Called with the session lock held (by the timer)."""
        cap = self.answer_cap.get(self.phase)
        if not cap or self._answer_since is None or self.confirm_end or self._responding or self.listening_blocked():
            return False
        if self.clock() - self._answer_since < cap:
            return False
        if not (self._speaking_now() or self.clock() - self._last_voice_at < ANSWER_CAP_QUIET_S):
            return False                              # they have stopped: the examiner answers in the normal way
        await self.emit({"type": "note", "text": f"the answer has gone on for {self.clock() - self._answer_since:.0f} s (limit {cap:.0f} s): "
                                                 "the examiner ends it politely and moves on"})
        if self._pause_task:
            self._pause_task.cancel()
        text, self._pending = " ".join(self._pending).strip(), []
        self._answer_since, self._cut_next, self._responding = None, True, True
        try:
            await self._respond(text or "(a very long answer)")
        finally:
            self._cut_next, self._responding = False, False
        return True

    async def _on_tick(self, limit) -> None:
        if self.phase in (PART1, PART3) and await self._check_answer_cap():
            return
        if self.phase == PART2_PREP and self.elapsed() >= limit:
            await self.start_long_turn()
        elif self.phase == PART2_SPEAK:
            if self.elapsed() >= limit:
                over = self.elapsed() - limit
                talking = self._speaking_now()
                if (talking or self.clock() - self._last_voice_at < P2_TRANSCRIPT_WAIT_S) and over < P2_FINISH_SENTENCE_S:
                    return                            # still talking (or their last words are being transcribed): let them finish
                await self.end_long_turn(time_up=True, cut=talking)       # "Thank you, your time is up."
            else:
                await self._part2_silence_check()
        elif self.phase == PART3 and self.elapsed() >= (limit or 0) + PART3_GRACE_S:
            # Part 3 time is up and nobody is answering: the real examiner would end the test, not wait for ever
            if not (self._pending or self._responding or self._speaking_now() or self.listening_blocked()):
                await self.close(reason="no_response")

    async def _part2_silence_check(self) -> None:
        """The candidate is quiet during the long turn and time remains.

        Started talking, then stopped:  "You still have time, so please tell me a little more about it." (once), then, if they
                                         say nothing more, the examiner thanks them and moves on.
        Never started:                   "Can you tell me about the topic you have been given?", then "You still have time,
                                         so please take a moment and tell me about the topic.", then moves on.
        """
        if self.p2_nudges >= 3 or self.confirm_end or self.listening_blocked() or self._line_waiting() or self._speaking_now():
            return                                    # moving on, waiting for "finish or continue", examiner talking, or they are talking
        if self.clock() - self._last_voice_at < VOICE_GRACE_S:
            return                                    # a breath between two sentences, or the transcript is still on its way
        started = self._p2_started()
        # Quiet time counts from the latest of: their last words, their voice last heard (a long answer is only transcribed
        # when they pause, so words alone would say "silent" while they are talking), the examiner finishing, the turn starting.
        since = max(self.long_turn_last, self._last_voice_at, self._bot_stopped_at, self._phase_start)
        quiet = self.clock() - since
        if started:
            need, line = (self.p2_early_giveup_s, None) if self._p2_time_said else (self.p2_early_s, SCRIPT["part2TimeMore"])
        elif self.p2_nudges == 0:
            need, line = self.p2_silence_s, SCRIPT["part2Prompt"]
        elif not self._p2_time_said:
            need, line = self.p2_remind_s, SCRIPT["part2Time"]
        else:
            need, line = self.p2_giveup_s, None
        if quiet < need:
            return
        if line is None:                              # nothing more is coming: thank them and go on
            self.p2_nudges = 3
            await self.end_long_turn(gave_up=not started)
            return
        if line in (SCRIPT["part2Time"], SCRIPT["part2TimeMore"]):
            self._p2_time_said = True
        self.p2_nudges += 1
        await self.say(line)

    async def _end_talk_soon(self) -> None:
        """The candidate said "that's all": give them a moment in case they go on, then thank them and move on."""
        try:
            await asyncio.sleep(DONE_TALKING_PAUSE_S)
            if self.phase != PART2_SPEAK or self.confirm_end:
                return
            if self._speaking_now() or self.clock() - self._last_voice_at < 1.2:
                return                                # they carried on after all
            async with self._lock:
                if self.phase == PART2_SPEAK:
                    await self.emit({"type": "note", "text": "the candidate said they had finished: moving on"})
                    await self.end_long_turn()
        except asyncio.CancelledError:
            pass

    # ---- hooks used by the pipeline taps ---------------------------------------------------------
    async def on_latency(self, seconds: float) -> None:
        load_guard.GUARD.record_delay(seconds)          # the whole service's recent reply delay decides whether to take new tests
        await self.emit({"type": "latency", "seconds": round(seconds, 2)})

    # ---- end -------------------------------------------------------------------------------------
    async def finish(self) -> Path | None:
        self._drop_pending()
        if self._ticker and self._ticker is not asyncio.current_task():     # never cancel the task that is saving
            self._ticker.cancel()
        self.muted = True
        self.end_reason = self.end_reason or "completed"
        self.status = "completed"
        await self.emit({"type": "done", "reason": self.end_reason})
        return self.save()

    def abort(self) -> Path | None:
        """Connection dropped: stop timers and save what we have. No events are sent."""
        if self._pause_task:
            self._pause_task.cancel()
        if self._ticker:
            self._ticker.cancel()
        self.muted = True
        if self.status not in ("completed", "failed"):      # a test that already finished (or crashed) keeps that status
            self.status, self.end_reason = "aborted", self.end_reason or "aborted"
        return self.save()

    def save(self) -> Path | None:
        if not self.log:
            return None
        RUNS.mkdir(exist_ok=True)
        path = RUNS / f"run_{time.strftime('%Y%m%d_%H%M%S')}_{self.test_id}.json"       # the id keeps two tests apart, and finds a test by its id
        lat = [e["seconds"] for e in self.log if e["type"] == "latency"]
        mic = {}
        if self._mic_pcm:
            import array, wave
            a = array.array("h", bytes(self._mic_pcm[: len(self._mic_pcm) // 2 * 2]))
            mic = {"mic_seconds": round(len(a) / 16000, 1), "mic_peak": round(max(abs(x) for x in a) / 32768, 4),
                   "mic_rms": round((sum(x * x for x in a) / len(a)) ** 0.5 / 32768, 4)}
            with wave.open(str(path.with_suffix(".wav")), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(self._mic_pcm))
        stamps = [e["at"] for e in self.log if "at" in e]
        path.write_text(json.dumps({**mic,
            "test_id": self.test_id, "external_user_id": self.external_user_id, "status": self.status or "aborted",
            "end_reason": self.end_reason, "started_at": stamps[0] if stamps else None, "ended_at": stamps[-1] if stamps else None,
            "topics": [t["topic"] for t in self.plan["part1"]], "card": self.plan["cueCard"]["prompt"],
            "name": self.name, "device": self.device, "known_facts": self.known, "mic_chunks_received": self.mic_chunks,
            "latencies_s": lat, "events": self.log}, indent=2), encoding="utf-8")
        return path
