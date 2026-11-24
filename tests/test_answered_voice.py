"""Part 2 never prompts a student who is talking; the bank never asks what was already answered; LLM failures say why."""
import asyncio

import httpx
import pytest

import worker.examiner.llm as llm_mod
import worker.session as sess
from worker.examiner import rules
from worker.examiner.answered import already_answered
from worker.examiner.rules import NextQuestionInput
from tests.test_listening import into_long_turn, make_timed, spoken


async def no_llm(*args, **kwargs):
    return None                                  # the LLM is down: the bank and the scripts carry on


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)


# ---- Part 2: "Can you tell me about the topic you have been given?" while the student is speaking --------------
def test_a_long_answer_with_breaths_in_it_is_never_prompted_before_its_transcript_arrives():
    """Reproduces the live bug: 11 s of speech, transcribed only when they pause; the prompt came 0.3 s before the text."""
    async def go():
        s, t = make_timed()
        await into_long_turn(s)
        limit = s._limit(s.phase)
        t["now"] = 2
        s.bot_stopped()                                              # the examiner has finished "start speaking now"
        for start, stop in ((3, 5.2), (5.8, 8.1), (8.7, 11.0), (11.5, 13.9)):    # speech with short breaths between sentences
            t["now"] = start
            s.vad_started()
            t["now"] = stop
            s.vad_stopped()
            t["now"] = stop + 0.3                                    # a tick lands in the breath: the voice flag is off
            await s._on_tick(limit)
            assert "topic you have been given" not in spoken(s)[-1]
        t["now"] = 14.4
        await s._on_tick(limit)                                      # 0.5 s after their last word, transcript still decoding
        assert "topic you have been given" not in spoken(s)[-1]
        await s.on_candidate_turn("I think the Instagram app is a daily routine of mine and I scroll it every morning and evening.")
        t["now"] = 20
        await s._on_tick(limit)                                      # 6 s of real quiet since their words: still fine
        assert "topic you have been given" not in spoken(s)[-1]
        return s

    asyncio.run(go())


def test_a_student_who_really_stays_silent_is_still_prompted():
    async def go():
        s, t = make_timed()
        await into_long_turn(s)
        limit = s._limit(s.phase)
        t["now"] = 2
        s.bot_stopped()
        t["now"] = 5
        s.vad_started()
        t["now"] = 5.4
        s.vad_stopped()                                              # a cough, then nothing
        t["now"] = 9
        await s._on_tick(limit)
        assert "topic you have been given" not in spoken(s)[-1]       # 3.6 s since the cough
        t["now"] = 13.5
        await s._on_tick(limit)                                      # 8.1 s since the cough
        return s

    assert spoken(asyncio.run(go()))[-1] == "Can you tell me about the topic you have been given?"


# ---- the bank never asks what was already answered ---------------------------------------------------------
@pytest.mark.parametrize("question,said,expected", [
    ("What time do you usually get up in the morning?", "Well, I wake up at like 6 a.m. then I went for the gym", True),
    ("What time do you usually get up in the morning?", "I like the morning because it is quiet", False),
    ("Do you work or are you a student?", "I work as a software engineer in a small company", False),     # too few words to judge
    ("Do you ever watch films or videos in English?", "I always watch films and videos in English with my friends", True),
    ("Which part of the day do you enjoy most?", "I think it depends, like some days I like the gym most", False),
    ("What do you do at the weekend?", "", False),
])
def test_already_answered(question, said, expected):
    assert already_answered(question, said) is expected


def test_the_fallback_skips_a_question_about_the_wake_up_time_after_they_gave_it():
    history = [("examiner", "What does your daily routine look like?"),
               ("candidate", "I wake up at like 6 a.m., go to the gym, then to the office and back home in the evening.")]
    frames = ["What does your daily routine look like?", "What time do you usually get up in the morning?",
              "Is your routine at the weekend different from your weekday routine?"]
    inp = NextQuestionInput(part=1, topic="your daily routine", frames=frames, asked=[frames[0]], question_number=2,
                            questions_on_topic=4, history=history, fallback=frames[1])
    assert rules.fallback_question(inp) == "Is your routine at the weekend different from your weekday routine?"


# ---- the LLM says why it failed -----------------------------------------------------------------------------
def run_with(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))
    return asyncio.run(llm_mod.generate_json("s", "p", timeout=1))


def test_a_timeout_is_reported_and_not_retried(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    assert run_with(monkeypatch, handler) is None
    assert "timed out" in llm_mod.last_error and len(calls) == 1


def test_bad_json_is_retried_once_then_reported(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"say": "What do you'}}]})

    assert run_with(monkeypatch, handler) is None
    assert "not valid JSON" in llm_mod.last_error and len(calls) == 2


def test_a_hiccup_followed_by_a_good_reply_is_recovered(monkeypatch):
    replies = [httpx.Response(500, text="busy"), httpx.Response(200, json={"choices": [{"message": {"content": '{"say": "ok"}'}}]})]
    assert run_with(monkeypatch, lambda request: replies.pop(0)) == {"say": "ok"}
    assert llm_mod.last_error == ""


# ---- Part 2 for a student who was talking: stop 1 "anything more?", stop 2 "you still have time", stop 3 move on ----
def talk_then_stop(s, t, start, words_at, stop):
    """The student speaks from `start` to `stop` (voice activity), and the transcript arrives just after."""
    t["now"] = start
    s.vad_started()
    t["now"] = stop
    s.vad_stopped()
    return t


def test_default_ladder_for_a_student_who_was_talking_one_gentle_nudge_then_time_to_finish():
    async def go():
        t = {"now": 0.0}

        async def send(e):
            pass

        s = sess.ExamSession(send, seed=3, llm=no_llm, hour=9, clock=lambda: t["now"])
        from tests.test_listening import FakeTask
        s.task = FakeTask()
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        await s.start_long_turn()
        limit = s._limit(s.phase)
        t["now"] = 1
        s.bot_stopped()
        t["now"] = 2
        s.vad_started()
        t["now"] = 14
        s.vad_stopped()
        await s.on_candidate_turn("I use Instagram every day, in the morning and in the evening, and it helps me keep in touch with friends.")
        for later in (15.5, 17, 17.9):                               # 1.5, 3 and 3.9 s of silence: they may be thinking
            t["now"] = later
            await s._on_tick(limit)
            assert "still have time" not in spoken(s)[-1]
        t["now"] = 18.5
        await s._on_tick(limit)
        assert spoken(s)[-1] == "You still have time, so please tell me a little more about it."       # the ONE nudge, after 4.5 s
        t["now"] = 19.5
        s.bot_stopped()
        t["now"] = 20
        s.vad_started()                                              # they carry on talking
        t["now"] = 25
        s.vad_stopped()
        await s.on_candidate_turn("Also I watch videos about football and I follow some pages about cooking.")
        t["now"] = 29
        await s._on_tick(limit)
        t["now"] = 30.5
        await s._on_tick(limit)
        assert s.phase == "part2_speak"                              # 5.5 s of silence: they are still given time to finish
        t["now"] = 32
        await s._on_tick(limit)                                      # 7 s of silence after their last words: nothing more is coming
        return s

    s = asyncio.run(go())
    assert s.phase in ("part2_followup", "part3") and "Thank you." in spoken(s)[-1]
    assert sum(1 for line in spoken(s) if "still have time" in line) == 1       # never nagged twice
    assert not any("anything more" in line for line in spoken(s))


# ---- "That's all": a candidate who has finished can say so --------------------------------------------------------
@pytest.mark.parametrize("text", ["That's all.", "So that is all, thank you sir.", "I am finished.", "I think that's it, thank you.", "Nothing more."])
def test_phrases_that_end_the_talk(text):
    from worker.examiner.intents import is_done_talking
    assert is_done_talking(text)


@pytest.mark.parametrize("text", ["That's all I know about the app and it is good", "I'm done with my studies", "That is a good question", "I finished my homework"])
def test_phrases_that_do_not_end_the_talk(text):
    from worker.examiner.intents import is_done_talking
    assert not is_done_talking(text)


def test_saying_that_is_all_ends_the_talk_after_a_short_pause_without_asking_to_finish_the_test(monkeypatch):
    monkeypatch.setattr(sess, "DONE_TALKING_PAUSE_S", 0.05)

    async def llm(system, prompt):
        return {"say": "Do you still use it every day?"}

    async def go():
        s, t = make_timed(llm)
        await into_long_turn(s)
        await s.on_candidate_turn("I use Instagram every day, in the morning and in the evening, to talk to friends and see their news. That's all.")
        await s._end_task
        return s

    s = asyncio.run(go())
    assert s.phase == "part2_followup" and spoken(s)[-1] == "Thank you. Do you still use it every day?"
    assert "Do you want to finish the speaking test" not in " ".join(spoken(s))        # "I am finished" is about the talk, not the test


def test_if_they_carry_on_after_saying_that_is_all_the_talk_is_not_cut_short(monkeypatch):
    monkeypatch.setattr(sess, "DONE_TALKING_PAUSE_S", 0.05)

    async def go():
        s, t = make_timed()
        await into_long_turn(s)
        await s.on_candidate_turn("I use Instagram every day in the morning. That's all.")
        t["now"] = 5
        s.vad_started()                                              # ...but they start speaking again straight away
        await s._end_task
        return s

    assert asyncio.run(go()).phase == "part2_speak"


def test_a_student_who_never_started_gets_a_longer_ladder():
    async def go():
        s, t = make_timed()
        s.p2_silence_s, s.p2_remind_s, s.p2_giveup_s = 6, 5, 5
        await into_long_turn(s)
        limit = s._limit(s.phase)
        t["now"] = 5
        await s._on_tick(limit)
        assert "topic you have been given" not in spoken(s)[-1]
        t["now"] = 6.5
        await s._on_tick(limit)
        assert spoken(s)[-1] == "Can you tell me about the topic you have been given?"
        t["now"] = 7
        s.bot_stopped()
        t["now"] = 12.5
        await s._on_tick(limit)
        assert spoken(s)[-1] == "You still have time, so please take a moment and tell me about the topic."
        t["now"] = 13
        s.bot_stopped()
        t["now"] = 18.5
        await s._on_tick(limit)
        return s

    s = asyncio.run(go())
    assert s.phase == "part3" and spoken(s)[-1].startswith("That's all right. Let's move on.")


# ---- stability: an error in one turn or one tick must not leave the test stuck ----------------------------------
def test_an_error_while_answering_is_logged_and_the_examiner_recovers():
    events = []

    async def go():
        async def send(e):
            events.append(e)
        from tests.test_listening import FakeTask, to_part1
        s = sess.ExamSession(send, seed=3, llm=no_llm, hour=9)
        s.test_mode()
        s.task = FakeTask()
        await to_part1(s)

        async def boom(text):
            raise RuntimeError("boom")
        s.part1_next = boom
        n = len(spoken(s))
        await s.on_candidate_turn("I live in a small town near the river and I have lived there all my life.")
        await s.settle()
        return s, n

    s, n = asyncio.run(go())
    assert spoken(s)[-1] == "Sorry, could you say that again, please?"
    assert any(e["type"] == "note" and "boom" in e["text"] for e in events)
    assert s._responding is False


def test_an_error_in_one_tick_does_not_stop_the_timers():
    async def go():
        async def send(e):
            pass
        s = sess.ExamSession(send, seed=3, llm=no_llm, hour=9)
        calls = {"n": 0}

        async def flaky(limit):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("one bad tick")
        s._on_tick = flaky
        s.phase = "part1"
        s._ticker = asyncio.create_task(s._tick_loop())
        await asyncio.sleep(1.4)                                     # about three ticks
        s.phase = "done"
        await s._ticker
        return calls["n"]

    assert asyncio.run(go()) >= 2                                    # it kept ticking after the failure
