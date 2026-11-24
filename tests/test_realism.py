"""Closer to a real examiner: the two-minute mark, the rounding-off question, and what the recogniser is fed."""
import asyncio

import numpy as np
import pytest

import worker.session as sess
from worker.stt import echoes_prompt, initial_prompt, keyterms_for, level_up
from tests.test_listening import into_long_turn, make_timed, spoken


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)


async def grounded(system, prompt):
    return {"say": "Did you ever find your phone?"}


TALK = ("I want to talk about the day I lost my phone in a crowded bus, it had all my photos and my contacts and "
        "I was very worried, so I went back to the bus stop and asked many people.")


def test_at_two_minutes_a_candidate_mid_sentence_is_allowed_to_finish_but_not_for_long():
    async def go():
        s, t = make_timed(grounded)
        await into_long_turn(s)
        limit = s._limit(s.phase)
        await s.on_candidate_turn(TALK)
        t["now"] = limit + 0.5
        s.vad_started()                                              # still speaking at the two-minute mark
        await s._on_tick(limit)
        assert s.phase == "part2_speak"                              # the sentence is allowed to finish
        t["now"] = limit + 3
        await s._on_tick(limit)
        assert s.phase == "part2_speak"
        t["now"] = limit + sess.P2_FINISH_SENTENCE_S + 1             # but not for ever
        s.vad_started()
        await s._on_tick(limit)
        return s

    assert asyncio.run(go()).phase == "part2_followup"


def test_at_two_minutes_a_silent_candidate_is_thanked_straight_away():
    async def go():
        s, t = make_timed(grounded)
        await into_long_turn(s)
        limit = s._limit(s.phase)
        await s.on_candidate_turn(TALK)
        t["now"] = limit
        await s._on_tick(limit)
        return s

    s = asyncio.run(go())
    assert s.phase == "part2_followup" and spoken(s)[-1].startswith("Thank you, your time is up.")


@pytest.mark.parametrize("bad", ["What was important about this conversation?", "Why did you mention the topic of the bus?",
                                 "What did you say about your phone?", "Did the dragon fly over the mountain?",
                                 "Can you tell me in great detail about every single thing that happened to your phone on that day?"])
def test_rounding_off_question_must_be_short_grounded_and_not_about_the_conversation(bad):
    async def llm(system, prompt):
        return {"say": bad}

    async def go():
        s, t = make_timed(llm)
        await into_long_turn(s)
        await s.on_candidate_turn(TALK)
        await s.end_long_turn()
        return s

    s = asyncio.run(go())
    assert s.phase == "part3" and spoken(s)[-1].startswith("Thank you. We've been talking about")     # no odd question: on to Part 3
    assert not any("anything more" in line for line in spoken(s))


def test_a_good_rounding_off_question_is_kept():
    async def llm(system, prompt):
        return {"say": "Did you ever find your phone?"}

    async def go():
        s, t = make_timed(llm)
        await into_long_turn(s)
        await s.on_candidate_turn(TALK)
        await s.end_long_turn()
        return s

    assert spoken(asyncio.run(go()))[-1] == "Thank you. Did you ever find your phone?"


def test_default_waits_are_short_enough_to_feel_like_a_conversation():
    async def send(e):
        pass

    s = sess.ExamSession(send, seed=1, hour=9)
    assert s.pause_s <= 2.5 and s.p3_pause_s <= 3.5 and s.max_wait_s <= 10.0   # patient on purpose: candidates must be able to finish
    assert s.p2_silence_s <= 6 and s.p2_early_s <= 4 and s.p2_early_giveup_s <= 6


# ---- what the recogniser is given ---------------------------------------------------------------------
def test_quiet_speech_is_brought_up_to_a_normal_level_and_loud_speech_is_left_alone():
    rng = np.random.default_rng(0)
    quiet = (rng.standard_normal(16000 * 3) * 0.025).astype(np.float32)
    louder = level_up(quiet)
    assert np.sqrt((louder ** 2).mean()) > 2 * np.sqrt((quiet ** 2).mean()) and np.abs(louder).max() <= 1.0
    loud = (rng.standard_normal(16000 * 3) * 0.12).astype(np.float32)
    assert np.array_equal(level_up(loud), loud)
    silence = np.zeros(16000, dtype=np.float32)
    assert np.array_equal(level_up(silence), silence)                      # never amplifies silence into noise


def test_the_prompt_stays_short_and_its_own_words_are_never_taken_as_speech():
    prompt = initial_prompt("What do you like about Chattogram food markets?")
    assert len(prompt.split()) <= 20 and "IELTS" not in prompt
    assert echoes_prompt("Bangladesh Dhaka Sylhet", prompt)
    assert not echoes_prompt("I live in Dhaka", prompt)
    assert not echoes_prompt("Dhaka", prompt)                              # a one-word answer can be a real answer


# ---- the two minutes are over while the candidate is still talking ------------------------------------------------
def test_time_up_is_said_politely_and_the_last_words_are_not_lost():
    async def go():
        s, t = make_timed(grounded)
        await into_long_turn(s)
        limit = s._limit(s.phase)
        await s.on_candidate_turn(TALK)
        t["now"] = limit + 1
        s.vad_started()                                              # speaking at the two-minute mark: no interruption
        await s._on_tick(limit)
        assert s.phase == "part2_speak"
        t["now"] = limit + 5
        s.vad_stopped()                                              # they finish their sentence; the transcript is still on its way
        await s._on_tick(limit)
        assert s.phase == "part2_speak"
        await s.on_candidate_turn("and that was the end of the story.")   # the last words arrive and are kept
        t["now"] = limit + 5 + sess.P2_TRANSCRIPT_WAIT_S + 0.5
        await s._on_tick(limit)
        return s

    s = asyncio.run(go())
    assert s.phase == "part2_followup" and spoken(s)[-1].startswith("Thank you, your time is up.")
    assert any("end of the story" in t for who, t in s.history if who == "candidate")


def test_a_candidate_who_will_not_stop_is_cut_off_politely_after_the_extra_time():
    async def go():
        s, t = make_timed(grounded)
        await into_long_turn(s)
        limit = s._limit(s.phase)
        await s.on_candidate_turn(TALK)
        t["now"] = limit + sess.P2_FINISH_SENTENCE_S + 1
        s.vad_started()
        await s._on_tick(limit)
        return s

    line = spoken(asyncio.run(go()))[-1]
    assert line.startswith("I'm sorry to stop you, but your time is up. Thank you.")


def test_time_up_without_a_follow_up_question_moves_on_to_part_3_politely():
    async def go():
        async def no_llm(system, prompt, **kw):
            return None
        s, t = make_timed(no_llm)
        await into_long_turn(s)
        limit = s._limit(s.phase)
        await s.on_candidate_turn(TALK)
        t["now"] = limit
        await s._on_tick(limit)
        return s

    s = asyncio.run(go())
    assert s.phase == "part3" and spoken(s)[-1].startswith("Thank you, your time is up. Now let's move on.")
