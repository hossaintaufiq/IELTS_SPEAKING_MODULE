"""'I want to finish the test' asks finish-or-continue; irrelevant questions: 1st reminder, 2nd warning, 3rd ends the test."""
import asyncio

import pytest

import worker.session as sess
from worker.examiner.intents import finish_answer, is_finish_request
from worker.session import ExamSession
from tests.test_listening import FakeTask, spoken, to_part1, llm_ok, make_timed, into_long_turn

ASK = "Do you want to finish the speaking test, or would you like to continue?"


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)


def make(events=None):
    async def send(e):
        if events is not None:
            events.append(e)

    s = ExamSession(send, seed=3, llm=llm_ok, hour=9)
    s.test_mode()
    s.task = FakeTask()
    return s


async def say(s, text):
    await s.on_candidate_turn(text)
    await s.settle()


# ---- recognising the request ---------------------------------------------------------------------
@pytest.mark.parametrize("text", ["I want to finish the test", "Okay, let's finish the test.", "Can I stop?", "I don't want to continue",
                                  "Let's end the exam", "I am done.", "Okay, let's finish the test"])
def test_requests_to_stop_are_recognised(text):
    assert is_finish_request(text)


@pytest.mark.parametrize("text", ["I am done with my studies", "My hometown is at the end of the road", "What is the end of the exam like?",
                                  "I like to stop and think", "I enjoy it"])
def test_ordinary_answers_are_not_requests_to_stop(text):
    assert not is_finish_request(text)


@pytest.mark.parametrize("text,expected", [("Finish", "finish"), ("Yes, finish it", "finish"), ("no I want to finish", "finish"),
                                           ("I want to continue", "continue"), ("No", "continue"), ("I do not want to finish", "continue"),
                                           ("yes", "unclear"), ("Yeah", "unclear"), ("hmm", "unclear")])
def test_the_answer_to_finish_or_continue(text, expected):
    assert finish_answer(text) == expected


# ---- the conversation ---------------------------------------------------------------------------
def test_asking_to_finish_gets_a_question_then_finishing_ends_with_a_goodbye():
    async def go():
        s = make()
        await to_part1(s)
        n = len(spoken(s))
        await say(s, "I want to finish the test.")
        assert spoken(s)[n:] == [ASK] and s.phase == "part1" and s.confirm_end      # asked, not ended
        await say(s, "Finish.")
        return s

    s = asyncio.run(go())
    assert spoken(s)[-1] == "All right. Thank you. That is the end of the speaking test."
    assert s.phase == "done"


def test_choosing_to_continue_resumes_with_the_same_question():
    async def go():
        s = make()
        await to_part1(s)
        q = s.last_question
        await say(s, "Can we stop please?")
        await say(s, "No, I want to continue.")
        return s, q

    s, q = asyncio.run(go())
    assert spoken(s)[-1] == f"All right, let's continue. {q}"
    assert s.phase == "part1" and not s.confirm_end


def test_an_unclear_answer_is_asked_once_more_plainly_then_treated_as_continue():
    async def go():
        s = make()
        await to_part1(s)
        await say(s, "I want to finish the test.")
        await say(s, "Yes.")
        first = spoken(s)[-1]
        await say(s, "Yeah.")
        return s, first

    s, first = asyncio.run(go())
    assert first.startswith("Sorry, please say \"finish\"")
    assert spoken(s)[-1].startswith("All right, let's continue.") and s.phase == "part1"        # never ends on a guess


def test_a_finish_request_in_the_part_2_talk_asks_and_a_continue_returns_to_the_talk():
    async def go():
        s, t = make_timed()
        await into_long_turn(s)
        await s.on_candidate_turn("I want to finish the test")
        await s.settle()
        assert spoken(s)[-1] == ASK and s.phase == "part2_speak"
        t["now"] = 30
        await s._on_tick(s._limit(s.phase))
        assert spoken(s)[-1] == ASK                          # no silence prompts while the question is open
        await s.on_candidate_turn("continue")
        await s.settle()
        return s

    s = asyncio.run(go())
    assert spoken(s)[-1] == "All right, please carry on with your talk." and s.phase == "part2_speak"


def test_a_request_to_finish_is_logged_for_the_run_log():
    events = []

    async def go():
        s = make(events)
        await to_part1(s)
        await say(s, "I want to finish the test")

    asyncio.run(go())
    assert any(e["type"] == "note" and "finish" in e["text"] for e in events)


# ---- irrelevant questions -------------------------------------------------------------------------
def test_irrelevant_questions_get_a_reminder_then_a_warning_then_the_test_ends():
    async def go():
        s = make()
        await to_part1(s)
        q = s.last_question
        await say(s, "Are you an AI?")
        one = spoken(s)[-1]
        await say(s, "What is your name?")
        two = spoken(s)[-1]
        assert s.phase == "part1"
        await say(s, "Can I change the topic?")
        return s, q, one, two

    s, q, one, two = asyncio.run(go())
    assert one == f"This is an IELTS speaking test, so let's carry on. {q}"
    assert two == ("This is an IELTS speaking test, so let's carry on. If you ask another question that is not part of the test, "
                   f"I will have to end the test. {q}")
    assert spoken(s)[-1] == "I'm sorry, but we have to end the speaking test here. Thank you."
    assert s.phase == "done"


def test_a_normal_answer_between_irrelevant_questions_does_not_reset_the_count():
    async def go():
        s = make()
        await to_part1(s)
        await say(s, "Are you an AI?")
        await say(s, "I live in a small town near the river and I have lived there all my life.")
        await say(s, "Are you a real person?")
        assert s.off_topic_count == 2 and s.phase == "part1"
        await say(s, "Who made you?")
        return s

    assert asyncio.run(go()).phase == "done"


def test_a_real_answer_is_never_counted_as_irrelevant():
    async def go():
        s = make()
        await to_part1(s)
        for _ in range(4):
            await say(s, "I live in a small town near the river and I have lived there all my life.")
        return s

    s = asyncio.run(go())
    assert s.off_topic_count == 0 and s.phase != "done"
