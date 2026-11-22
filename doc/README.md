# IELTS speaking examiner: the rules and the prompts

Everything the examiner says, asks, waits for and refuses to do, in one place. This file is **generated from the code**: every prompt, word list, pattern and number below is copied from the running modules, not retyped. Where a number can be changed without editing code, its environment variable is given (full list at the end).

**Status:** unit-tested (see `speaking-service/tests/`), not yet verified live with a candidate. The examiner follows the company's examiner rules (`worker/examiner/rules.py`, ported from the Node app) and adds the pacing and manner rules in the later sections.

Results are **estimated practice feedback**, never an official IELTS band.

## Contents

1. [The shape of a test and its timing](#1-the-shape-of-a-test-and-its-timing)
2. [What the examiner says: the fixed script](#2-what-the-examiner-says-the-fixed-script)
3. [The LLM: model, settings and the system prompt](#3-the-llm-model-settings-and-the-system-prompt)
4. [Choosing the next question (Part 1 and Part 3)](#4-choosing-the-next-question-part-1-and-part-3)
5. [The prompts sent to the LLM](#5-the-prompts-sent-to-the-llm)
6. [Checks on every LLM question](#6-checks-on-every-llm-question)
7. [Natural pace: waiting, follow-ups, lead-ins](#7-natural-pace-waiting-follow-ups-lead-ins)
8. [Part 2 rules](#8-part-2-rules)
9. [Ending, finishing early, irrelevant questions](#9-ending-finishing-early-irrelevant-questions)
10. [Listening: noise, hallucinations, repeat requests](#10-listening-noise-hallucinations-repeat-requests)
11. [Speech recognition and voice settings](#11-speech-recognition-and-voice-settings)
12. [Environment variables](#12-environment-variables)

## 1. The shape of a test and its timing

A test may take **up to 16 minutes**. The number of questions follows the clock, not the other way round.

| Stage | What happens | Time |
|---|---|---|
| Introduction | Greeting, full name, "what can I call you?" | about 30 s |
| Part 1 (interview) | 3 topics, from 46 in the question bank; 2 more are held in reserve | target 305 s, never over 340 s |
| Part 2 (long turn) | Cue card, 60 s preparation (mic muted), up to 120 s talk, one short rounding-off question | about 4 min |
| Part 3 (discussion) | Questions on the Part 2 theme until the target time | target 305 s, never over 340 s |
| Hard cap | The whole test | 960 s (16 min) |

Worst case: 30 + 340 + 235 + 340 + 10 s, which fits the cap.

### Part 1: time decides how many questions

- Each of the 3 main topics gets a **share of the time left**: `(Part 1 target - time used) / topics still to come`, never less than 60 s. A reserve topic gets 50 s.
- A topic always gets at least **2 real questions** (follow-ups such as "Why is that?" do not count), and has **no maximum**: it keeps going while there is time and the candidate is answering.
- A topic ends when its share of the time is used up, or when the answers have dried up (three questions asked and the last two answers are three words or fewer), or when its questions run out.
- Part 1 ends when the target time is reached and the current topic has had 2 questions, or at the maximum (340 s).
- After the 3 main topics a **reserve topic** is started only if there are still 40 s or more before the Part 1 target.

### Part 3: time decides too

- Part 3 closes when its target time (305 s) is reached **and** at least 3 questions have been asked, or at the maximum (340 s), or at the 16-minute cap, or when there is nothing fresh left to ask.
- If time is up and the candidate stays silent, the examiner closes after a further 25 s.

## 2. What the examiner says: the fixed script

The examiner is **Alex Morgan**, speaking British English. These lines are never written by the LLM (source: `SCRIPT` in `rules.py`, from the company's `brief.ts`, plus the lines added for pacing and endings).

| Key | Line |
|---|---|
| `greeting` | Good morning. My name is Alex Morgan and I'm your examiner today. Can you tell me your full name, please?  *("Good morning" / "Good afternoon" / "Good evening" follows the time of day)* |
| `callName` | Thank you. And what can I call you? |
| `part1Intro` | Now, in this first part, I'd like to ask you some questions about yourself. |
| `topicFirst` | Let's talk about |
| `topicNext` | Now let's move on to talk about |
| `part2Intro` | Now I'm going to give you a topic and I'd like you to talk about it for one to two minutes. Before you talk, you'll have one minute to think about what you're going to say. You can make some notes if you wish. Do you understand? |
| `part2Topic` | Here is your topic. I'd like you to |
| `part2Start` | All right? Remember you have one to two minutes for this, so don't worry if I stop you. I'll tell you when the time is up. Can you start speaking now, please? |
| `startNow` | Can you start speaking now, please? |
| `part2Prompt` | Can you tell me about the topic you have been given? |
| `part2Remind` | Remember, you have one to two minutes for this. Can you start speaking now, please? |
| `part2Time` | You still have time, so please take a moment and tell me about the topic. |
| `part2TimeMore` | You still have time, so please tell me a little more about it. |
| `part2Skip` | That's all right. Let's move on. |
| `part2Stop` | Thank you. |
| `part3Intro` | We've been talking about a time you lost something, and I'd like to discuss with you one or two more general questions related to this.  *(the Part 2 topic is filled in; here a sample)* |
| `part3First` | Let's consider first of all |
| `closing` | Thank you. That is the end of the speaking test. |
| `offTopic` | This is an IELTS speaking test, so let's carry on. |
| `offTopicWarn` | If you ask another question that is not part of the test, I will have to end the test. |
| `offTopicEnd` | I'm sorry, but we have to end the speaking test here. Thank you. |
| `finishAsk` | Do you want to finish the speaking test, or would you like to continue? |
| `finishUnclear` | Sorry, please say "finish" if you want to end the test, or "continue" if you want to carry on. |
| `finishContinue` | All right, let's continue. |
| `finishContinueTalk` | All right, please carry on with your talk. |
| `recover` | Sorry, could you say that again, please? |
| `finishDone` | All right. Thank you. That is the end of the speaking test. |

`rules.TIMING` holds the company's original timings (part1: {'min': 240, 'max': 300, 'max_answer': 45}, part2: {'prepare': 60, 'speak': 120}, part3: {'min': 240, 'max': 300, 'max_answer': 90}). Only the Part 2 preparation and talk times are still read from it; Part 1 and Part 3 now use the budget in section 1.

## 3. The LLM: model, settings and the system prompt

- **Model:** `Qwen/Qwen2.5-7B-Instruct-AWQ` (4-bit AWQ), served locally by vLLM through an OpenAI-compatible endpoint at `http://localhost:8000/v1`. No external AI API is ever called.
- **Settings:** temperature 0.6, max 220 tokens, `response_format: json_object`, timeout 10 s.
- **Failure handling:** a quick failure (HTTP error, invalid JSON) is retried once; a timeout is not retried (the conversation cannot wait twice). If the LLM still fails, the examiner falls back to the question bank and the reason is shown in the run log (`why`).
- **Start-up:** the LLM is called once when the server starts, so the first real turn is not the first request.
- **Fixed lines are never LLM text.** The wording of the off-test reminder, the closing and every `SCRIPT` line is always ours.

### System prompt (used for every question and for the Part 2 rounding-off question)

```
You are a certified IELTS Speaking examiner conducting a real test.
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
"facts": at most 3 short facts from the LAST answer only (e.g. "lives in Dhaka", "cooks pasta", "doesn't like reading"); [] if none.
```

### System prompt for rephrasing a Part 3 question the candidate did not understand

```
You are an IELTS Speaking examiner. The candidate asked you to repeat or explain your question.
Say the same question again in simpler, clearer everyday English, keeping exactly the same meaning and topic.
One question only, under 25 words, ending with a question mark. No comments, no "Sure".
Reply as JSON: {"say": "<the simpler question>"}
```

The user message for that call is `Question: <the question>`. The reply is accepted only if it is one question of at most 30 words with no sensitive subject; otherwise the original question is repeated.

## 4. Choosing the next question (Part 1 and Part 3)

After each answer the examiner asks the LLM for the next question. The LLM works in one of four **modes**, chosen by `choose_mode`:

| Mode | When | What the LLM does |
|---|---|---|
| `probe` | The candidate's last answer is very short (Part 1: 5 words or fewer; Part 3: 8 or fewer), is not "I don't know" / "no idea" / "not sure", and the previous examiner turn was not already a follow-up | Writes a short, natural follow-up to **that** answer ("Why is that?") |
| `bank` | First question after the topic opener, or the last answer is shorter than 6 words, or it says no / don't / never (under 15 words), or the draw does not choose a personal question (30% of the turns that could) | Picks the bank question that follows most naturally, word for word |
| `personal` | The last answer has at least 6 words, and a share of 70% of such turns (fixed per test and topic) | Writes its own follow-up about one specific detail the candidate mentioned |
| `discussion` | Part 3 | Writes a new discussion question from the next "angle" below |

- **Never two follow-ups in a row**, and a follow-up never counts as a topic question.
- **Memory:** the prompt carries the last 8 turns, up to 40 short facts extracted from earlier answers ("lives in Dhaka", "cooks pasta"), and the questions already asked. The LLM must never ask for something already known.
- **Bank questions the candidate already answered are skipped.** Both when the LLM picks one and when the fallback would (see section 6).
- **A question is never asked twice** (similarity of 0.6 or more with an earlier question counts as asked). When the bank is used up the examiner moves to the next topic.
- **Off-test question from the candidate:** the LLM may flag it (`reply: redirect`), but it is trusted only if the candidate really asked a short question (14 words or fewer). The LLM's own wording is never spoken (section 9).
- **Repeat request:** the examiner repeats a question only if the candidate really asked for it (section 10); otherwise `reply: repeat` from the LLM is ignored.

### Part 3 angles

Each Part 3 question is written from the next angle in a per-test shuffled order, so the discussion moves through different kinds of thinking:

1. compare the past with the present (how things have changed and why)
1. causes and reasons (why people behave this way, or why this happens)
1. effects on society or the community (benefits, problems)
1. the role of government, schools, companies or other organisations
1. the future (predictions, how things will change)
1. different groups of people (young vs old, city vs village, men vs women)
1. advantages and disadvantages, or a balanced comparison of two options
1. Bangladesh compared with other countries

### Generic Part 3 follow-ups (the company's, used as a safe fallback)

- "Why do you think that is?"
- "Can you give an example?"

### Safe follow-ups when the LLM cannot write one

- "Why is that?"
- "Could you give me an example?"
- "Why do you say that?"
- "Can you explain that a little?"

The one used is the first that was not asked in the last four examiner turns.

## 5. The prompts sent to the LLM

Below are the **real prompts**, produced by the real builder (`rules.build_prompt`) from a sample situation, so the text is exact. Text in the sample conversation and bank is only an example.

### Part 1, `bank` mode

```
This is Part 1 (interview). Current topic: "your hometown". This is question 3 of 5 on this topic.
Do not re-introduce the topic.

Question bank for this topic (from the examiner script):
1. Where is your hometown?
2. What is your hometown famous for?
3. Is it a good place for young people to live?
4. Would you like to live there in the future?

Already asked in this test:
- Where is your hometown?
- What is your hometown famous for?

Known about the candidate (told earlier in the test; never ask for these again):
- lives in Rampur

Conversation so far:
Examiner: Let's talk about your hometown. Where is your hometown?
Candidate: My hometown is in Rampur, it is a small town near the river and I lived there all my life.
Examiner: What is your hometown famous for?
Candidate: It is famous for its mangoes and the big market on Fridays where people come from many villages.

The question bank is a guide, not a script. First read the candidate's last answer.
- If it CLEARLY says no (they don't do / don't like / don't have the thing), do NOT pick any bank question that assumes they do it, now or in the past. Write your own question asking why not, or about what they prefer instead.
- If it doesn't answer the question (off-topic or unclear), don't assume yes or no: simply pick the next bank question.
- Otherwise pick the bank question that follows most naturally. Bank questions are asked word for word, so never reword them.
Do not repeat anything already asked or already answered. Keep it under 25 words.
```

### Part 1, `personal` mode

```
This is Part 1 (interview). Current topic: "your hometown". This is question 3 of 5 on this topic.
Do not re-introduce the topic.

Question bank for this topic (from the examiner script):
1. Where is your hometown?
2. What is your hometown famous for?
3. Is it a good place for young people to live?
4. Would you like to live there in the future?

Already asked in this test:
- Where is your hometown?
- What is your hometown famous for?

Known about the candidate (told earlier in the test; never ask for these again):
- lives in Rampur

Conversation so far:
Examiner: Let's talk about your hometown. Where is your hometown?
Candidate: My hometown is in Rampur, it is a small town near the river and I lived there all my life.
Examiner: What is your hometown famous for?
Candidate: It is famous for its mangoes and the big market on Fridays where people come from many villages.

Write a NEW follow-up question of your own, like a real examiner would. Pick one specific detail from the candidate's last answer (a place, activity, person or habit they mentioned) and ask about it, staying on the topic "your hometown".
It must be a simple, everyday Part 1 question about the candidate's own life, habits, likes or experiences (not an abstract or opinion-on-society question).
Do not copy a bank question. If the last answer says no or gives nothing to build on, pick a bank question instead.
Do not repeat anything already asked or already answered. Keep it under 25 words.
```

### Part 1 and Part 3, `probe` mode (the candidate gave a very short answer)

```
This is Part 1 of the IELTS Speaking test. Topic: "your hometown". The candidate has just given a very short answer.
Conversation so far:
Examiner: Let's talk about your hometown. Where is your hometown?
Candidate: My hometown is in Rampur, it is a small town near the river and I lived there all my life.
Examiner: What is your hometown famous for?
Candidate: Mostly mangoes.

Listen to what they said, then ask ONE short, natural follow-up that invites them to explain or give an example, like a real examiner (for example "Why is that?", "Why do you like it?", "Could you give me an example?", "How often do you do that?"). It must fit their LAST answer and use only what they actually said. Do not comment on the answer, do not praise it, do not repeat an earlier question. Under 12 words, exactly one question mark.
Reply as JSON: {"reply": "answer", "pick": null, "say": "<the follow-up>", "facts": []}
```

### Part 3, `discussion` mode

```
This is Part 3 (two-way discussion). The Part 2 task was: "Describe a book you read that you found interesting.". Discussion theme: "reading habits". This is question 2 of 8.

Example questions for this theme (for style and level only; do not simply copy them):
- Do you think people read less than in the past?
- How can schools encourage reading?

Already asked in Part 3:
- Do you think people read less than in the past?

Known about the candidate (told earlier in the test; never ask for these again):
- likes reading

Conversation so far:
Examiner: Do you think people read less than in the past?
Candidate: I think yes, because everyone has a phone now and they watch videos instead of reading books at home.

Write a NEW discussion question about the theme from this angle: compare the past with the present (how things have changed and why).
- Make it realistic for life in Bangladesh today, and connect it to something the candidate said in Part 2 or earlier where it fits naturally (without quoting them at length). Like a real examiner, say "in your country" or "where you live" rather than naming Bangladesh.
- It must be about people and society in general, not the candidate's personal life, and invite an opinion with reasons.
- If the candidate's last answer was very short (one sentence), you may instead ask a short follow-up that pushes them to develop it, e.g. "Why do you think that is?" or "Can you give an example?".
- Keep it clear and natural, under 30 words, and different from everything already asked.
```

### Part 2 rounding-off question (after the talk, only if the candidate said at least 12 words; sample card and talk)

```
Part 2 has just ended. The candidate talked about: "Describe a time you lost something important.".
What they said (speech recognition, may contain errors): I want to talk about the day I lost my phone on a crowded bus. It had all my photos and I was very worried, so I went back to the bus stop.
Ask ONE short rounding-off question, like a real IELTS examiner (under 12 words, ending with a question mark), about the thing they described. It must be easy to answer in a sentence, for example "Do you still have it?", "Do many people go there?", "Do you see him often?". Use only what they said; never add or assume any detail they did not mention, and never refer to the conversation, the talk, or what they "said" or "mentioned". Do not use a name or word they did not say. Reply as JSON: {"say": "<the question>"}
```

The reply must be one clean question, under 15 words, with no sensitive subject, without "conversation / discussion / you said / you mentioned / talked about / topic", and built from words the candidate or the cue card actually used. Otherwise no question is asked: the examiner says "Thank you." and goes straight to Part 3.

## 6. Checks on every LLM question

A question from the LLM is spoken only if all of these pass. If not, the examiner uses the bank (`why` in the run log says which check failed).

- It ends with a question mark and contains exactly one.
- Length: at least 3 words; at most 30 words in Part 1 and 40 in Part 3.
- It does not comment on the answer (no praise or "I see"). Pattern: `^(great|good|excellent|wonderful|nice|interesting|perfect|i see|that's (?:great|interesting|nice|good|wonderful)|that sounds|well done|fantastic)\b`
- It does not touch a sensitive subject unless the bank question itself does. Pattern: `\b(politic\w*|election\w*|vote|voting|awami|bnp|jamaat|religio\w*|allah|god|prayers?|praying|salary|salaries|income|how much (?:money|do you earn)|boyfriend|girlfriend|dating|divorce\w*|sex\w*|illness\w*|disease\w*|depress\w*|suicid\w*|death|die|died|dying|abuse\w*|weight)\b`
- It is not a repeat of an earlier question (similarity of 0.7 or more), except when the candidate really asked for a repeat. Follow-ups (`probe`) are exempt: "Why is that?" may be asked more than once in a test.
- In Part 1, a bank question is rejected if the candidate has in effect answered it already (section below).
- A follow-up must not mark the answer. Pattern: `\b(you said|you mentioned|your answer|that is (?:good|interesting)|that's (?:good|interesting))\b`

### "Already answered" check (`worker/examiner/answered.py`)

- A "what time..." question is treated as answered if the candidate has said a clock time ("6 a.m.", "at 7").
- Otherwise a question is treated as answered if it has at least 3 content words and at least 60% of them already appear in what the candidate said (simple stemming, common words ignored).
- The check is cautious on purpose: wrongly skipping a question costs less than asking it twice.

### Fallback when the LLM is not used

The next unasked, unanswered bank question is used. If none is left, the examiner moves on (next topic, or the next part).

## 7. Natural pace: waiting, follow-ups, lead-ins

### Waiting for the candidate to finish

The examiner never answers the instant a sentence ends. The voice detector closes a turn after 0.6 s of silence and the recogniser needs a moment; on top of that the examiner waits:

| After | Base wait |
|---|---|
| a Part 1 answer | 1.5 s |
| a Part 3 answer | 2 s |
| a name or "do you understand?" | 1.2 s |

The wait is then **adapted to what was said** (`worker/examiner/pacing.py`):

- short answer (5 words or fewer, Part 1 / Part 3 / Part 2 follow-up): **+1 s** (it usually goes on to an explanation)
- ends mid-sentence ("...and", "...because", "I mean", "for example", "you know"): **+1.2 s**
- asks for time ("let me think", "how can I say", "just a moment"): **+2.5 s**. Pattern: `\b(let me think|let me see|wait a (?:moment|minute|second)|just a (?:moment|minute|second)|one (?:moment|minute|second)|give me (?:a )?(?:moment|minute|second|time)|how (?:can|do|to) i say|how to say|what (?:is|do you call) it|i am thinking|i'm thinking|let me recall|let me remember)\b`
- a long, complete sentence (25 words or more, ends with . ? !): the wait is **x0.75**
- never more than **6 s** in total
- **While the candidate is speaking again, the examiner waits** until they stop, however long the wait was.
- **Fillers restart the wait.** A thinking noise ("ummm", "aaa", "hmm") means they are still thinking aloud.
- **A turn that arrives in pieces is merged** into one answer and answered once.
- **If more speech arrives while the next question is still being written, the question is taken back** and the examiner waits for the whole answer. It never asks a question about half an answer.

### Follow-up before moving on

- A very short answer gets a natural follow-up first (mode `probe`, section 4): no lead-in, and it does not use up one of the topic's questions.
- No follow-up after "I don't know", and never two in a row.

### Small acknowledgements between questions

A real examiner says little. About **50%** of the turns that lead to a new question start with a neutral lead-in; a change of topic always does. Never praise, never an opinion, never "I see" or "interesting" (company rule). The same one is never used twice in a row. Follow-ups never get one.

| Used after | Lead-ins |
|---|---|
| a short answer (5 words or fewer) | Okay., Right., Alright. |
| a medium answer | Okay., Right., All right., Okay, thank you. |
| a long answer (25 words or more) | Okay, thank you., Thank you., All right, thank you., Right, thank you. |
| a new topic | Thank you., Okay, thank you., All right, thank you. |

## 8. Part 2 rules

- **Preparation:** the cue card is shown and the microphone is muted for the preparation time. Then the examiner says the start line (`part2Start`).
- **The examiner stays silent while the candidate talks.** Fragments from silence (one or two stray words) do not count as speaking; the candidate has started once they have said at least 4 words.
- **Silence is timed from the last moment the candidate's voice was heard**, not from the last transcript, with a 2 s grace (a long answer is only transcribed when the candidate pauses; counting from the last words made the examiner interrupt someone who was talking).

**Candidate has started talking and then stops:**

- after **4 s** of silence: "You still have time, so please tell me a little more about it." (once)
- if they say nothing more, after **6 s** more: "Thank you." and the examiner moves on (with a rounding-off question if they said enough)
- if they carry on talking, the clock starts again; the examiner never nags twice and never asks "anything more?"

**Candidate never starts:**

- after **6 s**: "Can you tell me about the topic you have been given?"
- **5 s** later: "You still have time, so please take a moment and tell me about the topic."
- **5 s** later: "That's all right. Let's move on." and straight to Part 3 (no question is made up about nothing)

**Other Part 2 rules:**

- **"That's all":** if the talk ends with a phrase such as "that's all", "that's it", "I'm finished", "nothing more" (optionally "thank you sir"), the examiner waits 1.5 s in case they go on, then thanks them and moves on. Pattern: `\b(?:that'?s|that is) (?:all|it|everything|about it)\b|\bi(?:'ve| have| am|'m) (?:finished|done)\b|\b(?:nothing|no) (?:more|else)\b|\bthat'?s the end\b`
- **Two minutes:** at the end of the talk time a candidate who is mid-sentence may finish it (up to 4 s), then "Thank you."
- **Rounding-off question:** only if the candidate said at least 12 words, written by the LLM with the prompt in section 5; otherwise "Thank you." and Part 3.

## 9. Ending, finishing early, irrelevant questions

### Normal ending

"Thank you. That is the end of the speaking test." The page is told the test is over only **after** that line has finished playing. The same closing is used when the End button is pressed, when Part 3 time is up and the candidate is silent, and at the 16-minute cap.

### The candidate asks to finish

- Short phrases such as "I want to finish the test", "let's end it", "can I stop?", "I don't want to continue", "I'm done." are **not answers**. Only utterances of 16 words or fewer count, and questions ("what is the end of the exam like?") do not.
- The examiner asks: "Do you want to finish the speaking test, or would you like to continue?"
- **Finish** -> "All right. Thank you. That is the end of the speaking test." and the test ends.
- **Continue** -> "All right, let's continue." and the last question is asked again (in Part 2: "All right, please carry on with your talk.").
- **Unclear** (a bare "yes") -> asked once more: "Sorry, please say "finish" if you want to end the test, or "continue" if you want to carry on." If still unclear, the test **continues** (it never ends on a guess).
- When both words are said, the later one wins ("no, I want to finish" = finish). "I don't want to finish" = continue.
- In the Part 2 talk, "I'm finished / that's all" ends the **talk** (section 8), not the test.

Finish-request patterns:

- `\b(?:finish|end|stop|quit|terminate|complete|cancel)\b.{0,25}\b(?:test|exam|examination|interview|session)\b`
- `\b(?:i|we)\s*(?:want|wanna|would like|'d like|need|have|am going|'m going)\s*(?:to\s*)?(?:finish|end|stop|quit|leave)\b`
- `\blet'?s\s*(?:finish|end|stop|quit|call it)\b`
- `\b(?:finish|end|stop)\s*(?:it|this)?\s*now\b|\bfinish\s*(?:it|this)\b`
- `\b(?:i|we)\s*(?:don'?t|do not|no longer)\s*want\s*to\s*(?:continue|go on|carry on|do this|take (?:this|the))\b`
- `\b(?:can|could|may)\s*(?:i|we)\s*(?:please\s*)?(?:stop|finish|end|leave|quit)\b`
- `^\W*(?:i'?m|i am|we are|we're)\s*(?:done|finished)(?:\s*(?:now|with (?:this|the test|it)))?\W*$`
- `\bthat'?s enough\b`

### Irrelevant questions

A question to the examiner instead of an answer ("Are you an AI?", "What's your name?", "How am I doing?", "Can I change the topic?", "Can I go to the next question?") is **never answered**. The count is for the whole test:

| Time | The examiner says |
|---|---|
| 1st | "This is an IELTS speaking test, so let's carry on." + the last question again |
| 2nd | "This is an IELTS speaking test, so let's carry on. If you ask another question that is not part of the test, I will have to end the test." + the last question again |
| 3rd (limit 3) | "I'm sorry, but we have to end the speaking test here. Thank you." and the test ends |

Only questions of 14 words or fewer count. Patterns (case-insensitive):

- `\b(are|r) you (an? )?(ai|a\.i\.|artificial|robot|bot|machine|computer|program|human|real|person|chat ?gpt|gpt|alive)\b`
- `\bare you (a )?(man|woman|boy|girl|male|female|teacher|examiner|native)\b`
- `\b(what|what's|whats) (is )?your (name|age|job|surname|nationality|religion|favou?rite)\b`
- `\bwho (are you|made you|created you|built you|programmed you|trained you)\b`
- `\bwhat are you\b`
- `\bhow old are you\b`
- `\bwhere (are you from|do you live|were you born)\b`
- `\b(do|did|have|can|will|would|are) you (like|love|have|speak|know|work|live|get|feel|think|ever|enjoy|want|any|also)\b`
- `\bwhat about you\b|\band you\s*\?|\bhow about you\b|\byour opinion\b|\bwhat do you think\b`
- `\bmy (score|band|marks?|result|results|grade)\b|\bhow am i doing\b|\bwas (that|it) (good|ok|okay|correct|right|fine)\b|\bis (that|it) (good|ok|okay|correct|right|fine)\b|\bdid i (do|answer|pass|speak)\b|\bhow many (marks|bands|points)\b`
- `\b(can|could|will|would) you (help|tell|give|show|explain|teach|answer|recommend|suggest)\b`
- `\btell me (about|something about) yourself\b|\bwhich company\b|\bwho (owns|runs) (this|you)\b`
- `\b(change|skip|switch)\b.{0,12}\b(topic|question|subject)\b|\b(next|another|different) (topic|question)\b.{0,12}\b(please|now)\b|\bcan (i|we) (go|move) (to|on to) (the )?next\b|\b(give|ask) me (the |a |another )?(next|different|easier) (one|question)\b`

### The candidate's name

"You can call me X", "everyone calls me X", "my nickname is X" in the first answer skips "what can I call you?". Pattern: `\b(?:call(?:s)? me|(?:i am|i'm|i was|i'm being) called|i go by|(?:everyone|everybody|people|friends|they) calls? me|known as|my nickname is|my short name is|my pet name is|my friends call me)\s+([A-Za-z][A-Za-z'-]+)`

## 10. Listening: noise, hallucinations, repeat requests

### What is ignored as noise (shown as "ignored" in the run log)

- Empty text and the stock phrases Whisper invents on silence or background noise: `ah`, `bye`, `bye bye`, `goodbye`, `hmm`, `huh`, `i`, `mhm`, `mm`, `oh`, `please subscribe`, `so`, `subtitles by the amara.org community`, `thank you`, `thank you for watching`, `thank you so much`, `thanks`, `thanks for watching`, `the`, `uh`, `um`, `you`
- Patterns such as subtitles credits, URLs, brackets and music marks: `^(subtitles? by|translated by|transcribed by|www\.|https?://|\[|\(|♪|music)`
- Thinking noises: `^(?:u+h*m*|e+r+m*|e+h+|a+h+|a{2,}|h+m+|m+h*m*|o+h+)(?:\s+(?:u+h*m*|e+r+m*|e+h+|a+h+|a{2,}|h+m+|m+h*m*|o+h+))*$` ("ummm", "aaa", "hmm", "erm")
- "Thank you sir" / "thank you madam" on its own (politeness, not an answer). "Yes sir." is a real answer and is kept.
- Repetition loops (four or more words with at most a third of them different, "you you you you").
- The recogniser's own prompt words coming back as text (section 11).
- An ignored fragment while an answer is waiting **restarts the wait** (the candidate is still thinking).

### Unfinished sentences (the examiner waits longer)

- Ends with a connecting word: `a`, `aa`, `aaa`, `about`, `actually`, `also`, `an`, `and`, `are`, `as`, `at`, `basically`, `because`, `but`, `by`, `could`, `er`, `erm`, `for`, `from`, `hmm`, `how`, `if`, `in`, `is`, `like`, `maybe`, `means`, `my`, `of`, `on`, `or`, `perhaps`, `really`, `should`, `so`, `some`, `than`, `that`, `the`, `then`, `to`, `uh`, `uhh`, `um`, `umm`, `ummm`, `very`, `was`, `well`, `what`, `when`, `where`, `which`, `who`, `why`, `will`, `with`, `would`
- Ends with a searching phrase: `for example`, `for instance`, `such as`, `i think`, `i mean`, `you know`, `let me think`, `that is`, `that means`, `because of`, `so that`, `i don't know how to say`, `how to say`, `what to say`, `kind of`, `sort of`
- Ends with a comma, a dash or "...".

### Requests to repeat or explain (the only way a question is repeated)

Twelve words or fewer, matching: `\b(sorry|pardon|repeat|say (?:that|it) again|once more|come again|didn'?t (?:hear|catch|get|understand)|did not (?:hear|catch|understand)|can'?t hear|what do you mean|what was (?:the|that)|could you (?:say|repeat)|can you (?:say|repeat)|i don'?t understand|not clear|what did you say|excuse me|pardon me|once again|again please|one more time|speak (?:more )?slowly|slowly please|slow down|too fast|i (?:can'?t|cannot|could not|couldn'?t) (?:hear|understand|catch)|what is the meaning|what does (?:it|that|this) mean|meaning of (?:this|that|the question))\b` (also a bare "what?" / "huh?"). In Part 1 the question is repeated word for word; in Part 3 it is rephrased in simpler words (section 3).

## 11. Speech recognition and voice settings

### Speech recognition (faster-whisper)

- Model `large-v3-turbo`, device `cuda`, compute type `float16`; live captions use `small.en`.
- **Voice activity detection** (Silero): confidence 0.5, minimum volume 0.0, speech starts after 0.2 s, a turn ends after 0.6 s of silence.
- **The recogniser prompt is deliberately short.** Measured on a real Bangladeshi test recording, a long list of local names made Whisper repeat the prompt ("IELTS speaking test.") and invent words. It now carries only these terms plus up to 4 content words of the question just asked: Bangladesh, Dhaka, Chattogram, Sylhet, Eid, Pohela Boishakh, rickshaw, biryani, fuchka, Bangla. Example: `Bangladesh, Dhaka, Chattogram, Sylhet, Eid, Pohela Boishakh, rickshaw, biryani, fuchka, Bangla, food, markets.`
- Segments made only of the prompt's own words (three words or more) are dropped.
- **Quiet microphones are levelled up** before recognition: speech frames are brought to an rms of 0.08 with a gain of at most x6; loud audio and silence are never changed.

Decoding settings (`_decode` in `worker/stt.py`):

```
self._model.transcribe(
            level_up(audio_float),
            language=self._settings.language,
            initial_prompt=initial_prompt(self.question_hint),
            condition_on_previous_text=False,
            beam_size=5,
            temperature=[0.0, 0.2],
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            vad_filter=os.getenv("STT_VAD_FILTER", "1") == "1",   # set 0 if quiet speech is being clipped
            vad_parameters={"threshold": 0.35, "min_silence_duration_ms": 600, "speech_pad_ms": 300},
        )
```

Segments below an average log-probability of -1.0 or above the no-speech threshold are dropped.

### The examiner's voice (Kokoro)

- Voice `bf_emma` (British female), speed **0.95** with a random variation of +/-0.02 per line (`EXAMINER_SPEED`, `EXAMINER_SPEED_JITTER`): slightly slower and clearer for learners, and no two sentences sound stamped from the same mould.
- **Half-duplex:** the microphone is ignored while the examiner speaks and for a short tail after, so the examiner never answers its own echo. Use headphones.

## 12. Environment variables

Every knob that can be changed without editing code (name, default, file). Found by scanning the source.

| Variable | Default | File |
|---|---|---|
| `ADAPTIVE_WAIT` | `"1"` | `worker/session.py` |
| `AI_NEW_QUESTION_SHARE` | `"0.7"` | `worker/examiner/rules.py` |
| `ANSWER_PAUSE_S` | `"1.5"` | `worker/session.py` |
| `CAPTION_MODEL` | `"small.en"` | `worker/pipeline.py` |
| `EXAMINER_ACK_PROB` | `"0.5"` | `worker/session.py` |
| `EXAMINER_SPEED` | `"0.95"` | `worker/tts.py` |
| `EXAMINER_SPEED_JITTER` | `"0.02"` | `worker/tts.py` |
| `HOST` | `"127.0.0.1"` | `worker/server.py` |
| `INCOMPLETE_EXTRA_S` | `"1.2"` | `worker/session.py` |
| `KOKORO_MODEL` | `"models/cache/kokoro-v1.0.onnx"` | `worker/pipeline.py` |
| `KOKORO_VOICE` | `"bf_emma"` | `worker/pipeline.py` |
| `KOKORO_VOICES` | `"models/cache/voices-v1.0.bin"` | `worker/pipeline.py` |
| `LLM_BASE_URL` | `"http://localhost:8000/v1"` | `worker/examiner/llm.py` |
| `LLM_MODEL` | `"Qwen/Qwen2.5-7B-Instruct-AWQ"` | `worker/examiner/llm.py` |
| `LOG_DIR` | `"/root/work"` | `worker/server.py` |
| `MAX_WAIT_S` | `"6.0"` | `worker/session.py` |
| `MOCK` | `(unset)` | `worker/server.py` |
| `OFFTOPIC_LIMIT` | `"3"` | `worker/session.py` |
| `OTHER_PAUSE_S` | `"1.2"` | `worker/session.py` |
| `PART1_MAX_S` | `340` | `worker/session.py` |
| `PART1_MIN_S` | `270` | `worker/session.py` |
| `PART2_EARLY_GIVEUP_S` | `"6"` | `worker/session.py` |
| `PART2_EARLY_STOP_S` | `"4"` | `worker/session.py` |
| `PART2_GIVEUP_S` | `"5"` | `worker/session.py` |
| `PART2_PREP_S` | `t["part2"]["prepare"]` | `worker/session.py` |
| `PART2_REMIND_S` | `"5"` | `worker/session.py` |
| `PART2_SILENCE_S` | `"6"` | `worker/session.py` |
| `PART2_SPEAK_S` | `t["part2"]["speak"]` | `worker/session.py` |
| `PART3_MAX_S` | `340` | `worker/session.py` |
| `PART3_MIN_S` | `270` | `worker/session.py` |
| `PART3_PAUSE_S` | `"2.0"` | `worker/session.py` |
| `PERSONAL_MIN_WORDS` | `"6"` | `worker/examiner/rules.py` |
| `PORT` | `"8080"` | `worker/server.py` |
| `SHORT_ANSWER_EXTRA_S` | `"1.0"` | `worker/session.py` |
| `STT_VAD_FILTER` | `"1"` | `worker/stt.py` |
| `TEST_MAX_S` | `960` | `worker/session.py` |
| `THINKING_EXTRA_S` | `"2.5"` | `worker/session.py` |
| `VAD_CONFIDENCE` | `"0.5"` | `worker/pipeline.py` |
| `VAD_MIN_VOLUME` | `"0.0"` | `worker/pipeline.py` |
| `VAD_START_SECS` | `"0.2"` | `worker/pipeline.py` |
| `VAD_STOP_SECS` | `"0.6"` | `worker/pipeline.py` |
| `WHISPER_COMPUTE` | `"float16"` | `worker/pipeline.py` |
| `WHISPER_DEVICE` | `"cuda"` | `worker/pipeline.py` |
| `WHISPER_MODEL` | `"large-v3-turbo"` | `worker/pipeline.py` |

