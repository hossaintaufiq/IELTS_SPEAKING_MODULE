# Cost-efficiency experiments for the IELTS Speaking test

Nineteen self-contained experiments on how to run the speaking test at the lowest cost, each in its own folder with a README (objective, method, results, findings, limitations, how to reproduce). This page summarises them and gives a recommendation.

All timings were measured on one machine: Intel Core i7-1195G7 (4 cores), 8 GB RAM, no GPU, Windows 11. Test audio is **synthetic** (Windows voices), so accuracy figures are optimistic and say nothing about real candidates. No live API calls were made (no funded key was available), so every API cost below is a **calculation from published prices**, not a bill.

## Assumed test

14 minutes: 9 minutes of candidate speech, 3.5 minutes of examiner speech, 20 turns. These are planning assumptions.

## What each experiment found

| # | Folder | Type | Result |
|---|---|---|---|
| 01 | `01-stt-whisper-model-size` | measured | Local Whisper decodes 7–30x faster than real time on CPU (RTF 0.03–0.15); `small.en` uses 321 MB |
| 02 | `02-stt-quantisation-and-beam` | measured | `int8` is 1.5–2x faster and 3x smaller than `float32`; beam 5 adds 20–30% time with no gain on this corpus |
| 03 | `03-tts-kokoro-cpu` | measured | Local Kokoro runs at RTF 0.5–0.7, median 1.65 s for a short question |
| 04 | `04-prerendered-question-audio` | measured + calculated | 30 prompts render in 58 s, 4.5 MB; replaying them saves about $0.06 per test of live voice |
| 05 | `05-silence-gating-input-audio` | measured + calculated | Gating removes 18–42% of audio, but saves only $0.02–$0.06 and may not change billing |
| 06 | `06-realtime-context-growth-and-caching` | calculated | Context re-reading dominates: $2.5–3.4 without caching vs $0.35–0.57 with it; mini is about 65–70% cheaper |
| 07 | `07-local-llm-examiner-ollama` | measured | Local 0.6B–3B models answer in 2.4–4.0 s; the 3B reads best, the 0.6B sometimes confuses speakers |
| 08 | `08-transcript-assessment-cost` | calculated | Text-based scoring costs about $0.001–$0.003 per test |
| 09 | `09-session-duration-guardrails` | tested (unit) | Duration, idle, daily and concurrency caps work against a fake clock; bounds worst-case spend |
| 10 | `10-stt-vad-filter` | measured | The built-in silence filter saves 2–32% of decode time as pauses get longer |
| 11 | `11-tts-sentence-streaming` | measured | Sentence streaming cuts first audio 40–65%; a six-word opener reaches 1.4–2.1 s |
| 12 | `12-stt-concurrency-scaling` | measured | One machine decodes about 28–31 s of audio per second across processes |
| 13 | `13-tts-concurrency-scaling` | measured | TTS saturates at about 2.2–2.4 s of speech per second; over real time beyond about two generations |
| 14 | `14-local-pipeline-turn-latency` | measured (partial) | Fully local loop needs 5–9 s from end of turn to first audio; 1.7B run incomplete (out of memory) |
| 15 | `15-local-server-capacity-and-breakeven` | calculated | Local stack is about $0.02–$0.03 per test on a full machine, but a fleet only beats the API above roughly 1,300–9,000 tests per month |
| 16 | `16-hybrid-part-routing` | calculated | Scripting Parts 1–2 saves about 53%; adding the mini model for Part 3 saves about 82% |
| 17 | `17-cascaded-api-pipeline-cost` | calculated | Hosted transcription + text model + TTS costs about $0.09–$0.11 per test ($0.05–$0.07 with pre-rendered prompts) |
| 18 | `18-stt-noise-robustness` | measured | All models are equal down to 10 dB SNR; only `tiny.en` degrades at 0 dB (11.6% WER) |
| 19 | `19-realtime-usage-meter` | tested (unit) | Meter for real cost, cache hit rate and token usage; field names not checked against a live session |

## Cost per test, side by side

| Approach | Estimated cost per test | Basis |
|---|---|---|
| Realtime full model, no cache | $2.5 – $3.4 | experiment 06, worst case |
| Realtime full model, cached | $0.35 – $0.57 | experiment 06 |
| Realtime mini model, cached | $0.12 – $0.19 | experiment 06 |
| Hosted cascade (transcribe + text + TTS) | $0.09 – $0.11 | experiment 17 |
| Realtime full, Parts 1–2 scripted | $0.16 | experiment 16, scenario D |
| Realtime mini for Part 3, Parts 1–2 scripted | $0.06 | experiment 16, scenario E |
| Hosted cascade, Parts 1–2 pre-rendered | $0.05 – $0.07 | experiment 17 |
| Fully local | $0.02 – $0.03 compute, plus a fixed fleet of $450–$1,050 per month | experiment 15, server price is a placeholder |

## Recommendation

1. **Start with the hybrid route: scripted Parts 1–2 and the mini live model for Part 3.** The official format already scripts Parts 1–2, pre-rendered audio makes them nearly free (experiments 04 and 16), and this lands at about $0.06 per test, against $0.35 or more for the full model throughout.
2. **Ship the controls before the volume:** session caps (experiment 09) and the usage meter (experiment 19). The largest single risk in the numbers is the gap between $0.35 and $3.4 depending on whether the context cache works, and only the meter can show which one you get.
3. **Move scripted-turn transcription and the post-test assessment onto cheap paths:** local or low-cost hosted transcription (experiments 01, 12, 17) and text-model scoring (experiment 08), both well under a cent or a few cents.
4. **Treat fully local as a volume or privacy decision, not a cost shortcut.** It wins only above roughly 1,300–9,000 tests per month, and its measured 5–9 s turn latency (experiment 14) is the weakest part of the user experience.

## What was not tested, and what is needed

- **Real API behaviour.** All hosted costs are calculated. A funded key and a spending cap would let a short live session confirm tokens per minute, cache hit rate and the experiment 05 gating question.
- **Real candidate audio.** Recordings from real speakers, with accents and noise, are needed to choose a Whisper model size and to test scoring quality.
- **Quality.** No experiment judged voice quality, examiner realism or scoring accuracy against human examiners. A cheaper approach is only useful if those hold up.
- **Server hardware.** A cloud CPU or GPU would change experiments 03, 13 and 15 substantially.
- **Pronunciation scoring** cannot be done from a transcript and is not costed here.
