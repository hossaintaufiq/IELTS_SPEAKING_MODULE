# TTS — Tuning Log and Decisions

**Project:** IELTS Speaking Test Engine · **Stage:** 1 of 4 (TTS) · **Date:** 18 November 2026
**Companion to:** *IELTS Speaking Engine — System Architecture Proposal v1.0*

This document records everything decided and tried for the examiner's text-to-speech (TTS) voice, why each choice was made, and what remains open. The test page is `tts_lab/tts_browser.html`.

> **Honesty note.** All voice choices below were made by the project owner listening to the output. No benchmark numbers, MOS scores or listening-panel results have been recorded yet. Where a statement comes from general knowledge rather than a measurement in this project, it is marked *(unverified)*.

---

## 1. Summary of decisions

| # | Decision | Value |
|---|---|---|
| 1 | TTS engine | **Kokoro-82M** (baseline; alternatives not yet tested) |
| 2 | Model precision | **fp32** (q8 was available and faster) |
| 3 | Voice | **`bf_emma` 75% + `bf_alice` 25%** blended |
| 4 | Accent | British, neutral |
| 5 | Speed | **0.95** (±0.02 repeatable variation per chunk) |
| 6 | Mode | **Feedback mode** (streamed, sentence by sentence) is the standard; the separate "Exam prompt" mode was removed from the page |
| 7 | Target first audio | **1.5 s** (placeholder, editable) |
| 8 | Deployment direction | Server-side, GPU, streamed over WebSocket; students interact live |
| 9 | Interruption | End/Pause button only; no talking over the examiner |
| 10 | Next stages | STT accuracy testing, then LLM work (fine-tuning not yet decided) |

---

## 2. Why Kokoro

The examiner voice is mostly **fixed scripted prompts** (introduction, Part 1 questions, cue cards, Part 3 questions) plus short dynamic feedback. That favors a small, fast, licence-clean model whose fixed prompts can be pre-generated and cached.

| Candidate | Notes *(from general knowledge, unverified — re-check before relying on it)* |
|---|---|
| **Kokoro-82M** | Apache 2.0, very small, fast on CPU, ships British voices (`bf_*`, `bm_*`). No emotion control, no voice cloning. **Chosen as baseline.** |
| Chatterbox | MIT; expressive (exaggeration control) and can clone a voice; needs a GPU. Candidate for a comparison if Kokoro sounds too flat. |
| StyleTTS2 | MIT; high quality; more setup work. |
| Orpheus (3B) | Apache 2.0; very expressive but heavy for a fixed-script examiner. |
| Piper | Very fast, lower quality; fallback only. |
| XTTS-v2, F5-TTS | Non-commercial licences were noted, so they were avoided for a company product. |

**Not done yet:** a blind comparison of Kokoro against Chatterbox or any other model.

**Emotion.** Kokoro cannot take an emotion instruction. For IELTS this is acceptable: real examiners are neutral and steady, and consistency across candidates is a fairness concern. The target is "warm, calm and slightly encouraging", achieved through script wording, punctuation, pacing and voice choice rather than emotional synthesis.

---

## 3. Voice selection

- Voices auditioned: the British female voices Emma and Alice were preferred by the project owner.
- A single voice was not used. The two were **blended** by mixing their style vectors per input:
  `style = w · emma + (1 − w) · alice`, applied just before the model runs.
- Blend history: first 50/50 (default in the first test), then 80/20, then **75/25 (final)**.
- Kokoro selects a row of each voice pack by input length, so the blend is computed per row for the current token count.
- Observation by the owner: the British voice is fairly deep and natural speech contains stops, so perceived pace and measured pace may differ. A **words-per-minute** readout was added to the page so pace can be judged from numbers, not feel.

---

## 4. Speed history

| Stage | Speed | Why |
|---|---|---|
| First test page | 0.95 | Starting default |
| After voice picked | 0.85 | Owner's preference ("0.85 is perfect") |
| After "most natural" request | 0.9 | Slightly faster for a human feel |
| After "a little faster" request | **0.95 (final)** | Web guides *(secondary sources)* suggested ~0.95 for a natural reading rhythm |

A repeatable ±0.02 variation (derived from a hash of the sentence text) is added per chunk so delivery is not perfectly uniform, while the same text always yields the same audio — important for caching.

Reference pace figures discussed *(rules of thumb, not measured IELTS data)*: conversational English ≈ 140–170 words/min, careful examiner speech ≈ 110–140. A real examiner recording should be measured to set a proper target.

---

## 5. The text pipeline (in order)

### 5.1 Phrasing clean-up
- Collapse whitespace; turn ` - ` and `;` into commas.
- Add a comma after short discourse openers so the voice takes a breath: *Now, Okay, Alright, Right, Well, So, Good morning, Good afternoon, Good evening, Thank you, Thanks, Lovely, Great, Excellent*.
- Exception: "Thank you for…" / "Thank you very…" keep no comma.
- Remove any comma directly before `. ? !`.
- *Bug found and fixed:* "Let's move on" was originally in the opener list and produced "Let's move on, to the next question". It was removed.

### 5.2 Sentence split and pauses
| Boundary | Pause |
|---|---|
| After a statement (`. !`) | 0.30 s |
| After a question (`?`) | 0.45 s |
| After an ellipsis | 0.70 s |
| Other | 0.25 s |
| `[pause]` marker in the text | +0.60 s |

Each pause is multiplied by a repeatable factor between 0.85 and 1.15 (hash of the sentence) so gaps are not metronomic. In streamed Feedback mode all pauses are then multiplied by 0.8 (20% tighter).

Pause history: 0.40/0.55 s → 0.35/0.50 s → **0.30/0.45 s (final)**.

### 5.3 Merging short sentences — the "Good morning" fix
The owner noticed the speech sounded "weird" after "Good morning". Cause (reasoned from how Kokoro works, not formally proven): sentences were generated one at a time, so "Good morning." was a two-word input. Kokoro chooses its style vector by input length, and very short inputs tend to sound odd, with uneven silence at the edges. Splitting sentence by sentence also made every sentence restart its intonation.

Fix: **merge short neighbouring sentences into one generation**, so the model's own punctuation handling supplies the pause. `[pause]` markers still force a break.

### 5.4 Chunk sizes
- Sentences are merged into chunks of **8–24 words**.
- Only the **first** chunk is shortened for a fast start: if it has more than 14 words it is cut at the first comma (left part at least 6 words).
- All later chunks are re-merged to **14–40 words**. They are generated while the first plays, so they can be long and keep natural prosody.
- *Bug found and fixed:* an earlier version split every long sentence at commas, producing 6–10 word fragments that sounded choppy.

### 5.5 Generation and processing
- A warm-up sentence runs after the model loads (first inference is always slower).
- Each clip has leading/trailing silence **trimmed** (threshold 0.008, 40 ms kept) so the configured pauses are the only pauses.
- Light processing per chunk: one-pole **80 Hz high-pass**, one **gain for the whole utterance** (set from the first chunk so loudness stays even, targeting −3 dBFS, clamped 0.3–3×), and **5 ms fades**.

### 5.6 Processing that was tried and then dropped from the standard
An earlier full-quality "Exam prompt" path also applied a dynamics compressor (3:1, later 2:1), a very small synthetic room reverb (5%, later 4%, then 3%), peak normalisation (−2 then −3 dBFS), and a lead-in/tail of silence. The final page keeps only the Feedback path, so these are **not part of the standard**. They may return if pre-generated exam prompts are produced with a separate higher-quality pipeline.

---

## 6. Streaming design (Feedback mode)

- Sentences are generated one chunk at a time and scheduled for playback immediately, while the next is generated.
- **First audio** = time until the first chunk is ready.
- A **stall** is counted when the next chunk is not ready by the time the previous one (plus its pause) has finished — an audible gap. Streaming only works smoothly if RTF stays below 1.

---

## 7. Benchmark design

Built into `tts_lab/tts_browser.html` (**Test my text ×5** and **Full benchmark**).

- Texts: three built-in feedback samples (short, medium, long) plus the user's text; **5 runs each**; optional silent mode.
- Per text: first-audio p50/p95, RTF mean/p95, stalls, words/min (speech only and with pauses), PASS/FAIL.
- **Pass criteria:** first-audio p95 ≤ target (1.5 s, placeholder) · RTF p95 < 1.0 · 0 stalls.
- Also shown: JS heap, cached model size, CPU cores, WASM threads, single-run log with downloadable WAV.

**Results — to be filled in after running on the target machine**

| Text | Words | First audio p50 / p95 (s) | RTF mean / p95 | Stalls | Words/min | Result |
|---|---|---|---|---|---|---|
| Short feedback | | | | | | |
| Medium feedback | | | | | | |
| Long feedback | | | | | | |

**Limits of these numbers:** browser, single thread, one request at a time, fp32. They indicate the *method*, not server performance.

---

## 8. Server sizing and cost estimator

Included on the page to turn measured RTF into a rough infrastructure estimate:

```
core-seconds per speech-second = RTF × cores used per generation ÷ server speed factor
core-seconds per test          = live-generated audio per test × the above
average cores                  = concurrent tests × core-seconds per test ÷ test duration (s)
peak cores                     = average × burst factor
cores needed                   = peak ÷ (1 − headroom)
workers                        = ceil(cores needed ÷ cores per generation)
RAM                            = workers × RAM per worker + other services
servers                        = max( ceil(cores ÷ server cores), ceil(RAM ÷ server RAM) )
monthly cost                   = servers × price;  cost per test = monthly ÷ tests per month
```

All defaults are **placeholders**: 100 concurrent tests, 14-minute test, 60 s of live-generated audio per test, burst ×4, 1 core, speed factor 1.0, 30% headroom, 1000 MB per worker, 4 GB other services, 8-core/16 GB server, $150/month, 10,000 tests/month, 150 fixed prompts × 5 s. RAM per worker must be read from Chrome Task Manager, because the browser cannot see WASM memory. The estimate is CPU-only and prices no GPU.

---

## 9. Environment issue and workaround

The first plan was a local Python server with Kokoro. On the owner's Windows machine, a Windows **Application Control policy blocked a compiled library** (`srsly`, a spaCy dependency used by Kokoro's text front-end), so the Python server could not start. The policy was not bypassed. Decision: test in the **browser** instead (`kokoro-js`, WebAssembly), which needs no native libraries.

Consequence: the browser text front-end differs from the Python one, so pronunciation and speed numbers may not match the future Python engine exactly. The same Windows restriction would affect local faster-whisper testing; a Linux server avoids it.

---

## 10. Real-time server direction (discussion outcome — nothing built yet)

Context given by the owner: **10–15 students at a time**; the **GPU server runs TTS, STT and the LLM together**; students may interrupt only to end the exam; no added latency wanted.

- "Zero latency" is not achievable; the goal is a delay students do not notice. TTS is the smallest part of the turn delay (voice-activity detection, STT and LLM first token are larger).
- Fixed prompts should be **pre-generated and cached** (essentially zero TTS latency). LLM output should be streamed into TTS clause by clause. Models stay loaded and warm.
- Transport: one WebSocket per session, small browser playback buffer (≈100–200 ms), voice-activity detection in the browser.
- 15 students ≠ 15 simultaneous TTS jobs; peak is likely a few, but this must be measured. A synchronized exam start is covered by cached prompts.
- Main risk is **GPU contention** between the LLM and TTS/STT: separate processes, per-model queues and limits, live dialogue prioritised over feedback and background work, and benchmark the *combined* workload at 10–15 sessions.
- **Interruption:** an on-screen End/Pause button cancels generation server-side and discards unplayed audio client-side. Spoken "end the exam" is deferred (needs headphones/echo cancellation and a confirmation step).
- Proposed targets, to be validated: TTS first audio p95 < 300 ms on the server (excluding network), RTF well under 1.0 under load, zero audible stalls at 15 concurrent sessions. These are proposals, not measured or agreed figures.

Open questions: exam start pattern (scheduled batch or on demand), student location relative to the server, headphone requirement.

---

## 11. STT stage (next)

`stt_lab/stt_browser.html` is built to test Whisper accuracy (tiny.en / base.en / small.en / large-v3-turbo) with WER, CER, a word-level diff and filler tracking. It has not been run. Open points to resolve with real recordings: accuracy on the target candidates' accents, handling of disfluencies ("um", "uh" are often dropped), and whether small.en or larger is needed.

## 12. LLM stage and fine-tuning

No LLM or fine-tuning decisions have been made. Per the architecture proposal, the model, size, quantisation and serving approach are benchmark decisions, and assessment output must be validated against a schema and labelled as estimated practice feedback. Fine-tuning would follow STT validation; its goals, data and method are **to be defined**.

---

## 13. Open items checklist

- [ ] Run the full benchmark and record results (section 7 table).
- [ ] Measure real memory with Chrome Task Manager; update the sizing inputs.
- [ ] Blind listening test with teachers; consider a Chatterbox comparison for naturalness.
- [ ] Measure a real examiner recording's words/min and set a pace target.
- [ ] Agree the real first-audio target (1.5 s is a placeholder).
- [ ] Re-measure on the Python engine on the GPU server; run concurrency tests at 1 / 5 / 10 / 15 sessions.
- [ ] Run the STT accuracy lab on representative candidate audio.
- [ ] Define the LLM and any fine-tuning plan.
