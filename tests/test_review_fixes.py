"""Fixes from reviewing a full test transcript: meaning-based repetition, a relevant fallback, a better Part 2 follow-up,
non-English text from the recogniser, and the shape of a whole test against the IELTS format."""
import asyncio

import pytest

import worker.session as sess
from worker.examiner import rules
from worker.examiner.rules import NextQuestionInput
from worker.examiner.speech import has_foreign_script, strip_foreign
from worker.session import ExamSession
from worker.stt import language_code
from tests.test_listening import FakeTask, into_long_turn, make_timed, spoken
ADJ = ("heavy busy quiet crowded modern old cheap safe slow fast noisy clean green local foreign public private daily weekly small large "
       "famous popular rural urban traditional digital cultural national seasonal dangerous comfortable expensive reliable").split()
NOUN = ("roads buses trains schools markets parks rivers festivals clinics offices shops bridges villages teachers drivers farmers students "
        "neighbours visitors holidays weddings sports films books songs foods gardens streets stations hospitals libraries factories").split()
QUESTIONS = [f"How does the {a} {n} shape ordinary life here?" for a, n in zip(ADJ, NOUN)]


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)


def inp(**kw):
    base = dict(part=3, topic="traffic and city transport", frames=[
        "What can the government do to reduce traffic jams?",
        "What are the main causes of traffic congestion in big cities?",
        "How has transport changed compared with twenty years ago?",
        "Do you think owning a car is an advantage?"],
        asked=["Why do you think traffic jams happen so frequently in cities?"], question_number=3, questions_on_topic=8,
        history=[("examiner", "Why do you think traffic jams happen so frequently in cities?"),
                 ("candidate", "So many people rely on small roads and there are lots of rickshaws and buses, the road space cannot handle it."),
                 ("examiner", "How does traffic compare to other countries?"),
                 ("candidate", "It is heavier and slower than in many countries because the roads are smaller.")],
        cue_card="Describe a time you were stuck in heavy traffic.", fallback="What can the government do to reduce traffic jams?")
    base.update(kw)
    return NextQuestionInput(**base)


def llm_for(covered_words=(), question="What are the main causes of traffic congestion in big cities?"):
    """One fake LLM: writes `question`; the meaning check calls a proposed question covered if it contains one of `covered_words`."""
    async def llm(system, prompt):
        if system == rules.SEMANTIC_SYSTEM:
            lines = prompt.split("Proposed next questions:")[1].splitlines()
            proposed = [l.split(". ", 1)[1] for l in lines if l[:1].isdigit() and ". " in l]
            return {"covered": [i + 1 for i, q in enumerate(proposed) if any(w in q.lower() for w in covered_words)]}
        return {"reply": "answer", "pick": None, "say": question, "facts": []}
    return llm


# ---- 1. meaning-based repetition -------------------------------------------------------------------------------------
def test_covered_questions_reads_the_numbers_and_ignores_rubbish():
    for reply, expected in (({"covered": [1, 3]}, {0, 2}), ({"covered": [9, "x", 2.5]}, set()), ({"covered": "no"}, set()), ({}, set()), (None, set())):
        async def llm(system, prompt, reply=reply):
            return reply
        assert asyncio.run(rules.covered_questions(inp(), llm, ["a?", "b?", "c?"])) == expected


def test_the_meaning_check_gets_what_was_asked_and_what_was_said_and_a_short_timeout():
    seen = {}

    async def llm(system, prompt, timeout=None):
        seen.update(system=system, prompt=prompt, timeout=timeout)
        return {"covered": []}

    asyncio.run(rules.covered_questions(inp(), llm, ["What are the main causes of traffic congestion?"]))
    assert seen["system"] == rules.SEMANTIC_SYSTEM and seen["timeout"] == rules.SEMANTIC_TIMEOUT_S
    assert "Why do you think traffic jams happen" in seen["prompt"]              # an earlier question
    assert "rickshaws and buses" in seen["prompt"]                               # an earlier answer
    assert "1. What are the main causes of traffic congestion?" in seen["prompt"]


def test_a_question_that_means_the_same_as_an_earlier_one_is_replaced_not_asked():
    """The live case: 'Why do traffic jams happen?' was asked, then 'What are the main causes of congestion?' came back."""
    nq = asyncio.run(rules.next_question(inp(), llm_for(covered_words=("causes", "congestion"))))
    assert nq.origin == "fallback" and "meaning check" in nq.why
    assert nq.say and "causes" not in nq.say and "congestion" not in nq.say      # the bank question about causes is not used either


def test_a_question_the_candidate_just_answered_is_replaced():
    """The live case: they said 'interviews or exams', the examiner asked 'which events are important?'."""
    history = [("examiner", "Is being on time more important for some events than others?"),
               ("candidate", "Yes, like interviews or exams, definitely. Being on time matters more.")]
    i = inp(part=1, topic="being on time", frames=["Are you usually on time?", "Is being on time more important for some events than others?",
                                                    "Were you often late for school as a child?"],
            asked=["Is being on time more important for some events than others?"], history=history, question_number=3,
            fallback="Were you often late for school as a child?")
    nq = asyncio.run(rules.next_question(i, llm_for(covered_words=("events",), question="Which events are particularly important to be on time for?")))
    assert nq.origin == "fallback" and "events" not in nq.say                       # the covered question is not asked...
    assert nq.say in ("Are you usually on time?", "Were you often late for school as a child?")   # ...an unasked bank question is


def test_a_good_new_question_is_kept_and_the_check_is_skipped_for_follow_ups():
    nq = asyncio.run(rules.next_question(inp(), llm_for(question="How can cities reduce the number of private cars?")))
    assert nq.source == "ai" and nq.say == "How can cities reduce the number of private cars?"
    calls = []

    async def counting(system, prompt):
        calls.append(system)
        return {"reply": "answer", "pick": None, "say": "Why is that?", "facts": []}

    short = inp(part=1, probe_ok=True, history=[("examiner", "Do you like cricket?"), ("candidate", "Yes.")])
    assert asyncio.run(rules.next_question(short, counting)).origin == "probe"
    assert rules.SEMANTIC_SYSTEM not in calls                                    # a follow-up to the last answer needs no repeat check


# ---- 2. the fallback: relevant, not repeated -------------------------------------------------------------------------
def test_fallback_prefers_the_question_closest_to_what_was_just_said():
    i = inp(frames=["How has transport changed compared with twenty years ago?", "Do you think owning a car is an advantage?",
                    "What can the government do to reduce traffic jams?"], asked=[],
            history=[("examiner", "Anything else?"), ("candidate", "I think owning a car is a real advantage for my family.")])
    assert asyncio.run(rules.pick_fallback(i, llm_for())) == "Do you think owning a car is an advantage?"


def test_fallback_skips_questions_the_meaning_check_says_are_covered_and_never_repeats():
    frames = ["What are the main causes of traffic congestion in big cities?", "How has transport changed compared with twenty years ago?"]
    i = inp(frames=frames, asked=[], fallback=frames[0])
    assert asyncio.run(rules.pick_fallback(i, llm_for(covered_words=("causes",)))) == frames[1]
    assert asyncio.run(rules.pick_fallback(i, llm_for(covered_words=("causes", "twenty")))) == ""   # all covered: nothing is asked twice


def test_fallback_works_when_the_llm_is_down():
    async def down(system, prompt):
        return None

    assert asyncio.run(rules.pick_fallback(inp(), down)) in inp().frames        # fails open: the word checks still apply


def test_part_3_never_repeats_when_everything_left_is_covered_it_uses_the_generic_follow_ups_then_closes():
    t = {"now": 0.0}

    async def go():
        async def send(e):
            pass

        async def llm(system, prompt):
            if system == rules.SEMANTIC_SYSTEM:
                return {"covered": [1, 2, 3, 4, 5]}                        # everything proposed is already covered
            return {"reply": "answer", "pick": None, "say": "Which events are particularly important?", "facts": []}
        s = ExamSession(send, seed=3, llm=llm, hour=9, clock=lambda: t["now"])
        s.test_mode()
        s.task = FakeTask()
        from tests.test_listening import to_part1
        await to_part1(s)
        await s.start_part3()
        lines = []
        for _ in range(4):
            if s.phase != "part3":
                break
            t["now"] += 14
            await s.on_candidate_turn("The roads are small and there are many rickshaws and buses so the jams are very common here.")
            await s.settle()
            lines.append(spoken(s)[-1])
        return s, lines

    s, lines = asyncio.run(go())
    asked = [l for l in lines if "?" in l]
    assert all("Which events" not in l for l in lines)                    # the covered question was never asked
    assert any("Why do you think that is?" in l for l in lines)           # the company's generic follow-up carries on
    assert len(set(asked)) == len(asked)                                  # and nothing is asked twice
    assert s.phase == "done" and spoken(s)[-1] == "Thank you. That is the end of the speaking test."


# ---- 3. Part 2 follow-up ---------------------------------------------------------------------------------------------------
def test_the_part_2_follow_up_is_asked_to_be_about_the_main_topic_not_a_small_detail():
    prompts = []

    async def llm(system, prompt):
        prompts.append(prompt)
        return {"say": "Do you often get stuck in traffic like that?"}

    async def go():
        s, t = make_timed(llm)
        await into_long_turn(s)
        await s.on_candidate_turn("One time I got stuck in very heavy traffic on my way to the university and the bus barely moved at all. "
                                  "There was a little tea stall by the road and everybody was waiting.")
        await s.end_long_turn()
        return s

    s = asyncio.run(go())
    assert "MAIN subject of the topic" in prompts[-1] and "not a small incidental detail" in prompts[-1]
    assert "Do you often get stuck in traffic like that?" in prompts[-1]                       # an IELTS-style example
    assert spoken(s)[-1] == "Thank you. Do you often get stuck in traffic like that?"


# ---- 5. other-language text from the recogniser -----------------------------------------------------------------------------
def test_turkish_hallucination_from_the_real_run_is_removed_and_the_real_answer_kept():
    said = "Many vehicles, small roads, mixed types of traffic. That's the core of the problem. İzlediğiniz için teşekkür ederim."
    assert has_foreign_script(said)
    assert strip_foreign(said) == "Many vehicles, small roads, mixed types of traffic. That's the core of the problem."
    assert strip_foreign("Altyazı M.K.") == ""
    assert strip_foreign("A café near my naïve brother's résumé shop.") == "A café near my naïve brother's résumé shop."
    assert not has_foreign_script("It is hot, and nobody was in a good mood.") and has_foreign_script("আমি ঢাকায়")


def test_a_turn_that_is_only_another_language_is_dropped_before_the_examiner_sees_it():
    events = []

    async def go():
        async def send(e):
            events.append(e)
        s = ExamSession(send, seed=3, llm=llm_for(), hour=9)
        s.test_mode()
        s.task = FakeTask()
        from tests.test_listening import to_part1
        await to_part1(s)
        n = len(spoken(s))
        await s.on_candidate_turn("Altyazı M.K.")
        await s.settle()
        await s.on_candidate_turn("That's the core of the problem. İzlediğiniz için teşekkür ederim.")
        await s.settle()
        return s, n

    s, n = asyncio.run(go())
    texts = [e["text"] for e in events if e["type"] == "transcript" and e["role"] == "user"]
    assert all(not has_foreign_script(t) for t in texts) and any("core of the problem" in t for t in texts)


def test_the_language_given_to_whisper_is_always_the_plain_code():
    from pipecat.transcriptions.language import Language
    assert language_code(Language.EN) == "en" and language_code("en") == "en" and language_code("EN-us") == "en" and language_code(None) == "en"
    assert f"<|{language_code(Language.EN)}|>" == "<|en|>"                                    # not "<|Language.EN|>"


# ---- 4. a whole test against the IELTS format -------------------------------------------------------------------------------
def test_a_whole_test_follows_the_ielts_format_and_fits_the_time_budget():
    t = {"now": 0.0}
    n = {"q": 0}

    async def llm(system, prompt):
        if system == rules.SEMANTIC_SYSTEM:
            return {"covered": []}
        if "very short answer" in prompt or "rounding-off" in prompt:
            return {"reply": "answer", "pick": None, "say": "Do you often get stuck in traffic like that?", "facts": []}
        n["q"] += 1
        return {"reply": "answer", "pick": None, "say": QUESTIONS[(n["q"] - 1) % len(QUESTIONS)], "facts": []}

    answer_text = "I think it depends on the day and on the people around me, and I usually try to stay calm and keep going."
    talk = ("One time I got stuck in very heavy traffic on my way to the university and the bus barely moved at all. I checked my phone "
            "again and again because I was worried about being late and everybody was tired and hot.")

    async def go():
        async def send(e):
            pass
        s = ExamSession(send, seed=3, llm=llm, hour=9, clock=lambda: t["now"])
        s.test_mode()
        s.task = FakeTask()
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        for text in ("My name is Rahim Ahmed.", "You can call me Rahim."):
            t["now"] += 8
            await s.on_candidate_turn(text)
            await s.settle()
        guard = 0
        while s.phase == "part1" and guard < 60:               # about 14 s per exchange: the candidate talks, the examiner asks
            t["now"] += 14
            await s.on_candidate_turn(answer_text)
            await s.settle()
            guard += 1
        t["now"] += 6
        await s.on_candidate_turn("Yes, I understand.")        # Part 2 introduction: "Do you understand?"
        await s.settle()
        prep_start = t["now"]
        t["now"] += s.cfg["prep"]
        await s._on_tick(s._limit(s.phase))                    # one minute of preparation, then "start speaking now"
        speak_start = t["now"]
        await s.on_candidate_turn(talk)
        t["now"] = speak_start + s.cfg["speak"]
        await s._on_tick(s._limit(s.phase))                    # two minutes: "Thank you."
        if s.phase == "part2_followup":
            t["now"] += 8
            await s.on_candidate_turn("Yes, quite often, especially in the rainy season when the roads are flooded.")
            await s.settle()
        guard = 0
        while s.phase == "part3" and guard < 60:
            t["now"] += 14
            await s.on_candidate_turn(answer_text)
            await s.settle()
            guard += 1
        return s, prep_start, speak_start

    s, prep_start, speak_start = asyncio.run(go())
    phases = [(e["phase"], e["t"]) for e in s.log if e["type"] == "phase"]
    names = [p for p, _ in phases]
    assert names[:6] == ["intro", "name", "part1", "part2_intro", "part2_prep", "part2_speak"]       # the IELTS order
    assert names[-2:] == ["part3", "done"] and names[6] in ("part2_followup", "part3")
    at = dict(phases)
    part1, part3, total = at["part2_intro"] - at["part1"], at["done"] - at["part3"], at["done"]
    print("IELTS-FORMAT", {"part1": part1, "part2": at["part3"] - at["part2_intro"], "part3": part3, "total": total})
    assert 240 <= part1 <= 345                                  # IELTS: Part 1 is 4-5 minutes
    assert 240 <= part3 <= 345                                  # IELTS: Part 3 is 4-5 minutes
    assert at["part2_speak"] - at["part2_prep"] == s.cfg["prep"]          # exactly one minute to prepare
    assert 11 * 60 <= total <= s.cfg["total_max"]               # 11-14 minutes in the standard, never over the 16 minute cap
    assert any(l.startswith("Thank you. We've been talking about") or "We've been talking about" in l for l in spoken(s))
    assert spoken(s)[-1] == "Thank you. That is the end of the speaking test."


def test_part1_question_that_restates_the_one_just_answered_is_replaced():
    """The live case: 'Is being on time more important for some events?' -> 'Which events are important to be on time for?'"""
    frames = ["Are you usually on time?", "Is being on time more important for some events than others?",
              "Were you often late for school as a child?", "Do you use alarms or reminders to help you be on time?"]
    history = [("examiner", "Is being on time more important for some events than others?"),
               ("candidate", "Yes, like interviews or exams, definitely. Being on time matters more.")]
    i = inp(part=1, topic="being on time", frames=frames, asked=[frames[1]], history=history, question_number=3, fallback=frames[2])
    q = "So, which events are particularly important for you to be on time for?"
    assert rules.restates_last_question(q, i)
    nq = asyncio.run(rules.next_question(i, llm_for(question=q)))
    assert nq.origin == "fallback" and "restates" in nq.why
    assert nq.say in (frames[0], frames[2], frames[3]) and "events" not in nq.say
