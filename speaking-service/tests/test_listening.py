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
    s.test_mode(); s.pause_s, s.extra_s = pause, extra
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
    assert "IELTS" not in initial_prompt(None) and len(keyterms_for(None)) <= 10      # short: a long prompt makes Whisper hallucinate


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
    s.test_mode()
    s.p2_silence_s, s.p2_early_s, s.p2_remind_s, s.p2_giveup_s = 8, 6, 8, 8       # the ladder is tested with round numbers
    s.p2_early_s, s.p2_early_giveup_s = 6, 8
    s.task = FakeTask()
    return s, t


async def into_long_turn(s):
    await s.handle_control({"action": "start"})
    s._ticker.cancel()
    await s.start_long_turn()
    assert s.phase == "part2_speak"
    s._bot_stopped_at = 0.0          # the examiner has finished its "please begin speaking now"


def test_part2_never_started_prompts_then_says_there_is_time_then_moves_on_to_part3():
    async def go():
        s, t = make_timed()
        await into_long_turn(s)
        limit = s._limit(s.phase)
        n = len(spoken(s))
        t["now"] = 7
        await s._on_tick(limit)
        assert len(spoken(s)) == n                                   # not yet: 8 s of silence required
        t["now"] = 8.5
        await s._on_tick(limit)
        assert spoken(s)[-1] == "Can you tell me about the topic you have been given?"      # 1st: asked once
        t["now"] = 9
        s.bot_stopped()
        t["now"] = 16
        await s._on_tick(limit)
        assert spoken(s)[-1] == "Can you tell me about the topic you have been given?"      # not yet: 7 s since
        t["now"] = 17.5
        await s._on_tick(limit)
        assert spoken(s)[-1] == "You still have time, so please take a moment and tell me about the topic."   # 2nd: there is time
        t["now"] = 18
        s.bot_stopped()
        count = len(spoken(s))
        t["now"] = 25
        await s._on_tick(limit)
        assert len(spoken(s)) == count and s.phase == "part2_speak"  # not yet: 7 s since
        t["now"] = 26.5
        await s._on_tick(limit)                                      # still nothing: skip to the next part
        return s

    s = asyncio.run(go())
    assert s.phase == "part3"
    line = spoken(s)[-1]
    assert line.startswith("That's all right. Let's move on.") and "?" in line     # the first Part 3 question
    assert not any("you said" in l.lower() for l in spoken(s))                       # nothing is made up about silence


def test_part2_stopped_early_gets_one_gentle_line_then_time_to_finish_then_moves_on():
    async def go():
        s, t = make_timed()
        await into_long_turn(s)
        limit = s._limit(s.phase)
        t["now"] = 5
        await s.on_candidate_turn("It is a nice place near my house where I go with my friends every weekend.")
        n = len(spoken(s))
        t["now"] = 10
        await s._on_tick(limit)
        assert len(spoken(s)) == n                                   # 5 s quiet: they are allowed to think
        t["now"] = 11.5
        await s._on_tick(limit)
        assert spoken(s)[-1] == "You still have time, so please tell me a little more about it."      # the ONE nudge
        t["now"] = 12
        s.bot_stopped()
        t["now"] = 19
        await s._on_tick(limit)
        assert s.phase == "part2_speak"                              # 7 s after the nudge: still waiting for them to finish
        t["now"] = 20.5
        await s._on_tick(limit)                                      # 8.5 s: nothing more is coming
        return s

    s = asyncio.run(go())
    assert s.phase in ("part2_followup", "part3") and "Thank you." in " ".join(spoken(s)[-1:])
    assert not any("anything more" in line for line in spoken(s))    # that line is gone for good


def test_part2_stray_words_from_silence_do_not_count_as_speaking():
    async def go():
        s, t = make_timed()
        await into_long_turn(s)
        limit = s._limit(s.phase)
        t["now"] = 4
        await s.on_candidate_turn("Okay then")                       # two stray words: not a start
        t["now"] = 8.5
        await s._on_tick(limit)
        return s

    s = asyncio.run(go())
    assert spoken(s)[-1] == "Can you tell me about the topic you have been given?"          # still treated as "never started"


def test_part2_short_talk_gets_no_invented_question():
    seen = []

    async def llm(system, prompt):
        seen.append(prompt)
        return {"say": "Why did the dragon fly over the mountain?"}

    async def go():
        s, t = make_timed(llm)
        await into_long_turn(s)
        await s.on_candidate_turn("It is a nice park.")
        await s.end_long_turn()
        return s

    s = asyncio.run(go())
    assert seen == [] and s.phase == "part3"                          # the LLM is not even asked


def test_part2_followup_must_be_built_from_what_was_said():
    async def llm(system, prompt):
        return {"say": "Why did the dragon fly over the mountain?"}

    async def go():
        s, t = make_timed(llm)
        await into_long_turn(s)
        await s.on_candidate_turn("I want to talk about a book called Alchemist, it is about a shepherd who travels to Egypt "
                                  "to find a treasure and learns about life on the way.")
        await s.end_long_turn()
        return s

    s = asyncio.run(go())
    assert s.phase == "part3"                                        # the made-up question was dropped: thanked, then Part 3
    assert spoken(s)[-1].startswith("Thank you. We've been talking about")
    assert not any("dragon" in line for line in spoken(s))


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


def test_part2_candidate_speaks_after_the_prompt_so_the_clock_restarts():
    async def go():
        s, t = make_timed()
        await into_long_turn(s)
        limit = s._limit(s.phase)
        t["now"] = 8.5
        await s._on_tick(limit)                                      # prompt 1
        t["now"] = 9
        s.bot_stopped()
        t["now"] = 12
        await s.on_candidate_turn("Well, it is about a park I like very much near my home.")    # they start talking
        t["now"] = 17
        await s._on_tick(limit)
        assert "still have time" not in spoken(s)[-1]                # only 5 s quiet since their words
        t["now"] = 20.5
        await s._on_tick(limit)                                      # 8 s quiet again: the "you still have time" line
        assert spoken(s)[-1] == "You still have time, so please tell me a little more about it."
        return s

    asyncio.run(go())


