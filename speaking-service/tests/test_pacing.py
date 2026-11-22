"""Patience and natural manner: adaptive wait, thinking noises, South Asian learner phrases, acknowledgements."""
import asyncio
import random

import pytest

import worker.session as sess
from worker.examiner.naturalness import AckPicker
from worker.examiner.pacing import wait_seconds
from worker.examiner.speech import is_noise, is_repeat_request, looks_unfinished
from worker.session import ExamSession
from tests.test_listening import FakeTask, to_part1, spoken

KW = dict(short_extra=1.2, unfinished_extra=1.5, think_extra=3.0, max_wait=7.0)


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)


# ---- how long to wait --------------------------------------------------------------------------
def test_short_answer_waits_longer_than_a_full_sentence():
    short = wait_seconds("Yes.", 2.0, **KW)
    full = wait_seconds("I live in a flat in Dhaka with my parents and my younger brother, and I like it a lot because it is close to my university and to the market.", 2.0, **KW)
    assert short > 2.0 > full


def test_unfinished_and_thinking_answers_get_extra_time_but_never_more_than_the_cap():
    assert wait_seconds("I like cooking because", 2.0, **KW) >= 3.5
    assert wait_seconds("Let me think, how can I say", 2.0, **KW) >= 5.0
    assert wait_seconds("Let me think, how can I say, you know, and", 2.0, **KW) <= 7.0


def test_part3_base_is_longer_than_part1_and_adaptive_can_be_switched_off():
    assert wait_seconds("It depends on many things in life.", 2.6, **KW) > wait_seconds("It depends on many things in life.", 2.0, **KW)
    assert wait_seconds("Yes.", 2.0, adaptive=False, **KW) == 2.0


# ---- South Asian learner speech --------------------------------------------------------------------
@pytest.mark.parametrize("text", ["Ummm", "Hmm... aaa", "Erm", "Aaaa", "Thank you sir.", "thank you madam", "Mmm"])
def test_thinking_noises_and_politeness_are_not_answers(text):
    assert is_noise(text)


@pytest.mark.parametrize("text", ["Yes sir.", "I am", "Am I allowed?", "Mm... I like Dhaka", "No."])
def test_real_answers_are_kept(text):
    assert not is_noise(text)


@pytest.mark.parametrize("text", ["Excuse me sir?", "Please speak slowly", "What is the meaning of the question?",
                                  "One more time please", "I can't understand"])
def test_learner_ways_of_asking_for_help_are_repeat_requests(text):
    assert is_repeat_request(text)


@pytest.mark.parametrize("text", ["I like to cook, for example", "My hobby is, I mean", "Actually", "I think", "Because of"])
def test_searching_for_words_is_unfinished(text):
    assert looks_unfinished(text)


# ---- acknowledgements --------------------------------------------------------------------------
def test_acknowledgements_are_neutral_varied_and_follow_the_length_of_the_answer():
    p = AckPicker(random.Random(1), probability=1.0)
    seen = [p.pick("word " * 30) for _ in range(12)]
    assert all(a for a in seen) and all(a != b for a, b in zip(seen, seen[1:]))     # never twice in a row
    banned = ("great", "interesting", "good", "nice", "wonderful", "i see", "sounds")
    assert not any(b in a.lower() for a in seen for b in banned)                    # the company rules: no praise
    assert "thank" in p.pick("word " * 30, topic_change=True).lower()
    assert AckPicker(random.Random(1), probability=0.0).pick("a long answer " * 10) == ""


def llm_q(q):
    async def llm(system, prompt):
        return {"reply": "answer", "pick": None, "say": q, "facts": []}
    return llm


def test_examiner_acknowledges_before_the_next_question_but_the_question_is_still_asked_once():
    async def go():
        async def send(e):
            pass
        s = ExamSession(send, seed=3, llm=llm_q("What do you like most about your home town?"), hour=9)
        s.test_mode()
        s.acks.probability = 1.0
        s.task = FakeTask()
        await to_part1(s)
        await s.on_candidate_turn("I live in a small town near the river and I have lived there all my life.")
        await s.settle()
        return s

    s = asyncio.run(go())
    line = spoken(s)[-1]
    assert line.endswith("What do you like most about your home town?")
    assert line != "What do you like most about your home town?"                    # something neutral came first
    assert s.last_question == "What do you like most about your home town?"          # never stored with the acknowledgement
    assert s.asked[-1] == "What do you like most about your home town?"


# ---- speech that arrives while the next question is being written ---------------------------------------
def test_more_speech_during_the_llm_wait_takes_the_question_back_and_one_merged_answer_is_given():
    prompts = []

    async def go():
        async def send(e):
            pass
        gate = asyncio.Event()

        async def slow_llm(system, prompt):
            prompts.append(prompt)
            if len(prompts) == 1:
                await gate.wait()                                   # first attempt: the LLM is still thinking
            return {"reply": "answer", "pick": None, "say": "What do you like most about your home town?", "facts": []}

        s = ExamSession(send, seed=3, llm=slow_llm, hour=9)
        s.test_mode()
        s.task = FakeTask()
        await to_part1(s)
        n = len(spoken(s))
        await s.on_candidate_turn("I live in a small town near the river")
        await asyncio.sleep(0.05)                                   # the examiner starts writing its question...
        assert s._responding and s._interruptible
        await s.on_candidate_turn("and I have lived there all my life because my family is there.")
        await s.settle()
        return s, n

    s, n = asyncio.run(go())
    assert len(spoken(s)) == n + 1                                  # exactly one question, not one per fragment
    cands = [t for who, t in s.history if who == "candidate"]
    assert cands[-1].startswith("I live in a small town near the river and I have lived there")
    assert len(prompts) == 2 and "because my family is there" in prompts[1]
    assert sum(1 for c in cands if "small town" in c) == 1          # the first attempt was removed, not duplicated


def test_a_filler_while_waiting_keeps_the_examiner_waiting():
    async def go():
        async def send(e):
            pass
        s = ExamSession(send, seed=3, llm=llm_q("What do you like most about your home town?"), hour=9)
        s.test_mode()
        s.pause_s = 0.3
        s.task = FakeTask()
        await to_part1(s)
        n = len(spoken(s))
        await s.on_candidate_turn("I live in a small town")
        await asyncio.sleep(0.2)
        await s.on_candidate_turn("ummm")                           # still thinking: the clock starts again
        await asyncio.sleep(0.2)
        early = len(spoken(s)) == n                                 # 0.4 s after the answer, but only 0.2 s after the filler
        await s.settle()
        return early, len(spoken(s)) == n + 1

    early, answered = asyncio.run(go())
    assert early and answered
