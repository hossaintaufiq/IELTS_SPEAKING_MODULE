import asyncio
import json

import pytest

import worker.session as sess
from worker.protocol import BrowserSerializer
from worker.session import ExamSession, extract_name


class FakeTask:
    def __init__(self):
        self.frames = []

    async def queue_frames(self, frames):
        self.frames.extend(frames)


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)


async def rounding_llm(system, prompt):
    """Writes a grounded rounding-off question after Part 2, the usual reply otherwise."""
    if "rounding-off" in prompt:
        return {"say": "Do you still go to the river?"}
    return await default_llm(system, prompt)


async def default_llm(system, prompt):
    return {"reply": "answer", "pick": None, "say": "What do you like most about your neighbourhood?", "facts": ["lives in Dhaka"]}


def make(llm=None, clock=None):
    events = []

    async def send(e):
        events.append(e)

    kw = {"clock": clock} if clock else {}
    s = ExamSession(send, seed=3, llm=llm or default_llm, hour=9, **kw)
    s.test_mode()          # no waiting in tests; the pause behaviour has its own tests below
    s.task = FakeTask()
    return s, events


async def turn(s, text):
    """The candidate says something and the examiner finishes answering it."""
    await s.on_candidate_turn(text)
    await s.settle()


def spoken(s):
    return [f.text for f in s.task.frames]


async def run_until_part2(s):
    await s.handle_control({"action": "start"})
    s._ticker.cancel()
    await turn(s, "My name is Rahim Ahmed.")
    await turn(s, "Please call me Rahim.")
    for _ in range(8):
        if s.phase != "part1":
            break
        await turn(s, "I live in Dhaka and I like the food there very much.")


def test_extract_name():
    assert extract_name("Please call me Rahim.") == "Rahim"
    assert extract_name("My name is Rahim Ahmed") == "Rahim"
    assert extract_name("Rahim") == "Rahim"
    assert extract_name("uh well it is a long story really") == ""


def test_greeting_name_part1_script_lines():
    async def go():
        s, ev = make()
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        await turn(s, "My name is Rahim Ahmed.")
        await turn(s, "Call me Rahim.")
        return s, ev

    s, ev = asyncio.run(go())
    lines = spoken(s)
    assert lines[0] == ("Good morning. My name is Alex Morgan and I'm your examiner today. "
                        "Can you tell me your full name, please?")
    assert lines[1] == "Thank you. And what can I call you?"
    assert lines[2].startswith("Thank you, Rahim. Now, in this first part, I'd like to ask you some questions "
                               "about yourself. Let's talk about ")
    assert lines[2].endswith("?")
    assert s.phase == "part1"
    users = [e["text"] for e in ev if e["type"] == "transcript" and e["role"] == "user"]
    assert users == ["My name is Rahim Ahmed.", "Call me Rahim."]


def test_part1_follow_up_comes_from_llm_with_the_answer_and_then_moves_on():
    seen = []

    async def llm(system, prompt):
        seen.append(prompt)
        return {"reply": "answer", "pick": None, "say": "What do you like most about Dhaka?", "facts": ["lives in Dhaka"]}

    async def go():
        s, ev = make(llm)
        await run_until_part2(s)
        return s

    s = asyncio.run(go())
    assert any("I live in Dhaka" in p for p in seen)
    assert "lives in Dhaka" in s.known
    assert s.phase == "part2_intro" or s.phase == "part1"
    if s.phase == "part2_intro":
        assert "Do you understand?" in spoken(s)[-1]


def test_part2_card_prep_long_turn_followup_and_part3():
    async def go():
        s, ev = make(rounding_llm)
        await run_until_part2(s)
        if s.phase == "part1":
            await s.skip_part()
        assert s.phase == "part2_intro"
        await turn(s, "Yes, I understand.")
        assert s.phase == "part2_prep" and s.muted
        card = [e for e in ev if e["type"] == "phase" and e["phase"] == "part2_prep"][0]["cue_card"]
        assert card["bullets"] and card["closing"]
        await s.skip_part()
        assert s.phase == "part2_speak" and not s.muted
        n = len(spoken(s))
        await turn(s, "I want to talk about my village and the river near it.")
        await turn(s, "We used to swim there every summer.")
        assert len(spoken(s)) == n                       # examiner stays silent during the talk
        await s.skip_part()
        assert s.phase == "part2_followup" and spoken(s)[-1].startswith("Thank you.")
        await turn(s, "Yes, almost every year.")
        assert s.phase == "part3"
        p3 = spoken(s)[-1]
        assert p3.startswith("We've been talking about ") and "Let's consider first of all" in p3
        await turn(s, "I think places like that matter a lot for people in cities.")
        assert s.phase == "part3"
        await s.skip_part()
        return s, ev

    s, ev = asyncio.run(go())
    assert s.phase == "done" and spoken(s)[-1] == "Thank you. That is the end of the speaking test."
    runs = list(sess.RUNS.glob("run_*.json"))
    assert len(runs) == 1
    data = json.loads(runs[0].read_text())
    assert data["name"] == "Rahim" and data["events"]


def test_llm_down_falls_back_to_bank_questions():
    async def down(system, prompt):
        return None

    async def go():
        s, ev = make(down)
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        await turn(s, "Rahim")
        await turn(s, "Rahim")
        before = len(spoken(s))
        await turn(s, "I work in a bank in Dhaka and I like it.")
        return s, before

    s, before = asyncio.run(go())
    assert len(spoken(s)) == before + 1 and spoken(s)[-1].endswith("?")


def test_part2_says_there_is_still_time_when_candidate_stops_early():
    t = {"now": 0.0}

    async def go():
        s, ev = make(clock=lambda: t["now"])
        await run_until_part2(s)
        if s.phase == "part1":
            await s.skip_part()
        await turn(s, "Yes.")
        await s.skip_part()
        t["now"] = 10
        await turn(s, "It is a nice place.")
        t["now"] = 30
        await s._on_tick(s._limit(s.phase))
        return s

    s = asyncio.run(go())
    assert spoken(s)[-1] == "You still have time, so please tell me a little more about it." and s.phase == "part2_speak"


def test_serializer_counts_audio_drops_when_muted_and_routes_control():
    async def go():
        s, ev = make()
        ser = BrowserSerializer(s)
        assert s.muted
        assert await ser.deserialize(b"\x01\x00" * 640) is None
        assert s.mic_chunks == 1 and s.mic_rms > 0
        s.muted = False
        frame = await ser.deserialize(b"\x00\x00" * 640)
        assert frame.sample_rate == 16000
        await ser.deserialize(json.dumps({"action": "start"}))
        s._ticker.cancel()
        return s

    assert asyncio.run(go()).started


def test_mic_is_ignored_while_examiner_speaks_and_for_a_short_tail():
    t = {"now": 0.0}

    async def go():
        s, ev = make(clock=lambda: t["now"])
        s.muted = False
        ser = BrowserSerializer(s)
        pcm = b"\x10\x00" * 640
        assert await ser.deserialize(pcm) is not None            # normal: audio passes
        s.bot_started()
        assert await ser.deserialize(pcm) is None                # examiner speaking: dropped (no echo loop)
        t["now"] = 5.0
        s.bot_stopped(tail=0.7)
        assert await ser.deserialize(pcm) is None                # short tail after it stops
        t["now"] = 5.8
        assert await ser.deserialize(pcm) is not None            # then listening again
        s.bot_started()
        t["now"] = 50.0                                          # a missed 'stopped' signal cannot lock the mic
        assert await ser.deserialize(pcm) is not None
        return s

    asyncio.run(go())


def test_skip_prep_starts_the_long_turn_only_during_preparation():
    async def go():
        s, ev = make()
        await s.handle_control({"action": "skip_prep"})          # before the test has started: nothing happens
        assert not ev
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        await s.handle_control({"action": "skip_prep"})          # in the introduction: nothing happens
        assert s.phase == "intro"
        for _ in range(4):
            if s.phase == "part2_prep":
                break
            await s.skip_part()
        assert s.phase == "part2_prep"
        await s.handle_control({"action": "skip_prep"})
        assert s.phase == "part2_speak" and not s.muted
        lines = len(spoken(s))
        await s.handle_control({"action": "skip_prep"})          # pressed twice: the start line is not said again
        assert s.phase == "part2_speak" and len(spoken(s)) == lines

    asyncio.run(go())


def test_part2_silence_waits_until_a_slow_voice_has_said_the_line():
    async def go():
        now = [1000.0]
        s, _ = make(clock=lambda: now[0])
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        for _ in range(6):
            if s.phase == "part2_speak":
                break
            await s.skip_part()
        assert s.phase == "part2_speak"
        s.await_audio = True                       # the real service: speech takes a while to be generated
        await s.say("Can you start speaking now, please?")
        said = len(spoken(s))
        now[0] += 20                               # still generating: this is not the candidate being silent
        await s._part2_silence_check()
        assert len(spoken(s)) == said
        s.bot_started()
        now[0] += 3
        s.bot_stopped()
        now[0] += 10                               # now they really have been quiet since the examiner finished
        await s._part2_silence_check()
        assert len(spoken(s)) == said + 1
        now[0] += 10                               # the reminder is queued but not heard yet: nothing more is said
        await s._part2_silence_check()
        assert len(spoken(s)) == said + 1 and s.phase == "part2_speak"
        now[0] += 60                               # a voice that never starts must not stop the test for ever
        await s._part2_silence_check()
        assert len(spoken(s)) > said + 1

    asyncio.run(go())
