import asyncio
import random

from worker.examiner import rules
from worker.examiner.rules import NextQuestionInput


def inp(**kw):
    base = dict(part=1, topic="Reading",
                frames=["Do you enjoy reading?", "What kind of books do you enjoy most?", "Where do you usually like to read?"],
                asked=["Do you enjoy reading?"], question_number=2, questions_on_topic=3,
                history=[("examiner", "Do you enjoy reading?"), ("candidate", "Not really, I never have time for books.")],
                fallback="What kind of books do you enjoy most?")
    base.update(kw)
    return NextQuestionInput(**base)


def test_bank_loaded_and_plan_shape():
    bank = rules.load_bank()
    assert len(bank["part1"]) == 46 and len(bank["cueCards"]) == 50
    plan = rules.choose_plan(bank, random.Random(1))
    assert 3 <= len(plan["part1"]) <= 3 + rules.RESERVE_TOPICS and plan["cueCard"]["bullets"] and len(plan["part3"]["questions"]) >= 4
    assert plan["part1"][0]["questions"][0]["ifNegative"] is None


def test_check_question_rules():
    i = inp()
    assert rules.check_question("Why don't you enjoy reading?", i) is None
    assert rules.check_question("Tell me more about it.", i) == "not a question"
    assert rules.check_question("That's interesting. Why?", i) == "comments on the answer"
    assert rules.check_question("Great! Do you read at night?", i) == "comments on the answer"
    assert rules.check_question("Who did you vote for in the election?", i) == "sensitive subject"
    assert rules.check_question("Do you enjoy reading?", i) == "repeats an earlier question"
    assert rules.check_question("Do you read? Do you write?", i) == "more than one question"
    assert rules.check_question("Why?", i) == "too short"


def test_negative_answer_forces_bank_mode_and_fallback_skips_asked():
    assert rules.choose_mode(inp()) == "bank"
    assert rules.fallback_question(inp(fallback="Do you enjoy reading?")) == "What kind of books do you enjoy most?"


def test_next_question_uses_llm_and_falls_back_on_bad_output():
    async def good(system, prompt):
        assert "Question bank for this topic" in prompt and "Not really" in prompt
        return {"reply": "answer", "pick": None, "say": "Why don't you enjoy reading?", "facts": ["doesn't like reading"]}

    nq = asyncio.run(rules.next_question(inp(), good))
    assert nq.say == "Why don't you enjoy reading?" and nq.source == "ai" and nq.facts == ["doesn't like reading"]

    async def bad(system, prompt):
        return {"say": "Great answer! Tell me more."}

    nq = asyncio.run(rules.next_question(inp(), bad))
    assert nq.source == "script" and nq.origin == "fallback"

    async def down(system, prompt):
        return None

    assert asyncio.run(rules.next_question(inp(), down)).source == "script"


def test_repeat_reply_and_pick():
    async def rep(system, prompt):
        return {"reply": "repeat", "say": "Do you enjoy reading?"}

    nq = asyncio.run(rules.next_question(
        inp(history=[("examiner", "Do you enjoy reading?"), ("candidate", "Sorry?")]), rep))
    assert nq.reply == "repeat" and nq.say == "Do you enjoy reading?"

    async def pick(system, prompt):
        return {"reply": "answer", "pick": 3, "say": "", "facts": []}

    nq = asyncio.run(rules.next_question(inp(question_number=1, history=[]), pick))
    assert nq.say.startswith("Now let's move on to reading.") and nq.say.endswith("read?")


def test_script_lines_match_company_wording():
    assert rules.SCRIPT["greeting"]("Alex Morgan", "morning") == (
        "Good morning. My name is Alex Morgan and I'm your examiner today. Can you tell me your full name, please?")
    assert rules.time_of_day(9) == "morning" and rules.time_of_day(14) == "afternoon" and rules.time_of_day(20) == "evening"
    assert rules.TIMING["part2"] == {"prepare": 60, "speak": 120}
