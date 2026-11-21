import asyncio
import json

import pytest

import worker.session as sess
from worker.examiner.flow import FlowConfig, Phase
from worker.protocol import BrowserSerializer
from worker.session import ExamSession


class FakeTask:
    def __init__(self):
        self.frames = []

    async def queue_frames(self, frames):
        self.frames.extend(frames)


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)


def make(cfg=None):
    events = []

    async def send(e):
        events.append(e)

    s = ExamSession(send, cfg or FlowConfig(), seed=1)
    s.task = FakeTask()
    return s, events


def kinds(task):
    return [type(f).__name__ for f in task.frames]


def test_start_sets_part1_instructions_then_speaks_intro():
    async def go():
        s, ev = make()
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        return s, ev

    s, ev = asyncio.run(go())
    assert kinds(s.task) == ["LLMMessagesAppendFrame", "TTSSpeakFrame"]
    assert "PART 1" in s.task.frames[0].messages[0]["content"]
    assert not s.muted and s.started
    assert any(e["type"] == "transcript" and e["role"] == "examiner" for e in ev)


def test_full_walkthrough_with_part2_monologue_held():
    async def go():
        s, ev = make()
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        await s.advance()                       # -> PART1
        await s.advance()                       # -> PART2_PREP
        assert s.muted and s.flow.phase == Phase.PART2_PREP
        assert any(e.get("cue_card") for e in ev if e["type"] == "phase")
        await s.advance()                       # -> PART2_SPEAK
        assert s.hold and not s.muted
        assert await s.on_user_text("I want to talk about a park") is False   # held, not answered
        assert await s.on_user_text("it is near my house") is False
        await s.advance()                       # -> PART2_FOLLOWUP
        followup = s.task.frames[-1]
        assert followup.run_llm is True
        assert "park" in followup.messages[-1]["content"] and "near my house" in followup.messages[-1]["content"]
        assert not s.hold
        assert await s.on_user_text("yes") is True        # normal turns answered again
        await s.advance()                       # -> PART3
        assert s.task.frames[-1].run_llm is True
        await s.advance()                       # -> DONE (speaks goodbye, finishes)
        return s, ev

    s, ev = asyncio.run(go())
    assert s.flow.phase == Phase.DONE and s.muted
    assert ev[-1]["type"] == "done"
    saved = list(sess.RUNS.glob("run_*.json"))
    assert len(saved) == 1
    data = json.loads(saved[0].read_text())
    assert data["card"] and data["events"]


def test_timer_advances_phase():
    t = {"now": 0.0}

    async def go():
        events = []

        async def send(e):
            events.append(e)

        s = ExamSession(send, FlowConfig(part1_s=1), clock=lambda: t["now"], seed=1)
        s.task = FakeTask()
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        await s.advance()                       # PART1
        t["now"] = 2.0
        prev = s.flow.phase
        new = s.flow.tick()
        await s._enter(prev, new)
        return s

    assert asyncio.run(go()).flow.phase == Phase.PART2_PREP


def test_latency_is_logged_and_saved():
    async def go():
        s, ev = make()
        await s.on_latency(1.234)
        return s.abort()

    path = asyncio.run(go())
    assert json.loads(path.read_text())["latencies_s"] == [1.23]


def test_serializer_drops_audio_when_muted_and_routes_control():
    async def go():
        s, ev = make()
        ser = BrowserSerializer(s)
        assert s.muted
        assert await ser.deserialize(b"\x00\x00" * 640) is None
        s.muted = False
        frame = await ser.deserialize(b"\x00\x00" * 640)
        assert frame.sample_rate == 16000 and frame.num_channels == 1
        assert await ser.deserialize("not json") is None
        await ser.deserialize(json.dumps({"action": "start"}))
        s._ticker.cancel()
        return s

    assert asyncio.run(go()).started
