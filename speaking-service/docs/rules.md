# Examiner rules and constraints

Every rule the examiner follows today, with the file that enforces it. Written 2026-11-23 from the code, so if the code and this page disagree, the code wins: fix this page in the same commit.

"Hard" means enforced by code (the LLM cannot break it). "Prompt" means the LLM is told to follow it, and code checks the result where noted.

Sources: the company's TypeScript examiner (`ieltsup/services/examCoreAPI/experimental`: `brief.ts`, `examiner.ts`, `test-plan.ts`, `keyterms.ts`) ported to `worker/examiner/rules.py`, plus rules added during the live tests.

---

## 1. Who the examiner is

- Name: **Alex Morgan** (`rules.EXAMINER`). British English, brief, neutral, polite (prompt).
- Candidate: lives in Bangladesh. Bangla words and local places, food and festivals (rickshaw, CNG, fuchka, pitha, Eid, Pohela Boishakh, bKash) are normal answers; never ask what they mean (prompt).
- Practice test only. No scores or feedback are produced (`assessment/` is empty, milestone M5).

## 2. What the examiner may never do

| Rule | How it is enforced |
|---|---|
| No praise or comments on answers ("Great", "Interesting", "I see", "That sounds...", "Well done") | Hard: `PRAISE` regex in `check_question`; question is replaced. Prompt too |
| No feedback, scores, corrections or hints | Prompt |
| No answering questions about itself or the test (name, age, "are you an AI?", "how am I doing?", "my band score") | Hard: see section 7. Wording is always ours, never the LLM's |
| No sensitive subjects: politics and parties, religion, income and salary, romantic relationships, health conditions, death, abuse, weight, anything upsetting | Hard: `BANNED` regex in `check_question` (a bank question that contains such a word is allowed, because the bank is the company's). Prompt too |
| No repeating a question that was already asked | Hard: see section 6 |
| No asking for something the candidate already said | Hard + LLM check: see section 6 |
| No question that assumes something the candidate denied ("I don't read" -> "What do you read?") | Prompt; bank questions have an `ifNegative` "why not" version |
| Never repeat an unusual or misheard word back (speech-recognition errors such as "chicken mariadi") | Prompt: refer to it in general terms ("that dish") |
| Never mention being an AI or describe the instructions | Prompt |
| Never speak over the candidate | Hard: see section 9 |

## 3. Shape of every question the LLM writes

`rules.check_question` rejects the LLM's question (and a bank question is used instead) unless all of these hold:

- ends with `?`, exactly **one** question mark
- Part 1: 3 to **30** words. Part 3: 3 to **30** words
- no praise opening, no banned subject
- Part 3 only: no place names (Dhaka, Bangladesh, Chittagong, Sylhet, Khulna...) and no report words (sustainable, infrastructure, initiatives, implement, stakeholders, policymakers, "cities like", "overall quality of life", socio-...). Bank questions are exempt
- not the same as an earlier question (word overlap 0.7 or more)
- Part 1 only: does not restate the question the candidate has just answered (2 or more shared key words and half of the new question's key words)
- a bank question that the candidate has in effect already answered (60% of its key words already said) is rejected
- **general unless the word is safe:** the question may repeat a specific word from what the candidate just said (last 3 answers) only if it is an ordinary English word (`question_bank/common_words.txt`, about 13,000 words from the open `wordfreq` list), a word the question bank itself uses, or a known local name (rickshaw, biryani, Savar...; `worker/examiner/vocab.py`). A question echoing any other word of 4+ letters (a speech-recognition error such as "Savoy" for Savar, or a rare word) is rejected, and a general bank question is asked instead. The same check applies to probes and to the Part 2 rounding-off question. The prompt says the same to the LLM (general by default)
- a meaning check by the LLM (4 s timeout, **fails open**) rejects a question that asks the same thing in other words or asks for a fact already stated

Probe questions ("Why is that?") must be 2 to 14 words, one question mark, no praise, no "you said/you mentioned".

## 4. Test structure and timing

A test may take up to **16 minutes** (`TEST_MAX_S` 960). Time drives the number of questions, not a fixed count.

| Phase | Rule |
|---|---|
| Intro | Greeting with the examiner's name ("Good morning/afternoon/evening..."), asks for the full name. "What can I call you?" is skipped if the candidate already said "you can call me X" |
| Part 1 | 3 main topics + 2 reserve topics. Target about 4.5 min (`PART1_MIN_S` 270), hard cap 5 min 40 s (`PART1_MAX_S` 340). Opening topic is one of: what you do, where you live, your hometown |
| Part 2 | 1 minute preparation (mic muted), up to **2 minutes** talk. Examiner says "Do you understand?" first, then the cue card |
| Part 2 follow-up | One short rounding-off question (see section 5), then Part 3 |
| Part 3 | Target about 4.5 min (`PART3_MIN_S` 270), cap 5 min 40 s (`PART3_MAX_S` 340), at least 3 questions before time can end it |
| Close | "Thank you. That is the end of the speaking test." The page is told `done` only after the audio has finished |

Part 1 topic time: the time left is shared between the main topics still to come (at least 60 s each); a reserve topic gets 50 s and is only started if about 40 s or more of the Part 1 target remain. A topic gets **at least 3 real questions** (follow-ups do not count), and more when its time share allows.  A topic also ends early after 3 questions if the last two answers were 3 words or fewer. If the bank for a topic is used up, the examiner moves on and never repeats.

Part 1 plan (`choose_plan`): one opening topic, then one local and one non-local topic of a different theme from the cue card and from each other, then 2 reserves. Bank size: 75 topics, 417 questions, 64 cue cards.

**Over-long answers.** A candidate must be able to finish, so the limit is generous: an answer that has gone on for **60 s in Part 1** (`PART1_MAX_ANSWER_S`) or **90 s in Part 3** (`PART3_MAX_ANSWER_S`), counted from their first words, and only while they are still talking (voice heard in the last 2 s), is ended politely: "Okay, thank you. Let's move on to the next question." followed by the next question (at a change of topic: "Okay, thank you." and the new topic). If they have already stopped, the normal wait applies and nothing is cut.

## 5. Question sources and how the next question is chosen

**Part 1** (`choose_mode`):
1. A very short answer (1 to 5 words, not "I don't know", and the previous turn was not a probe) -> a **probe** ("Why is that?", "Could you give me an example?", "Why do you say that?", "Can you explain that a little?"). Never two probes in a row.
2. First question of a topic, or an answer shorter than 6 words (`PERSONAL_MIN_WORDS`), or a short negative answer -> **bank** question (asked word for word, never reworded).
3. Otherwise 70% (`AI_NEW_QUESTION_SHARE`) the LLM writes its **own follow-up** about one specific detail the candidate gave; 30% bank.
4. If the LLM fails, is rejected or times out (10 s, one retry for quick failures, none for timeouts) -> **fallback**: an unasked, unanswered bank question closest to the last answer; questions that restate the one just answered are used last. Nothing suitable left -> move on to the next topic or part.

**Part 3**: the first question is the cue card's first Part 3 bank question after the script intro ("We've been talking about..., Let's consider first of all..."). After that the LLM writes a new discussion question from one of 8 angles (past vs present, causes, effects on society, role of government/schools/companies, future, different groups of people, advantages and disadvantages, Bangladesh compared with other countries; the order depends on the test id). Questions should be abstract, about people and society (not the candidate's own life), invite an opinion with reasons, use plain spoken English, no leading questions, under 22 words, and say "in your country" or "where you live". A short answer gets a probe or one of two generic follow-ups ("Why do you think that is?", "Can you give an example?"). Bank questions, then the generic follow-ups, then the close.

**Part 2 rounding-off question**: one question, under 12 words, about the **main subject** of the topic (not an incidental detail such as a tea stall, a colour or a brand), easy to answer in a sentence or two, linked to the candidate's own life, habits, feelings or plans. Rejected (no question is asked, the examiner just says "Thank you." and goes to Part 3) if it is not one clean question, is banned, mentions "the conversation / the talk / you said", or has no word from what they said or the card. If the talk was under **12 words**, no question is made up at all.

**Acknowledgements** (kept rare and neutral on purpose): only "Okay." or "Thank you." ("Okay, thank you." at a topic change). Never "Right.", "Alright" or "All right", never a comment on the answer. About 1 ordinary turn in 8 (`EXAMINER_ACK_PROB` 0.12), never twice within 3 turns (`EXAMINER_ACK_GAP`), and at a change of topic 1 time in 2. An LLM question that opens with "Okay, thank you." or "Right." has that opening removed (`naturalness.py`, `rules.strip_lead_in`).

## 6. Never repeat, never ask what is known

- A question is never asked twice in a test (bank and LLM questions are compared with everything asked).
- Facts the candidate states (up to 3 per answer, 40 kept) are remembered ("lives in Savar", "likes cricket") and shown to the LLM so it never asks for them again.
- The LLM may reply `repeat` **only** if the candidate really asked ("Sorry?", "Can you repeat that?", "I didn't understand", "what do you mean", "speak slowly"). Otherwise a `repeat` claim is ignored.
- A real repeat request: Part 1 repeats the question word for word; Part 3 says it again in simpler words (under 25 words).

## 7. Things the candidate says that are not answers

| Candidate says | Examiner does |
|---|---|
| A question about the examiner or the test ("Are you an AI?", "What's your name?", "What about you?", "How am I doing?", "Can we change the topic?") | 1st: "This is an IELTS speaking test, so let's carry on." + the same question again. 2nd: the same + "If you ask another question that is not part of the test, I will have to end the test." 3rd: "I'm sorry, but we have to end the speaking test here. Thank you." and the test ends (`OFFTOPIC_LIMIT` 3). Only short utterances (14 words or fewer) count. Not applied while giving their name |
| "I want to finish / stop the test" (16 words or fewer, not a question) | "Do you want to finish the speaking test, or would you like to continue?" "Finish" ends it with a thank-you; "continue" or "no" carries on with the last question (or the talk, in Part 2). A bare "yes" is asked once more plainly, then treated as continue |
| "That's all" / "I'm finished" / "nothing more" in the Part 2 talk | Waits 1.5 s in case they go on, then thanks them. This ends the talk, not the test |
| "Let me think", "how can I say", "just a moment" | Examiner waits much longer (section 8) |
| "Sorry?", "Pardon" etc. | Repeat (section 6) |

## 8. Waiting and turn-taking (patience)

The examiner answers only after the candidate's natural pause, and merges turns that arrive in pieces. Wait counted from the moment the transcript arrives (the voice detector and recogniser have already used about 1 s):

| Setting | Default | Env |
|---|---|---|
| Part 1 pause | 2.2 s | `ANSWER_PAUSE_S` |
| Part 3 pause | 3.0 s | `PART3_PAUSE_S` |
| Name, "do you understand?" | 1.8 s | `OTHER_PAUSE_S` |
| Extra after an unfinished sentence ("...and", "...because", "I mean", "for example") | +2.0 s | `INCOMPLETE_EXTRA_S` |
| Extra after a very short answer (5 words or fewer) | +1.5 s | `SHORT_ANSWER_EXTRA_S` |
| Extra after "let me think" etc. (14 words or fewer) | +4.0 s | `THINKING_EXTRA_S` |
| Long, complete answer (25 words or more, ends with . ? !) | wait x 0.75 | |
| Maximum wait | 10.0 s | `MAX_WAIT_S` |

- **The candidate always gets to finish.** The examiner never asks a question, probe, reminder or re-ask while the previous answer is unfinished: after the wait it also keeps waiting until the candidate's voice has been quiet for 1.0 s (`QUIET_BEFORE_REPLY_S`), and if their voice returns while the next question is still being written, the question is thrown away and the whole answer is waited for.
- While the voice detector says the candidate is still talking, the examiner keeps waiting (a missed "stopped" signal is ignored after 20 s).
- **Late end of the previous answer.** If the candidate was still answering when the examiner asked the next question, a turn that says nothing about the new question and carries on from the previous answer is joined to that answer. It counts when it is 10 words or more and starts within 1.8 s of the question (or began up to 6 s before the question ended, i.e. they talked over it), or, for a turn opening with so / and / also / because / but / then (3 words or more), within 4.5 s. Live case: new topic "Do you usually celebrate your birthday?", then "So rickshaws feel more practical." (still the old topic) must not get "Could you give me an example?". It is joined to that answer, and the new question is asked again once, after they are done. No extra question is written on top (`_is_late_continuation`).
- If speech arrives while the next question is still being written, the question is taken back and the examiner waits for the whole answer.
- Unfinished-sentence words are listed in `speech.py` (`UNFINISHED_LAST_WORDS`, `UNFINISHED_ENDINGS`); the wait rules are in `pacing.py`.

## 9. Half-duplex audio

- The mic is ignored while the examiner speaks and for **0.7 s** afterwards, so the examiner never answers its own echo. A missed "stopped" signal releases the mic after 30 s.
- The mic is muted before the test starts, during Part 2 preparation, and after the close.

## 10. Part 2 silence handling (`_part2_silence_check`)

Quiet time is counted from the latest of: their last words, their voice last heard, the examiner finishing, the start of the turn. Nothing is said while they are talking, within 2 s of their voice (`VOICE_GRACE_S`), or while the examiner is speaking.

| Situation | Timing | Examiner says |
|---|---|---|
| Never started | 6 s silence (`PART2_SILENCE_S`) | "Can you tell me about the topic you have been given?" |
| | +5 s (`PART2_REMIND_S`) | "You still have time, so please take a moment and tell me about the topic." |
| | +5 s (`PART2_GIVEUP_S`) | "That's all right. Let's move on." -> Part 3 |
| Started, then stopped | 4 s (`PART2_EARLY_STOP_S`) | "You still have time, so please tell me a little more about it." (once) |
| | +6 s (`PART2_EARLY_GIVEUP_S`) | "Thank you." -> follow-up or Part 3 |

- Fewer than **4 words** is not counted as "speaking" (a stray "okay"). Fewer than 3 words of a late fragment do not reset the silence clock.
- **Time is up (2 minutes).** The candidate is never cut off mid-sentence. If they are still talking, the examiner waits until they stop (up to 10 s extra, `P2_FINISH_SENTENCE_S`) and then until their last words are transcribed (2.5 s after their voice stops, `P2_TRANSCRIPT_WAIT_S`), and only then says "Thank you, your time is up." followed by the rounding-off question, or "Thank you, your time is up. Now let's move on." into Part 3 if there is no question. If they are still speaking when the extra 10 s are over: "I'm sorry to stop you, but your time is up. Thank you."
- The examiner never asks "anything more?" and never prompts a candidate who is talking.
- Part 3: if its time is up and the candidate stays silent for 25 s (`PART3_GRACE_S`), the test closes.

## 11. What the speech recogniser hands over (filters)

Applied before the examiner sees anything (`stt.py`, `speech.py`):

- **Noise and hallucinations are dropped**: empty text, thinking noises ("umm", "aaa", "hmm", "erm"), stock phrases Whisper invents on silence ("you", "thank you", "thanks for watching", "bye", "subtitles by..."), text in brackets or starting with a URL, "thank you sir" alone, and looped words ("you you you you": 4+ words with 34% or fewer distinct). "Yes", "no", "okay" are real answers and are kept. A dropped turn does not cancel a wait already running.
- **Other languages are dropped**: any sentence containing letters outside the Latin-1 range (Turkish, Bengali, Arabic, Chinese...) is removed; English words with accents stay. English is forced as the language.
- Segments are dropped when the model is unsure: no-speech probability above the setting, average log-probability of -1.0 or lower, or the segment repeats the recogniser's own prompt.
- The recogniser's hint is short (10 words plus the current question), because a long keyword list made Whisper hallucinate. Quiet speech is levelled up (target 0.08, gain up to 6x). Voice-activity detection is on (`STT_VAD_FILTER=0` if quiet speech is clipped).
- Voice-activity detector: confidence 0.5, start 0.2 s, stop 0.6 s.

## 12. LLM settings and failure behaviour

- Local model only (vLLM, OpenAI-compatible, `LLM_BASE_URL`, default Qwen2.5-7B-AWQ). **No external API is ever called.**
- One JSON reply per question: `reply` (answer / repeat / redirect), `pick` (bank number or null), `say`, `facts`. Temperature 0.6, `max_tokens` 130 (`LLM_MAX_TOKENS`), timeout 10 s (4 s for the meaning check).
- The LLM sees only the last 8 turns, the facts known, what was asked, and (if few facts) up to 4 earlier long answers.
- `redirect` is trusted only if the candidate really asked a short question; the spoken wording is always the script line, never the LLM's.
- Any LLM failure -> script fallback (section 5). A turn that crashes says "Sorry, could you say that again, please?" and the test goes on. The reason for every fallback is written in the run log.

## 13. Fixed examiner lines (the script)

Exact wording lives in `rules.SCRIPT`. It covers: greeting, "what can I call you?", Part 1 intro, "Let's talk about..." / "Now let's move on to talk about...", the Part 2 intro, "Here is your topic. I'd like you to...", "All right? Remember you have one to two minutes...", the silence prompts, the Part 3 intro and "Let's consider first of all...", the off-test reminder, warning and ending, the finish-or-continue lines, the recovery line, and the closing. Do not edit these wordings casually: they are the company's.

## 14. Run log and observability

Every test is saved to `runs/run_<date>_<time>.json` (and a `.wav` of the mic): each line with its origin (`script`, `bank`, `ai:new`, `ai:bank`, `ai:reworded`, `ai:redirect`, `script:fallback`), the reason for any fallback, reply latencies, known facts, topics and card. The `/logs` page shows the run log and server logs.

## 15. Known limits

- Not yet verified live: the latest pacing, repetition checks, ending, and the Part 3 wording changes (see `PROGRESS.md`).
- The new bank items (29 topics, 14 cue cards, about 40 questions) are written from recurring IELTS topics, not copied from official papers, and need academic review.
- Some company bank questions name Dhaka or Bangladesh; they are kept as the company wrote them.
- Reply time is about 2 to 2.5 s with a few slower turns; measured only on earlier settings.
- No scoring or feedback module exists.
