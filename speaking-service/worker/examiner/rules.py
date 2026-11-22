"""The company's examiner rule set, ported from TypeScript.

Sources (ieltsup/services/examCoreAPI/experimental):
  - stepfun/lib/speaking/brief.ts        exam timings and the SCRIPT of fixed examiner lines
  - deepgram/lib/speaking/examiner.ts    the question engine: prompt, modes, validation, fallbacks
  - deepgram/lib/speaking/test-plan.ts   what a test contains (simplified: random choice, no database)

Wording is kept as in the originals. Only the language changed (TypeScript -> Python).
"""
from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

BANK_PATH = Path(__file__).resolve().parent.parent.parent / "question_bank" / "ielts_bank.json"

EXAMINER = "Alex Morgan"

# brief.ts SPEAKING_EXAM (seconds)
TIMING = {
    "part1": {"min": 240, "max": 300, "max_answer": 45},
    "part2": {"prepare": 60, "speak": 120},
    "part3": {"min": 240, "max": 300, "max_answer": 90},
}

PART1_OPENERS = ["what you do", "where you live", "your hometown"]


def time_of_day(hour: int) -> str:
    return "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"


# brief.ts SCRIPT
SCRIPT = {
    "greeting": lambda examiner, tod: f"Good {tod}. My name is {examiner} and I'm your examiner today. Can you tell me your full name, please?",
    "callName": "Thank you. And what can I call you?",
    "part1Intro": "Now, in this first part, I'd like to ask you some questions about yourself.",
    "topicFirst": "Let's talk about",
    "topicNext": "Now let's move on to talk about",
    "part2Intro": ("Now I'm going to give you a topic and I'd like you to talk about it for one to two minutes. Before you talk, "
                   "you'll have one minute to think about what you're going to say. You can make some notes if you wish. Do you understand?"),
    "part2Topic": "Here is your topic. I'd like you to",
    "part2Start": ("All right? Remember you have one to two minutes for this, so don't worry if I stop you. I'll tell you when the "
                   "time is up. Can you start speaking now, please?"),
    "startNow": "Can you start speaking now, please?",
    # Part 2 silence handling (requested by the tester; built from the company's own phrases)
    "part2Prompt": "Can you tell me about the topic you have been given?",
    "part2Remind": "Remember, you have one to two minutes for this. Can you start speaking now, please?",
    # the reminder after the first prompt: say there is still time (never repeats "start speaking now" to someone who has started)
    "part2Time": "You still have time, so please take a moment and tell me about the topic.",
    "part2TimeMore": "You still have time, so please tell me a little more about it.",
    "part2Skip": "That's all right. Let's move on.",
    "part2Stop": "Thank you.",
    "part3Intro": lambda subject: f"We've been talking about {subject}, and I'd like to discuss with you one or two more general questions related to this.",
    "part3First": "Let's consider first of all",
    "closing": "Thank you. That is the end of the speaking test.",
    # reminder that this is a test (requested by the tester)
    "offTopic": "This is an IELTS speaking test, so let's carry on.",
    # the second irrelevant question gets this warning too; the third ends the test
    "offTopicWarn": "If you ask another question that is not part of the test, I will have to end the test.",
    "offTopicEnd": "I'm sorry, but we have to end the speaking test here. Thank you.",
    # the candidate asked to stop
    "finishAsk": "Do you want to finish the speaking test, or would you like to continue?",
    "finishUnclear": "Sorry, please say \"finish\" if you want to end the test, or \"continue\" if you want to carry on.",
    "finishContinue": "All right, let's continue.",
    "finishContinueTalk": "All right, please carry on with your talk.",
    "recover": "Sorry, could you say that again, please?",
    "finishDone": "All right. Thank you. That is the end of the speaking test.",
}

# examiner.ts SYSTEM (verbatim)
SYSTEM = """You are a certified IELTS Speaking examiner conducting a real test.
Speak exactly as a real examiner does: brief, neutral and polite, in British English.
Rules:
- The candidate lives in Bangladesh. They may mention local places, food, festivals and Bangla words
  (e.g. rickshaw, CNG, fuchka, pitha, cha, Eid, Pohela Boishakh, bKash). Treat them as normal answers;
  don't ask what they mean, and don't assume anything about the candidate beyond what they say.
- The candidate's words come from live speech recognition and can contain misheard words (a dish, place or name
  turned into an odd or unknown word, e.g. "chicken mariadi" for "chicken biryani"). Never repeat an unusual or unclear
  word back to the candidate; refer to it in general terms instead ("that dish", "your favourite dish").
- Ask exactly one question at a time, ending with a question mark.
- Never give feedback, praise, corrections or opinions. Do not comment on answers (no "Great", "Interesting", "I see").
- Never answer questions about the test or yourself; just continue.
- If the candidate is off-topic, rude or refuses to answer, stay calm and professional and continue with the next question.
- Never ask about politics or political parties, religious beliefs, income or salary, romantic relationships,
  health conditions, death, or anything embarrassing or upsetting. Keep questions suitable for any candidate.
- Your next question must fit the candidate's LAST answer. Before choosing, check: does it assume something the candidate denied?
  If they said they don't do, don't like or don't have something, never ask about it as if they do (including in the past).
  Instead ask why (e.g. "Why don't you enjoy reading?"), or ask about what they do instead.
- Never ask for information the candidate has already given anywhere in the test (see "Known about the candidate" and the conversation).
  If a planned question is already answered, choose another one, or build on what they said (e.g. "You said you cook pasta. Who taught you?").
- If the candidate's LAST turn only asks you to repeat or explain the question (e.g. "Sorry?", "Can you repeat?", "I didn't understand"),
  set "reply" to "repeat" and "say" to the same question again: word for word in Part 1, or in simpler words in Part 3. Otherwise "reply" is "answer".
- If the candidate asks you something that is not part of the test (for example whether you are an AI or a real person, your name, your age,
  where you are from, their score, or any personal question about you), do not answer it. Set "reply" to "redirect" and "say" to this reminder
  followed by the question you last asked, word for word: "This is an IELTS speaking test, so let's carry on."
Reply as JSON: {"reply": "answer" | "repeat" | "redirect", "pick": <number> | null, "say": "<exactly what the examiner says next>", "facts": ["<new fact the candidate stated in their LAST answer>", ...]}
"pick": in Part 1, the number of the bank question you are asking word for word; null if you wrote your own question. Always null in Part 3.
"facts": at most 3 short facts from the LAST answer only (e.g. "lives in Dhaka", "cooks pasta", "doesn't like reading"); [] if none."""

REPHRASE_SYSTEM = """You are an IELTS Speaking examiner. The candidate asked you to repeat or explain your question.
Say the same question again in simpler, clearer everyday English, keeping exactly the same meaning and topic.
One question only, under 25 words, ending with a question mark. No comments, no "Sure".
Reply as JSON: {"say": "<the simpler question>"}"""

HISTORY_LIMIT = 8
MAX_LINE_LENGTH = 300
MAX_WORDS = {1: 30, 3: 40}
EARLIER_ANSWERS = 4
MAX_FACTS = 40
AI_NEW_QUESTION_SHARE = float(os.getenv("AI_NEW_QUESTION_SHARE", "0.7"))   # share of Part 1 turns where the LLM writes its own follow-up
PERSONAL_MIN_WORDS = int(os.getenv("PERSONAL_MIN_WORDS", "6"))            # shorter answers always use the bank (company rule)

PART3_ANGLES = [
    "compare the past with the present (how things have changed and why)",
    "causes and reasons (why people behave this way, or why this happens)",
    "effects on society or the community (benefits, problems)",
    "the role of government, schools, companies or other organisations",
    "the future (predictions, how things will change)",
    "different groups of people (young vs old, city vs village, men vs women)",
    "advantages and disadvantages, or a balanced comparison of two options",
    "Bangladesh compared with other countries",
]

BANNED = re.compile(
    r"\b(politic\w*|election\w*|vote|voting|awami|bnp|jamaat|religio\w*|allah|god|prayers?|praying|salary|salaries|income|"
    r"how much (?:money|do you earn)|boyfriend|girlfriend|dating|divorce\w*|sex\w*|illness\w*|disease\w*|depress\w*|suicid\w*|"
    r"death|die|died|dying|abuse\w*|weight)\b", re.I)
PRAISE = re.compile(
    r"^(great|good|excellent|wonderful|nice|interesting|perfect|i see|that's (?:great|interesting|nice|good|wonderful)|"
    r"that sounds|well done|fantastic)\b", re.I)


@dataclass
class NextQuestionInput:
    part: int                       # 1 or 3
    topic: str
    frames: list[str]
    asked: list[str]
    question_number: int
    questions_on_topic: int
    history: list[tuple[str, str]]  # (speaker, text), speaker is "examiner" or "candidate"
    fallback: str
    cue_card: str = ""
    known: list[str] = field(default_factory=list)
    probe_ok: bool = False          # the previous examiner turn was not a follow-up probe, so a short answer may get one


@dataclass
class NextQuestion:
    say: str
    source: str                     # "ai" | "script"
    origin: str                     # bank | reworded | new | fallback | repeat
    reply: str = "answer"
    facts: list[str] = field(default_factory=list)
    why: str = ""                   # why the script fallback was used instead of the LLM's question (for the run log)


from worker.examiner.answered import already_answered  # noqa: E402
from worker.examiner.speech import is_repeat_request  # noqa: E402

JsonLLM = Callable[[str, str], Awaitable["dict | None"]]


# ---- small helpers ------------------------------------------------------------------------------
def fnv_hash(text: str) -> float:
    h = 2166136261
    for ch in text:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h / 4294967296


def lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def clean(text: str) -> str:
    t = re.sub(r"^[\"']|[\"']$", "", text.strip())
    return re.sub(r"\s+", " ", t)[:MAX_LINE_LENGTH]


def tokens(text: str) -> set[str]:
    return {w for w in re.sub(r"[^\w\s]", " ", text.lower()).split() if len(w) > 2}


def similarity(a: str, b: str) -> float:
    x, y = tokens(a), tokens(b)
    if not x or not y:
        return 0.0
    shared = len(x & y)
    return shared / (len(x) + len(y) - shared)


def question_part(say: str) -> str:
    for s in re.split(r"(?<=[.!?])\s+", say):
        if s.strip().endswith("?"):
            return s
    return say


def last_answer(inp: NextQuestionInput) -> str:
    for speaker, text in reversed(inp.history):
        if speaker == "candidate":
            return text
    return ""


RESERVE_TOPICS = 2
PROBE_MAX_WORDS = {1: 5, 3: 8}      # an answer this short or shorter gets a natural follow-up before the next question
_NO_ANSWER = re.compile(r"\b(?:don'?t|do not|didn'?t|can'?t|cannot) (?:know|remember|think)\b|\bno idea\b|\bnot sure\b|\bno\b$", re.I)
PROBES = ["Why is that?", "Could you give me an example?", "Why do you say that?", "Can you explain that a little?"]


def wants_probe(answer: str, part: int, probe_ok: bool) -> bool:
    """A very short, real answer ("Yes, I do.", "Mostly football.") is followed up like a real examiner would ("Why is that?")
    before moving to the next question. Not after "I don't know", and never two probes in a row."""
    words = len(answer.split())
    return probe_ok and 1 <= words <= PROBE_MAX_WORDS.get(part, 5) and not _NO_ANSWER.search(answer.strip(" ."))


def choose_mode(inp: NextQuestionInput, test_id: str = "") -> str:
    if wants_probe(last_answer(inp), inp.part, inp.probe_ok):
        return "probe"
    if inp.part == 3:
        return "discussion"
    answer = last_answer(inp)
    words = len(answer.split())
    if inp.question_number < 2 or words < PERSONAL_MIN_WORDS:
        return "bank"
    if re.search(r"\b(no|not|don't|never|hate|dislike)\b", answer, re.I) and words < 15:
        return "bank"
    roll = fnv_hash(f"{test_id}:{inp.topic}:{inp.question_number}") if test_id else random.random()
    return "personal" if roll < AI_NEW_QUESTION_SHARE else "bank"


def part3_angle(inp: NextQuestionInput, test_id: str = "") -> str:
    seed = test_id or inp.cue_card or inp.topic
    order = sorted(PART3_ANGLES, key=lambda a: fnv_hash(seed + a))
    return order[(inp.question_number - 1) % len(order)]


def asked_in_test(inp: NextQuestionInput) -> list[str]:
    out = list(dict.fromkeys(
        list(inp.asked) + [question_part(t) for s, t in inp.history if s == "examiner" and "?" in t]))
    return out


def build_prompt(inp: NextQuestionInput, mode: str, test_id: str = "") -> str:
    recent = inp.history[-HISTORY_LIMIT:]
    history = "\n".join(f"{'Examiner' if s == 'examiner' else 'Candidate'}: {t or '(no answer)'}" for s, t in recent)
    known = inp.known[-MAX_FACTS:]
    earlier = ""
    if len(known) < 3:
        old = [t for s, t in inp.history[:-HISTORY_LIMIT] if s == "candidate" and len(t.split()) >= 5][-EARLIER_ANSWERS:]
        earlier = "\n".join(f"- {t[:150]}" for t in old)
    memory = ""
    if known:
        memory += "\nKnown about the candidate (told earlier in the test; never ask for these again):\n" + "\n".join(f"- {f}" for f in known) + "\n"
    if earlier:
        memory += f"\nWhat the candidate said earlier in the test:\n{earlier}\n"
    asked_list = asked_in_test(inp)
    asked = "\n".join(f"- {a}" for a in asked_list) if asked_list else "- (none yet)"

    if mode == "probe":
        return (f'This is Part {inp.part} of the IELTS Speaking test. Topic: "{inp.topic}". The candidate has just given a very short answer.\n'
                f"Conversation so far:\n{history}\n\n"
                "Listen to what they said, then ask ONE short, natural follow-up that invites them to explain or give an example, "
                'like a real examiner (for example "Why is that?", "Why do you like it?", "Could you give me an example?", '
                '"How often do you do that?"). It must fit their LAST answer and use only what they actually said. '
                "Do not comment on the answer, do not praise it, do not repeat an earlier question. Under 12 words, exactly one question mark.\n"
                'Reply as JSON: {"reply": "answer", "pick": null, "say": "<the follow-up>", "facts": []}')

    if inp.part == 1:
        intro = (f'This is the first question on this topic. If you pick a bank question, the topic introduction is added for you. '
                 f'If you write your own question, introduce the topic briefly first, for example "Now let\'s move on to {lower_first(inp.topic)}."'
                 if inp.question_number == 1 else "Do not re-introduce the topic.")
        if mode == "personal":
            task = (f'Write a NEW follow-up question of your own, like a real examiner would. Pick one specific detail from the candidate\'s '
                    f'last answer (a place, activity, person or habit they mentioned) and ask about it, staying on the topic "{inp.topic}".\n'
                    "It must be a simple, everyday Part 1 question about the candidate's own life, habits, likes or experiences "
                    "(not an abstract or opinion-on-society question).\n"
                    "Do not copy a bank question. If the last answer says no or gives nothing to build on, pick a bank question instead.")
        else:
            task = ("The question bank is a guide, not a script. First read the candidate's last answer.\n"
                    "- If it CLEARLY says no (they don't do / don't like / don't have the thing), do NOT pick any bank question that assumes "
                    "they do it, now or in the past. Write your own question asking why not, or about what they prefer instead.\n"
                    "- If it doesn't answer the question (off-topic or unclear), don't assume yes or no: simply pick the next bank question.\n"
                    "- Otherwise pick the bank question that follows most naturally. Bank questions are asked word for word, so never reword them.")
        bank = "\n".join(f"{i + 1}. {f}" for i, f in enumerate(inp.frames))
        return (f'This is Part 1 (interview). Current topic: "{inp.topic}". This is question {inp.question_number} of {inp.questions_on_topic} on this topic.\n'
                f"{intro}\n\nQuestion bank for this topic (from the examiner script):\n{bank}\n\nAlready asked in this test:\n{asked}\n"
                f"{memory}\nConversation so far:\n{history}\n\n{task}\nDo not repeat anything already asked or already answered. Keep it under 25 words.")

    angle = part3_angle(inp, test_id)
    frames = "\n".join(f"- {f}" for f in inp.frames)
    return (f'This is Part 3 (two-way discussion). The Part 2 task was: "{inp.cue_card}". Discussion theme: "{inp.topic}". '
            f"This is question {inp.question_number} of {inp.questions_on_topic}.\n\n"
            f"Example questions for this theme (for style and level only; do not simply copy them):\n{frames}\n\n"
            f"Already asked in Part 3:\n{asked}\n{memory}\nConversation so far:\n{history}\n\n"
            f"Write a NEW discussion question about the theme from this angle: {angle}.\n"
            "- Make it realistic for life in Bangladesh today, and connect it to something the candidate said in Part 2 or earlier where it fits "
            "naturally (without quoting them at length). Like a real examiner, say \"in your country\" or \"where you live\" rather than naming Bangladesh.\n"
            "- It must be about people and society in general, not the candidate's personal life, and invite an opinion with reasons.\n"
            "- If the candidate's last answer was very short (one sentence), you may instead ask a short follow-up that pushes them to develop it, "
            'e.g. "Why do you think that is?" or "Can you give an example?".\n'
            "- Keep it clear and natural, under 30 words, and different from everything already asked.")


def spoken_line(js: dict, inp: NextQuestionInput) -> str:
    picked = None
    if inp.part == 1 and js.get("reply") != "repeat" and isinstance(js.get("pick"), int):
        i = js["pick"] - 1
        picked = inp.frames[i] if 0 <= i < len(inp.frames) else None
    if not picked:
        return clean(js["say"]) if isinstance(js.get("say"), str) else ""
    return f"Now let's move on to {lower_first(inp.topic)}. {picked}" if inp.question_number == 1 else picked


def check_question(say: str, inp: NextQuestionInput, repeat: bool = False) -> str | None:
    words = len(say.split())
    if not say.strip().endswith("?"):
        return "not a question"
    if say.count("?") > 1:
        return "more than one question"
    if words > MAX_WORDS[inp.part]:
        return "too long"
    if words < 3:
        return "too short"
    if PRAISE.search(say.strip()):
        return "comments on the answer"
    if BANNED.search(say) and not BANNED.search(" ".join(inp.frames)):
        return "sensitive subject"
    q = question_part(say)
    previous = list(inp.asked) + [t for s, t in inp.history if s == "examiner"]
    if not repeat and any(similarity(q, question_part(p)) >= 0.7 for p in previous):
        return "repeats an earlier question"
    return None


def fallback_question(inp: NextQuestionInput) -> str:
    previous = [question_part(p) for p in list(inp.asked) + [t for s, t in inp.history if s == "examiner"]]

    def fresh(q: str) -> bool:
        return not any(similarity(question_part(q), p) >= 0.6 for p in previous)

    said = " ".join(t for s, t in inp.history if s == "candidate")

    def usable(q: str) -> bool:                  # not asked before AND not already answered in something they said
        return fresh(q) and not already_answered(q, said)

    if usable(inp.fallback):
        return inp.fallback
    # Never hand back a question that was already asked or answered: "" tells the caller the bank is used up.
    return next((f for f in inp.frames if usable(f)), "")


MARKS_ANSWER = re.compile(r"\b(you said|you mentioned|your answer|that is (?:good|interesting)|that's (?:good|interesting))\b", re.I)


def last_examiner_question(inp: NextQuestionInput) -> str:
    for speaker, text in reversed(inp.history):
        if speaker == "examiner" and "?" in text:
            return question_part(text)
    return ""


def origin_of(say: str, frames: list[str]) -> str:
    q = question_part(say)
    best = max([0.0] + [similarity(q, f) for f in frames])
    return "bank" if best >= 0.8 else "reworded" if best >= 0.45 else "new"


def fallback_probe(inp: NextQuestionInput) -> str:
    """A safe follow-up that does not repeat the one just used."""
    recent = [question_part(t) for s, t in inp.history if s == "examiner"][-4:]
    return next((p for p in PROBES if p not in recent), PROBES[0])


async def next_question(inp: NextQuestionInput, llm: JsonLLM, test_id: str = "") -> NextQuestion:
    mode = choose_mode(inp, test_id)
    js = await llm(SYSTEM, build_prompt(inp, mode, test_id))
    if mode == "probe":
        say = clean(js["say"]) if js and isinstance(js.get("say"), str) else ""
        ok = (say.endswith("?") and say.count("?") == 1 and 2 <= len(say.split()) <= 14 and not BANNED.search(say)
              and not PRAISE.search(say) and not MARKS_ANSWER.search(say))
        if ok:
            return NextQuestion(say, "ai", "probe")
        why = "the LLM did not answer in time" if not js else "the follow-up was not a clean short question"
        return NextQuestion(fallback_probe(inp), "script", "probe", why=why)
    say = spoken_line(js, inp) if js else ""
    if js and js.get("reply") == "redirect":
        say = say or "redirect"      # handled below; the LLM's own wording is never spoken
    if not js or not say:
        return NextQuestion(fallback_question(inp), "script", "fallback", why="the LLM did not answer in time" if not js else "the LLM reply had no question")
    if js.get("reply") == "redirect":
        # Trust the LLM only if the candidate really asked a short question; the wording is always ours, not the LLM's.
        ans, q = last_answer(inp), last_examiner_question(inp)
        if q and "?" in ans and len(ans.split()) <= 14:
            return NextQuestion(f"{SCRIPT['offTopic']} {q}", "ai", "redirect", "redirect")
    facts = [f.strip()[:120] for f in js.get("facts", []) if isinstance(f, str) and len(f.strip()) > 2][:3] \
        if isinstance(js.get("facts"), list) else []
    # The examiner may only repeat a question when the candidate really asked for it. An LLM that
    # claims so without a request (it did, after a noisy turn) would repeat questions unasked.
    repeat = js.get("reply") == "repeat" and is_repeat_request(last_answer(inp))
    rejected = check_question(say, inp, repeat=repeat)
    if (not rejected and not repeat and inp.part == 1 and origin_of(say, inp.frames) == "bank"
            and already_answered(question_part(say), " ".join(t for sp, t in inp.history if sp == "candidate"))):
        rejected = "already answered by the candidate"      # a bank question they have in effect answered before
    if rejected:
        return NextQuestion(fallback_question(inp), "script", "fallback", facts=facts, why=f"LLM question rejected: {rejected}")
    return NextQuestion(say, "ai", "repeat" if repeat else origin_of(say, inp.frames),
                        "repeat" if repeat else "answer", facts)


async def rephrase_question(question: str, llm: JsonLLM) -> str:
    js = await llm(REPHRASE_SYSTEM, f"Question: {question}")
    say = clean(js["say"]) if js and isinstance(js.get("say"), str) else ""
    ok = say.endswith("?") and say.count("?") == 1 and len(say.split()) <= 30 and not BANNED.search(say)
    return say if ok else question


# ---- the test plan (test-plan.ts, simplified: random choice, no history database) ------------------
def load_bank() -> dict:
    return json.loads(BANK_PATH.read_text(encoding="utf-8"))


def choose_plan(bank: dict | None = None, rng: random.Random | None = None) -> dict:
    """One opening topic + two other Part 1 topics (different themes) and one cue card."""
    bank, rng = bank or load_bank(), rng or random.Random()
    card = rng.choice(bank["cueCards"])
    used = {card["theme"]}
    topics = [t for t in bank["part1"] if len(t["questions"]) >= 3]
    picked: list[dict] = []

    def pick(pool):
        pool = [t for t in pool if t not in picked and t["theme"] not in used] or [t for t in pool if t not in picked]
        if not pool:
            return
        t = rng.choice(pool)
        picked.append(t)
        used.add(t["theme"])

    pick([t for t in topics if t["opening"]])
    others = [t for t in topics if not t["opening"]]
    for pool in rng.sample([[t for t in others if t["local"]], [t for t in others if not t["local"]]], 2):
        pick(pool or others)
    for _ in range(RESERVE_TOPICS):                 # reserves: asked only if the three main topics finish with time to spare
        pick(others)

    part1 = []
    for t in picked:
        first, rest = t["questions"][0], list(t["questions"][1:])
        rng.shuffle(rest)
        part1.append({"topic": t["topic"], "questions": [first] + rest})
    p3 = list(card["part3"])
    rng.shuffle(p3)
    return {"part1": part1, "cueCard": card, "part3": {"topic": card["discussionTopic"], "questions": p3}}
