import asyncio
import random

import pytest

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
    assert len(bank["part1"]) == 75 and len(bank["cueCards"]) == 64
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
        if system == rules.SEMANTIC_SYSTEM:                    # the meaning check: nothing is covered
            return {"covered": []}
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


def test_part3_rejects_place_names_and_report_wording():
    from worker.examiner.rules import NextQuestionInput, check_question
    inp = NextQuestionInput(part=3, topic="traffic", frames=["What can the government do?"], asked=[], question_number=2,
                            questions_on_topic=6, history=[], fallback="")
    assert check_question("What are the main causes of traffic in cities like Dhaka?", inp)
    assert check_question("Should schools teach students about sustainable transport?", inp)
    assert check_question("Why do you think traffic jams happen so often where you live?", inp) is None


def test_llm_lead_in_acknowledgements_are_dropped_from_questions():
    assert rules.strip_lead_in("Okay, thank you. What do you like most about your home town?") == "What do you like most about your home town?"
    assert rules.strip_lead_in("Right. Do you often cook at home?") == "Do you often cook at home?"
    assert rules.strip_lead_in("So, why do you think that is?") == "So, why do you think that is?"


# ---- follow-ups never repeat a word the recogniser may have got wrong -----------------------------------------------
def test_a_possibly_misheard_word_is_not_repeated_back_but_ordinary_and_local_words_are():
    from worker.examiner.vocab import is_known, unverified_echoes
    said = ["I live in Savoy and we eat chicken mariadi with my neighbours, I like cricket and rickshaws too"]
    assert unverified_echoes("What do you like about Savoy?", said) == ["savoy"]
    assert unverified_echoes("Who cooks the chicken mariadi?", said) == ["mariadi"]
    assert unverified_echoes("Do you play cricket with your neighbours?", said) == []         # ordinary words
    assert unverified_echoes("Do you often take a rickshaw?", said) == []                      # local word, plural/singular
    assert unverified_echoes("What do you like most about the place where you live?", said) == []   # general: nothing echoed
    assert is_known("neighbors") and is_known("neighbours") and is_known("biryani") and not is_known("mariadi")


def test_check_question_turns_a_misheard_word_into_a_general_question():
    i = inp()
    i.history = [("examiner", "Where do you live?"), ("candidate", "I live in Gosundara near the river and I like it a lot.")]
    assert "misheard" in (rules.check_question("What do you like to do in Gosundara?", i) or "")
    assert rules.check_question("What do you like most about living there?", i) is None
    assert rules.check_question("Do you enjoy living near the river?", i) is None             # an ordinary word may be repeated


def test_the_part2_follow_up_does_not_repeat_a_misheard_word():
    from worker.examiner.vocab import unverified_echoes
    talk = "I went to Koxbazar with my family last year and the sea was beautiful and we stayed there for three days"
    assert unverified_echoes("Did you enjoy Koxbazar?", [talk]) == ["koxbazar"]
    assert unverified_echoes("Would you like to go there again?", [talk]) == []


# ---- follow-ups are rare, varied, and never after a negative answer ---------------------------------------------------
@pytest.mark.parametrize("answer", ["There is no furniture.", "No.", "Um, not really.", "I don't like it.", "Never.", "I have nothing.",
                                    "Of course I don't like them."])
def test_a_negative_answer_gets_no_follow_up(answer):
    assert not rules.wants_probe(answer, 1, True) and not rules.wants_probe(answer, 3, True)


def test_only_a_really_short_positive_answer_gets_a_follow_up_in_part_1():
    assert rules.wants_probe("Yes, I do.", 1, True) and rules.wants_probe("Mostly football.", 1, True)
    assert not rules.wants_probe("I live near the river with my parents.", 1, True)         # a real answer: next question
    assert not rules.wants_probe("Yes, I do.", 1, False)


@pytest.mark.parametrize("bad", ["What do you mean by 'who say square box'?", "Why did you say yes?", "What do you mean?",
                                 "You said it is a square box, why?"])
def test_a_follow_up_that_quotes_the_candidate_or_asks_what_a_word_means_is_refused(bad):
    assert rules.PROBE_BAD.search(bad)
    assert not rules.PROBE_BAD.search("Could you give me an example?") and not rules.PROBE_BAD.search("Why is that?")


def test_the_safe_follow_up_does_not_start_with_why_twice():
    i = inp()
    i.history = [("examiner", "Why is that?"), ("candidate", "Yes.")]
    assert not rules.fallback_probe(i).lower().startswith("why")
