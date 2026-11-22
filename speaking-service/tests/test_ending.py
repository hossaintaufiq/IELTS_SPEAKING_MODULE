"""The test ends the way a real IELTS test does: the examiner says thank you and closes, then the page is told it is over."""
import asyncio

import pytest

import worker.session as sess
from worker.examiner.speech import is_noise
from worker.session import ExamSession
from tests.test_listening import FakeTask, spoken, to_part1, llm_ok

CLOSING = "Thank you. That is the end of the speaking test."


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)


def make(events=None, clock=None):
    async def send(e):
        if events is not None:
            events.append(e)

    kw = {"clock": clock} if clock else {}
    s = ExamSession(send, seed=3, llm=llm_ok, hour=9, **kw)
    s.test_mode()
    s.task = FakeTask()
    return s


def test_end_button_makes_the_examiner_say_the_closing_words_before_done():
    events = []

    async def go():
        s = make(events)
        await to_part1(s)
        await s.handle_control({"action": "end"})
        return s

    s = asyncio.run(go())
    assert spoken(s)[-1] == CLOSING
    kinds = [(e["type"], e.get("role") or e.get("phase")) for e in events if e["type"] in ("transcript", "phase", "done")]
    assert kinds.index(("transcript", "examiner")) < kinds.index(("phase", "done")) < kinds.index(("done", None))
    assert s.phase == "done"


def test_end_before_the_test_started_just_ends():
    async def go():
        s = make()
        await s.handle_control({"action": "end"})
        return s

    s = asyncio.run(go())
    assert spoken(s) == []


def test_done_is_only_sent_after_the_closing_words_have_been_spoken():
    events = []

    async def go():
        s = make(events)
        s.await_audio = True
        await to_part1(s)
        task = asyncio.create_task(s.handle_control({"action": "end"}))
        await asyncio.sleep(0.3)                               # the examiner is "speaking" the goodbye
        s.bot_started()
        await asyncio.sleep(0.3)
        assert not any(e["type"] == "done" for e in events)    # the page must not stop the audio yet
        s.bot_stopped()
        await task
        return s

    s = asyncio.run(go())
    assert any(e["type"] == "done" for e in events) and s.phase == "done"


def test_silent_part3_is_closed_after_the_time_is_up_plus_a_grace_period():
    async def go():
        t = {"now": 0.0}
        s = make(clock=lambda: t["now"])
        await to_part1(s)
        await s.start_part3()
        limit = s._limit(s.phase)
        t["now"] = limit + 10
        await s._on_tick(limit)
        assert s.phase == "part3"                              # still in the grace period
        t["now"] = limit + sess.PART3_GRACE_S + 1
        await s._on_tick(limit)
        return s

    s = asyncio.run(go())
    assert s.phase == "done" and spoken(s)[-1] == CLOSING


@pytest.mark.parametrize("text", ["you you you you", "thank you thank you thank you thank you", "the the the the the"])
def test_repetition_loops_from_silence_are_noise(text):
    assert is_noise(text)


def test_a_real_answer_with_repeated_words_is_not_noise():
    assert not is_noise("very very good")
    assert not is_noise("I like it, I like it a lot because it is calm")
