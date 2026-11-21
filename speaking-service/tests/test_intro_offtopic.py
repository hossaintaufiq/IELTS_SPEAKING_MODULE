"""Off-test questions get a reminder that this is an IELTS test; 'you can call me X' skips the second name question."""
import asyncio

import pytest

import worker.session as sess
from worker.examiner import rules
from worker.examiner.speech import extract_call_name, is_off_topic_question
from worker.session import ExamSession

REMINDER = "This is an IELTS speaking test, so let's carry on."


class FakeTask:
    def __init__(self):
        self.frames = []

    async def queue_frames(self, frames):
        self.frames.extend(frames)


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)


async def llm_ok(system, prompt):
    return {"reply": "answer", "pick": None, "say": "What do you like most about living there?", "facts": []}


def make(llm=llm_ok):
    async def send(e):
        pass

    s = ExamSession(send, seed=3, llm=llm, hour=9)
    s.pause_s = s.extra_s = 0.0
    s.task = FakeTask()
    return s


def spoken(s):
    return [f.text for f in s.task.frames]


async def turn(s, text):
    await s.on_candidate_turn(text)
    await s.settle()


# ---- detection ----------------------------------------------------------------------------------
@pytest.mark.parametrize("ask", [
    "Are you an AI?", "Are you a robot?", "Are you a real person?", "What's your name?", "What is your name?",
    "Who made you?", "How old are you?", "Where are you from?", "How am I doing?", "Was that good?",
    "What about you?", "Can you help me with my score?", "Do you like your job?", "Are you ChatGPT?",
])
def test_questions_aimed_at_the_examiner_are_detected(ask):
    assert is_off_topic_question(ask), ask


@pytest.mark.parametrize("answer", [
    "I live in Dhaka near the river.", "My name is Rahim Ahmed.", "You can call me Rahim.",
    "I like reading books because they teach me new things.", "The level of noise in my city is very high.",
    "I think you can learn a lot from travelling.", "Sorry, could you repeat the question?", "Yes, I do.",
    "My favourite food is biryani, and I eat it every Friday with my family at my grandmother's house in the village.",
])
def test_normal_answers_are_not_mistaken_for_off_topic_questions(answer):
    assert not is_off_topic_question(answer), answer


def test_call_me_name_extraction():
    assert extract_call_name("You can call me Rahim.") == "Rahim"
    assert extract_call_name("My full name is Rahim Ahmed, everyone calls me Raj.") == "Raj"
    assert extract_call_name("Please call me Sam") == "Sam"
    assert extract_call_name("Call me later") == ""
    assert extract_call_name("My name is Rahim Ahmed.") == ""


# ---- introduction -------------------------------------------------------------------------------
def test_call_me_in_the_first_answer_skips_what_can_i_call_you():
    async def go():
        s = make()
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        await turn(s, "My full name is Rahim Ahmed, and you can call me Rahim.")
        return s

    s = asyncio.run(go())
    lines = spoken(s)
    assert all("what can I call you" not in t.lower() for t in lines)           # never asked
    assert lines[1].startswith("Thank you, Rahim. Now, in this first part, I'd like to ask you some questions about yourself.")
    assert s.phase == "part1" and s.name == "Rahim"


def test_without_a_call_me_the_examiner_still_asks_once():
    async def go():
        s = make()
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        await turn(s, "My full name is Rahim Ahmed.")
        return s

    s = asyncio.run(go())
    assert spoken(s)[1] == "Thank you. And what can I call you?" and s.phase == "name"


# ---- off-test questions -------------------------------------------------------------------------
def test_off_test_question_in_part1_gets_the_reminder_and_the_same_question_again():
    async def go():
        s = make()
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        await turn(s, "You can call me Rahim.")
        q, count = s.last_question, s.q_in_topic
        await turn(s, "Are you an AI?")
        return s, q, count

    s, q, count = asyncio.run(go())
    assert spoken(s)[-1] == f"{REMINDER} {q}"                                    # reminder, then the same question
    assert s.q_in_topic == count and s.phase == "part1"                          # did not advance


def test_off_test_question_during_the_introduction_reasks_the_name_question():
    async def go():
        s = make()
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        await turn(s, "What's your name?")
        return s

    s = asyncio.run(go())
    assert spoken(s)[-1] == f"{REMINDER} Can you tell me your full name, please?" and s.phase == "intro"


def test_llm_can_redirect_phrasings_the_patterns_miss_but_only_for_real_questions():
    async def redirecting(system, prompt):
        return {"reply": "redirect", "pick": None, "say": "I am a friendly examiner called Alex.", "facts": []}

    async def go(answer):
        s = make(redirecting)
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        await turn(s, "You can call me Rahim.")
        q = s.last_question
        await turn(s, answer)
        return s, q

    s, q = asyncio.run(go("By the way, do they pay you for doing this job?"))
    assert spoken(s)[-1] == f"{REMINDER} {q}"                                    # wording is ours, never the LLM's
    assert "friendly examiner" not in spoken(s)[-1]

    s, q = asyncio.run(go("I live in a flat in Dhaka with my parents and my brother."))
    assert "friendly examiner" not in spoken(s)[-1] and REMINDER not in spoken(s)[-1]   # a normal answer is never redirected


def test_the_llm_prompt_contains_the_new_rule():
    assert "redirect" in rules.SYSTEM and "IELTS speaking test" in rules.SYSTEM
