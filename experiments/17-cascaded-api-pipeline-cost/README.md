# 17 — Cascaded hosted pipeline: transcription + text model + speech synthesis

## Objective
Price the alternative to a single live-voice model: transcribe the candidate with a hosted transcription model, generate the examiner's reply with a small text model, and synthesise it with a hosted TTS model.

## Method
A cost model with the following inputs (prices from third-party listings checked on 19 Nov 2026; verify on the OpenAI pricing page):

| Component | Price used |
|---|---|
| `gpt-4o-mini-transcribe` | $0.003 per audio minute |
| `gpt-4o-transcribe` | $0.006 per audio minute |
| `gpt-4.1-mini` | $0.40 input, $0.10 cached input, $1.60 output per 1M tokens |
| `gpt-4o-mini-tts` | about $0.015 per minute (derived estimate; the billed rates are $0.60 per 1M text tokens and $12 per 1M audio tokens) |

Test shape: 9.0 minutes of candidate speech at 130 words per minute, 20 LLM turns, a 600-token system prompt, 25-word examiner replies, and the full conversation text re-sent each turn at the cached rate. Examiner speech is 3.5 minutes in total, of which 56 s is Part 3.

## Results

| Variant | Transcription | Text model | Speech | Total |
|---|---|---|---|---|
| All turns synthesised | $0.027 | $0.005 | $0.053 | **$0.085** |
| All turns synthesised, larger transcription model | $0.054 | $0.005 | $0.053 | **$0.112** |
| Part 3 only synthesised (Parts 1–2 pre-rendered) | $0.027 | $0.005 | $0.014 | **$0.046** |
| Part 3 only, larger transcription model | $0.054 | $0.005 | $0.014 | **$0.073** |

## Findings
- A hosted cascade costs about $0.09–$0.11 per test, close to the cached mini Realtime figure ($0.12, experiment 06) and about a quarter to a third of the full Realtime model ($0.35–$0.57).
- Candidate transcription is the largest line (30–50%), because the candidate talks for most of the test. A cheaper transcription model or local transcription (experiment 01) is the first lever.
- Combined with pre-rendered scripted prompts (experiment 04), the hosted cascade falls to $0.05–$0.07 per test.
- The text model costs under one cent, so using a stronger model for the replies would add little.

## Limitations
- Latency was not measured. A cascade has three network round trips per turn and no interruption handling, so turns will feel slower than a single live-voice connection. This needs a live test.
- The TTS per-minute figure is an estimate, and two of the models (`gpt-4o-mini-tts` and `gpt-4o-mini-transcribe`) are listed by a secondary source as scheduled for retirement in early 2027. Confirm availability before building on them.
- Voice quality, pronunciation scoring and turn-taking behaviour are not compared.

## Reproduce
```
python run.py
```
Edit the price constants at the top of `run.py` to test other models.
