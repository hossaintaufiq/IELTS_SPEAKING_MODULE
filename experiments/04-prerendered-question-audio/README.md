# 04 — Pre-rendered examiner audio for scripted prompts

## Objective
Quantify the saving from rendering fixed examiner prompts (Part 1 and Part 3 questions, Part 2 instructions, closing lines) once and replaying the audio file, instead of having a live voice model speak them every test.

## Method
- `question_bank.json` holds 30 prompts in four groups: Part 1, Part 2 instructions, Part 3 and closing.
- Each prompt was rendered with Kokoro (`bf_emma`, speed 0.95, int8 ONNX) on CPU and saved as 24 kHz 16-bit WAV.
- The avoided cost uses the Realtime audio output rate: about 1,200 tokens per minute at $64 per 1M tokens, i.e. $0.0768 per spoken minute (see `gpt-live-voice-api/README.md`).
- The number of scripted prompts per test (14) is an assumption, not a measurement.

## Results

| Metric | Value |
|---|---|
| Prompts rendered | 30 |
| Total speech | 1.55 min (average 3.1 s per prompt) |
| One-off render time | 58.3 s |
| Storage as WAV | 4.5 MB |
| Realtime cost to speak one prompt | about $0.004 |
| Saving per test (14 scripted prompts) | about $0.056 |

## Findings
- The whole bank renders in about a minute and fits in 4.5 MB, so serving it costs effectively nothing.
- Replaying audio also removes the TTS latency for those turns: playback starts immediately.
- The saving is small per test (a few cents) but is free to capture, and it grows if the examiner voice is a more expensive model. It does not cover adaptive follow-up questions, which still need live generation.

## Limitations
- A pre-rendered voice will differ from a live Realtime voice. Mixing the two in one test may sound inconsistent; using the same local voice for scripted and adaptive prompts avoids that (experiment 03).
- The bank is a small sample, not an official question set, and the 14-prompt count is a planning assumption.

## Reproduce
```
pip install kokoro-onnx numpy
set KOKORO_DIR=path\to\kokoro\model\folder
python run.py
```
Audio is written to `audio/` (git-ignored).
