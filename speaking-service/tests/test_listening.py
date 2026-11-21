"""Behaviour reported by the tester: hallucinated words, answering before the candidate finished,
and repeating a question without being asked."""
import asyncio

import pytest

import worker.session as sess
from worker.examiner import rules
from worker.examiner.speech import is_noise, is_repeat_request, looks_unfinished
from worker.session import ExamSession
from worker.stt import initial_prompt, keyterms_for


class FakeTask:
    def __init__(self):
        self.frames = []

    async def queue_frames(self, frames):
        self.frames.extend(frames)


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)


def make(llm, pause=0.05, extra=0.3):
    async def send(e):
        pass

    s = ExamSession(send, seed=3, llm=llm, hour=9)
    s.pause_s, s.extra_s = pause, extra
    s.task = FakeTask()
    return s


def spoken(s):
    return [f.text for f in s.task.frames]


async def to_part1(s):
    await s.handle_control({"action": "start"})
    s._ticker.cancel()
    for t in ("My name is Rahim.", "Call me Rahim."):
        await s.on_candidate_turn(t)
        await s.settle()
    assert s.phase == "part1"


async def llm_ok(system, prompt):
    return {"reply": "answer", "pick": None, "say": "What do you like most about living there?", "facts": []}


# ---- hallucinations -----------------------------------------------------------------------------
def test_noise_phrases_are_recognised_but_real_short_answers_are_not():
    for junk in ("you", "You.", "Thank you.", "Thanks for watching!", "", "  ", "Subtitles by the Amara.org community", "[Music]", "hmm"):
        assert is_noise(junk), junk
    for real in ("Yes", "No", "Okay", "Maybe", "I live in Dhaka", "Sorry?"):
        assert not is_noise(real), real


def test_noise_turn_gets_no_reply_and_is_not_counted_as_an_answer():
    async def go():
        s = make(llm_ok)
        await to_part1(s)
        before, hist = len(spoken(s)), len(s.history)
        await s.on_candidate_turn("Thank you.")
        await s.settle()
        return s, before, hist

    s, before, hist = asyncio.run(go())
    assert len(spoken(s)) == before and len(s.history) == hist
    assert any(e["type"] == "ignored" for e in s.log)


def test_keyterms_hint_has_company_terms_and_the_question_words():
    terms = keyterms_for("What do you like about Chattogram food markets?")
    assert "Chattogram" in terms and "fuchka" in terms and "markets" in terms and "food" in terms
    assert initial_prompt(None).startswith("IELTS speaking test.")


# ---- waiting for the pause ----------------------------------------------------------------------
def test_unfinished_sentences_are_detected():
    assert looks_unfinished("I like the food there because")
    assert looks_unfinished("I like it, and")
    assert not looks_unfinished("I like the food there.")


def test_turns_that_arrive_in_pieces_are_merged_into_one_answer_and_answered_once():
    seen = []

    async def llm(system, prompt):
        seen.append(prompt)
        return {"reply": "answer", "pick": None, "say": "What do you like most about your home town?", "facts": []}

    async def go():
        s = make(llm, pause=0.2)
        await to_part1(s)
        n = len(spoken(s))
        await s.on_candidate_turn("I live in a small town near the river")
        await asyncio.sleep(0.05)                    # a short pause, shorter than the examiner's patience
        await s.on_candidate_turn("and I have lived there all my life.")
        assert len(spoken(s)) == n                   # still waiting: nothing said yet
        await s.settle()
        return s, n

    s, n = asyncio.run(go())
    assert len(spoken(s)) == n + 1                   # answered exactly once, after the pause
    candidate = [t for who, t in s.history if who == "candidate"][-1]
    assert "small town near the river and I have lived there" in candidate      # one merged answer
    assert any("small town near the river and I have lived" in p for p in seen)


def test_examiner_keeps_waiting_while_the_candidate_is_still_speaking():
    async def go():
        s = make(llm_ok, pause=0.05)
        await to_part1(s)
        n = len(spoken(s))
        s.vad_started()                              # they are mid-sentence
        await s.on_candidate_turn("I really enjoy it because")
        await asyncio.sleep(0.4)
        assert len(spoken(s)) == n                   # still waiting, they are talking
        s.vad_stopped()
        await s.settle()
        return s, n

    s, n = asyncio.run(go())
    assert len(spoken(s)) == n + 1


# ---- repeating a question -----------------------------------------------------------------------
def test_repeat_request_detection():
    for ask in ("Sorry?", "Can you repeat that?", "Pardon", "I didn't hear the question", "What do you mean?", "What?"):
        assert is_repeat_request(ask), ask
    for answer in ("I like reading books in the evening.", "Yes, I do, very much indeed, especially at night when it is quiet"):
        assert not is_repeat_request(answer), answer


def test_examiner_repeats_only_when_asked():
    async def go():
        s = make(llm_ok)
        await to_part1(s)
        q = s.last_question
        await s.on_candidate_turn("Sorry, could you repeat the question?")
        await s.settle()
        return s, q

    s, q = asyncio.run(go())
    assert spoken(s)[-1] == q                        # Part 1: word for word


def test_llm_claiming_repeat_without_a_request_is_ignored():
    async def liar(system, prompt):
        return {"reply": "repeat", "pick": None, "say": "Which room do you spend the most time in?", "facts": []}

    async def go():
        s = make(liar)
        await to_part1(s)
        first = s.last_question
        await s.on_candidate_turn("I live in a flat with my parents and my brother.")
        await s.settle()
        return s, first

    s, first = asyncio.run(go())
    assert spoken(s)[-1] != first                    # not the earlier question again


def test_question_is_never_asked_twice_even_if_the_llm_keeps_proposing_it():
    async def stubborn(system, prompt):
        return {"reply": "answer", "pick": None, "say": "Which room do you spend the most time in?", "facts": []}

    async def go():
        s = make(stubborn)
        await to_part1(s)
        for _ in range(8):
            if s.phase != "part1":
                break
            await s.on_candidate_turn("I spend a lot of time at home and I like it very much.")
            await s.settle()
        return s

    s = asyncio.run(go())
    qs = [rules.question_part(t) for who, t in s.history if who == "examiner" and "?" in t]
    assert len(qs) == len(set(qs)), qs               # no duplicates anywhere in the conversation


def test_fallback_returns_nothing_when_the_bank_is_used_up():
    inp = rules.NextQuestionInput(part=1, topic="Reading", frames=["Do you enjoy reading?"], asked=["Do you enjoy reading?"],
                                  question_number=2, questions_on_topic=3, history=[], fallback="Do you enjoy reading?")
    assert rules.fallback_question(inp) == ""


def test_part3_never_repeats_and_closes_when_questions_run_out():
    async def stubborn(system, prompt):
        return {"reply": "answer", "pick": None, "say": "Why is that important to people?", "facts": []}

    async def go():
        s = make(stubborn)
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        await s.start_part3()
        for _ in range(14):
            if s.phase == "done":
                break
            await s.on_candidate_turn("I think it matters a lot because people need time to rest and think.")
            await s.settle()
        return s

    s = asyncio.run(go())
    qs = [rules.question_part(t) for who, t in s.history if who == "examiner" and "?" in t]
    assert len(qs) == len(set(qs)), qs
    assert s.phase == "done"


# ---- Part 2: silence during the long turn -------------------------------------------------------
def make_timed(llm=llm_ok):
    t = {"now": 0.0}

    async def send(e):
        pass

    s = ExamSession(send, seed=3, llm=llm, hour=9, clock=lambda: t["now"])
    s.pause_s = s.extra_s = 0.0
    s.task = FakeTask()
    return s, t


async def into_long_turn(s):
    await s.handle_control({"action": "start"})
    s._ticker.cancel()
    await s.start_long_turn()
    assert s.phase == "part2_speak"
    s._bot_stopped_at = 0.0          # the examiner has finished its "please begin speaking now"


def test_part2_never_started_prompts_once_then_reminds_then_stops_nudging():
    async def go():
        s, t = make_timed()
        await into_long_turn(s)
        limit = s._limit(s.phase)
        n = len(spoken(s))
        t["now"] = 9
        await s._on_tick(limit)
        assert len(spoken(s)) == n                                   # not yet: 10 s of silence required
        t["now"] = 10.5
        await s._on_tick(limit)
        assert spoken(s)[-1] == "Can you tell me about the topic you have been given?"      # asked once
        t["now"] = 12
        s.bot_stopped()                                              # the examiner finished that line
        t["now"] = 21
        await s._on_tick(limit)
        assert spoken(s)[-1] == "Can you tell me about the topic you have been given?"      # not yet: 9 s since
        t["now"] = 22.5
        await s._on_tick(limit)
        assert spoken(s)[-1] == ("Remember, you have one to two minutes for this. "
                                 "Can you start speaking now, please?")                     # the reminder
        t["now"] = 22.6
        s.bot_stopped()
        count = len(spoken(s))
        for later in (35, 50, 80, 110):
            t["now"] = later
            await s._on_tick(limit)
        assert len(spoken(s)) == count                               # never nags a third time
        t["now"] = 121                                               # time is up: moves on, as before
        await s._on_tick(limit)
        return s

    assert asyncio.run(go()).phase == "part2_followup"


def test_part2_stopped_early_asks_for_more_then_reminds():
    async def go():
        s, t = make_timed()
        await into_long_turn(s)
        limit = s._limit(s.phase)
        t["now"] = 5
        await s.on_candidate_turn("It is a nice place near my house.")      # they did speak
        t["now"] = 12
        await s._on_tick(limit)
        assert len(s.task.frames) and spoken(s)[-1] != "Can you tell me anything more about that?"   # only 7 s quiet
        t["now"] = 14
        await s._on_tick(limit)
        assert spoken(s)[-1] == "Can you tell me anything more about that?"                   # company line
        t["now"] = 15
        s.bot_stopped()
        t["now"] = 26
        await s._on_tick(limit)
        return s

    s = asyncio.run(go())
    assert spoken(s)[-1].startswith("Remember, you have one to two minutes")


def test_part2_no_nudge_while_candidate_or_examiner_is_talking():
    async def go():
        s, t = make_timed()
        await into_long_turn(s)
        limit = s._limit(s.phase)
        n = len(spoken(s))
        t["now"] = 0
        s.vad_started()                                              # they are speaking right now
        t["now"] = 15
        await s._on_tick(limit)
        assert len(spoken(s)) == n
        s.vad_stopped()
        s.bot_started()                                              # or the examiner is mid-sentence
        await s._on_tick(limit)
        assert len(spoken(s)) == n
        return s

    asyncio.run(go())


def test_part2_candidate_speaks_after_the_prompt_so_only_one_more_nudge_is_possible():
    async def go():
        s, t = make_timed()
        await into_long_turn(s)
        limit = s._limit(s.phase)
        t["now"] = 10.5
        await s._on_tick(limit)                                      # prompt 1
        t["now"] = 11
        s.bot_stopped()
        t["now"] = 14
        await s.on_candidate_turn("Well, it is about a park I like.")    # they start talking
        t["now"] = 30
        await s._on_tick(limit)                                      # quiet again: the reminder (2nd and last)
        t["now"] = 31
        s.bot_stopped()
        count = len(spoken(s))
        t["now"] = 100
        await s._on_tick(limit)
        assert len(spoken(s)) == count
        return s

    asyncio.run(go())
