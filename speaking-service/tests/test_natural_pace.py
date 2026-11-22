"""Natural pace: time decides how many questions, short answers get a follow-up, nobody is hurried to the next topic."""
import asyncio
import random

import pytest

import worker.session as sess
from worker.examiner import rules
from worker.session import ExamSession
from tests.test_listening import FakeTask, spoken, to_part1

LONG = "I live in a small town near the river and I have lived there all my life with my family and my cousins."


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)


def make(llm, t):
    async def send(e):
        pass

    s = ExamSession(send, seed=3, llm=llm, hour=9, clock=lambda: t["now"])
    s.test_mode()
    s.task = FakeTask()
    return s


QUESTIONS = [
    "What is the best thing about the area where you live?", "Do you have a favourite room at home?",
    "How has your neighbourhood changed over the years?", "Which season do you enjoy most in your town?",
    "Who do you spend most of your evenings with?", "Where would you like to live one day?",
    "What do people usually cook in your house?", "How do you usually travel around your city?",
    "Is there a park near your home?", "What do your neighbours do at the weekend?",
    "Which festival does your family celebrate together?", "When do you usually visit your grandparents?",
    "What would you change about your street?", "Do you like shopping in big markets?",
    "Who taught you to cook?", "Where do you meet your friends?", "How long does it take you to get to work?",
    "What sounds can you hear from your window?", "Do you grow plants at home?", "Which shop do you visit most often?",
]


def counting_llm():
    """A writer of new, different questions, so the bank never runs out; probes are recognised by their prompt."""
    n = {"q": 0}

    async def llm(system, prompt):
        if "very short answer" in prompt:
            return {"reply": "answer", "pick": None, "say": "Why is that?", "facts": []}
        n["q"] += 1
        return {"reply": "answer", "pick": None, "say": QUESTIONS[(n["q"] - 1) % len(QUESTIONS)], "facts": []}
    return llm


async def answer(s, text):
    await s.on_candidate_turn(text)
    await s.settle()


# ---- a follow-up before the next question -------------------------------------------------------------------
def test_a_very_short_answer_gets_a_natural_follow_up_which_does_not_count_as_a_question():
    t = {"now": 0.0}

    async def go():
        s = make(counting_llm(), t)
        await to_part1(s)
        q0 = s.q_in_topic
        await answer(s, "Yes, I do.")
        return s, q0

    s, q0 = asyncio.run(go())
    assert spoken(s)[-1] == "Why is that?"                       # no "Okay." lead-in, and the question is about THEIR answer
    assert s.q_in_topic == q0 and s._last_was_probe
    assert any(e.get("origin") == "ai:probe" for e in s.log if e["type"] == "transcript")


def test_never_two_follow_ups_in_a_row_and_a_developed_answer_moves_on():
    t = {"now": 0.0}

    async def go():
        s = make(counting_llm(), t)
        await to_part1(s)
        await answer(s, "Yes.")
        first = spoken(s)[-1]
        await answer(s, "Because it is nice.")                    # another short answer: a new question, not another "Why?"
        second = spoken(s)[-1]
        return first, second

    first, second = asyncio.run(go())
    assert first == "Why is that?" and second != "Why is that?" and second.endswith("?")


@pytest.mark.parametrize("text", ["I don't know.", "No idea.", "I am not sure", "No"])
def test_no_follow_up_after_i_dont_know(text):
    assert not rules.wants_probe(text, 1, True)


def test_wants_probe_rules():
    assert rules.wants_probe("Yes, I do.", 1, True) and rules.wants_probe("Mostly football.", 1, True)
    assert not rules.wants_probe("Yes, I do.", 1, False)                           # the last turn was already a follow-up
    assert not rules.wants_probe(LONG, 1, True)
    assert rules.wants_probe("It depends on the person.", 3, True) and not rules.wants_probe(LONG, 3, True)


def test_a_failed_llm_still_gives_a_safe_follow_up_and_does_not_repeat_the_last_one():
    async def down(system, prompt):
        return None

    t = {"now": 0.0}

    async def go():
        s = make(down, t)
        await to_part1(s)
        await answer(s, "Yes.")
        first = spoken(s)[-1]
        await answer(s, "Yes.")                                   # a new question this time (never two in a row)
        await answer(s, "Yes.")
        return first, spoken(s)[-1]

    first, last = asyncio.run(go())
    assert first in rules.PROBES and last in rules.PROBES and last != first


# ---- time decides, not a question count ---------------------------------------------------------------------------
def test_a_topic_keeps_going_while_there_is_time_and_moves_on_when_its_share_is_used():
    t = {"now": 0.0}

    async def go():
        s = make(counting_llm(), t)
        await to_part1(s)
        topic0 = s.topic_idx
        for _ in range(7):                                        # far more than the old 3-4 questions on one topic
            t["now"] += 5                                         # about 5 s per exchange: well inside the topic's share
            await answer(s, LONG)
            if s.topic_idx != topic0:
                break
        same_topic_questions = s.q_in_topic
        t["now"] = s.topic_t0 + s.topic_slice + 1                 # the share is now used up
        await answer(s, LONG)
        return s, topic0, same_topic_questions

    s, topic0, n = asyncio.run(go())
    assert n >= 6                                                 # it did not stop at 3 or 4
    assert s.topic_idx == topic0 + 1                              # and then it moved on, with a lead-in
    assert "move on to talk about" in spoken(s)[-1]


def test_part_1_ends_on_time_after_the_current_thread_not_after_a_fixed_number_of_questions():
    t = {"now": 0.0}

    async def go():
        s = make(counting_llm(), t)
        await to_part1(s)
        s.topic_slice = 1e9                                       # keep this test on one topic: only the Part 1 clock matters
        await answer(s, LONG)                                     # at least two questions on the topic
        assert s.phase == "part1"
        t["now"] = s.cfg["p1_min"] - 5                            # a little under the target: still Part 1
        await answer(s, LONG)
        still = s.phase
        t["now"] = (s.cfg["p1_min"] + s.cfg["p1_max"]) / 2 + 1    # the target: wrap up
        await answer(s, LONG)
        return still, s.phase

    still, after = asyncio.run(go())
    assert still == "part1" and after == "part2_intro"


def test_there_are_reserve_topics_for_a_student_who_finishes_early():
    plan = rules.choose_plan(rng=random.Random(5))
    assert len(plan["part1"]) == sess.CORE_TOPICS + rules.RESERVE_TOPICS


def test_a_reserve_topic_is_started_only_if_real_time_is_left():
    t = {"now": 0.0}

    async def go():
        s = make(counting_llm(), t)
        await to_part1(s)
        s.topic_idx = sess.CORE_TOPICS - 1                        # the third main topic
        s.q_in_topic = 3
        t["now"] = 100                                            # lots of time left: a reserve topic follows
        await s.next_topic_or_part2("It is fine.")
        idx_early, phase_early = s.topic_idx, s.phase
        s.topic_idx = sess.CORE_TOPICS - 1
        t["now"] = s._p1_target() - 10                            # almost the target: no new topic, on to Part 2
        await s.next_topic_or_part2("It is fine.")
        return idx_early, phase_early, s.phase

    idx, phase_early, phase_late = asyncio.run(go())
    assert idx == sess.CORE_TOPICS and phase_early == "part1" and phase_late == "part2_intro"


def test_part_3_runs_on_time_and_asks_follow_ups_instead_of_stopping_after_four_questions():
    t = {"now": 0.0}

    async def go():
        s = make(counting_llm(), t)
        await to_part1(s)
        await s.start_part3()
        n = 0
        for _ in range(8):                                        # more than four exchanges, all inside the target time
            t["now"] += 20
            await answer(s, LONG)
            n += 1
            if s.phase == "done":
                break
        return s, n

    s, n = asyncio.run(go())
    assert s.phase == "part3" and n == 8 and s.part3_q >= 6


def test_part_3_closes_once_its_target_time_is_reached_and_a_few_questions_were_asked():
    t = {"now": 0.0}

    async def go():
        s = make(counting_llm(), t)
        await to_part1(s)
        await s.start_part3()
        s.part3_q = 3
        t["now"] = (s.cfg["p3_min"] + s.cfg["p3_max"]) / 2 + 1
        await answer(s, LONG)
        return s

    s = asyncio.run(go())
    assert s.phase == "done" and spoken(s)[-1] == "Thank you. That is the end of the speaking test."


def test_the_whole_test_is_capped_at_sixteen_minutes():
    t = {"now": 0.0}

    async def go():
        s = make(counting_llm(), t)
        await to_part1(s)
        await s.start_part3()
        s.part3_q = 1
        t["now"] = s.cfg["total_max"] + 1                         # 16 minutes after the start
        await answer(s, LONG)
        return s

    s = asyncio.run(go())
    assert s.cfg["total_max"] == 960 and s.phase == "done"


def test_worst_case_length_fits_sixteen_minutes():
    c = sess.timings()
    part2 = 25 + c["prep"] + c["speak"] + 30                      # the examiner's lines, preparation, the talk, a rounding-off question
    assert 30 + c["p1_max"] + part2 + c["p3_max"] + 10 <= c["total_max"] + 15
