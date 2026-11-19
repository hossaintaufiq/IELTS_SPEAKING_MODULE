# 12 — Local speech-to-text: concurrency scaling

## Objective
Find how much transcription work one 4-core CPU can do when several tests are processed at the same time, which sets how many servers a local STT stack needs.

## Method
- Model `base.en`, `int8`, beam 1. Each worker is a separate process that loads its own model, then transcribes the six synthetic clips (145.4 s of audio) twice (290.8 s) after a shared start time.
- Four configurations were run: 1 process with 4 threads, 2 processes with 2 threads, 4 processes with 1 thread, and 4 processes with 4 threads (oversubscribed).
- RTF per stream is the slowest worker's time divided by its audio length. Aggregate throughput is total audio decoded divided by that wall time, which equals how many real-time streams could be kept up with if audio arrived continuously.

Machine: Intel Core i7-1195G7 (4 cores), 8 GB RAM, no GPU.

## Results

| Processes | Threads each | RTF per stream | Audio decoded per second | Equivalent real-time streams |
|---|---|---|---|---|
| 1 | 4 | 0.051 | 19.5 | 19.5 |
| 2 | 2 | 0.071 | 28.2 | 28.2 |
| 4 | 1 | 0.143 | 28.0 | 28.0 |
| 4 | 4 | 0.130 | 30.8 | 30.8 |

## Findings
- Splitting work across processes raises total throughput by about 45% over one four-thread process (19.5 to about 28 seconds of audio per second); oversubscribing threads gives only a further 10%.
- Per-stream speed degrades gracefully: with four simultaneous streams each still decodes at RTF 0.13–0.14, about 7x faster than real time.
- Speech arrives in bursts, not continuously, so STT is unlikely to be the capacity limit for 10–15 simultaneous tests on one machine of this class. TTS and the LLM are the heavier parts (experiments 07 and 11).
- A first attempt with eight processes failed with an out-of-memory error on this 8 GB machine while other applications were open, so memory per worker (a Python process plus model, several hundred MB) has to be budgeted explicitly.

## Limitations
- Audio is processed as whole clips, not a live stream, and the model is `base.en` only; `small.en` is about 2.5x slower (experiment 01).
- The load is pure STT; running TTS and an LLM at the same time on the same CPU would reduce these numbers.
- Short test (about 25 s per configuration) on a laptop with thermal limits and background applications.

## Reproduce
```
pip install faster-whisper soundfile
python run.py
```
Close memory-heavy applications first.
