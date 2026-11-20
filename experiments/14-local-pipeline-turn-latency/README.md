# 14 — Local pipeline: end-to-end turn latency

## Objective
Measure the delay between the candidate finishing a turn and the first examiner audio being ready when the whole conversation loop (speech-to-text, a language model and text-to-speech) runs locally on a CPU.

## Method
One loop per turn, in sequence:

1. `faster-whisper` `base.en` (`int8`, beam 1) transcribes a candidate clip of 23–26 s.
2. An Ollama model generates a follow-up question, streamed. Time stops at the end of the first sentence.
3. Kokoro int8 (`bf_emma`) synthesises that sentence.

Turn latency is the sum of the three. Six turns were run after warm-up using three synthetic clips twice. The LLM prompt is the one from experiment 07.

Machine: Intel Core i7-1195G7 (4 cores), 8 GB RAM, no GPU.

## Results

`qwen3:0.6b`, six turns:

| Turn | Candidate audio (s) | STT (s) | LLM first token (s) | LLM first sentence (s) | TTS (s) | Turn latency (s) |
|---|---|---|---|---|---|---|
| 1 | 25.9 | 2.39 | 2.35 | 2.63 | 2.95 | 7.97 |
| 2 | 24.8 | 1.65 | 2.32 | 2.51 | 3.39 | 7.55 |
| 3 | 22.7 | 1.41 | 2.28 | 2.63 | 4.56 | 8.60 |
| 4 | 25.9 | 1.73 | 2.10 | 2.25 | 2.14 | 6.12 |
| 5 | 24.8 | 1.44 | 2.11 | 2.30 | 2.63 | 6.37 |
| 6 | 22.7 | 1.60 | 2.08 | 2.20 | 1.47 | 5.28 |

Median 7.55 s, maximum 8.60 s. Raw data: `results_qwen3_0.6b.json`.

`qwen3:1.7b`: only one turn completed (STT 1.79 s, LLM first sentence 3.35 s, TTS 1.39 s, total 6.54 s). The run then stopped with an out-of-memory error (`Unable to allocate 3.79 MiB`) because other applications were using most of the 8 GB. A first attempt failed the same way. No summary statistics are reported for this model, and the single turn should not be read as a median.

## Findings
- A fully local loop on this CPU needs about 5–9 s from the end of the candidate's turn to the first examiner audio. That is noticeably slower than a hosted live-voice model and would feel like a long pause.
- The LLM's time to first token (about 2.1–2.4 s even for a 0.6B model) is a fixed cost of loading the prompt into the model on CPU and is as large as STT and TTS combined.
- The loop is not cheap on memory: Whisper, Kokoro and a 1.7B model together did not fit comfortably next to ordinary desktop applications on 8 GB. Dedicated server memory must be budgeted for all three.
- Ways to cut the delay, not tested here: start transcription while the candidate is still speaking, keep the model warm with a cached system prompt, use a fixed acknowledgement phrase (pre-rendered audio, experiment 04) while the reply is generated, and stream the LLM output into TTS by sentence (experiment 11).

## Limitations
- Six turns of one model; the larger model is incomplete.
- Sequential, single user, no network. A real deployment adds network and queueing time.
- Synthetic clips: transcripts were near-perfect, so the LLM saw clean input.

## Reproduce
```
pip install faster-whisper kokoro-onnx soundfile
ollama pull qwen3:0.6b
set KOKORO_DIR=path\to\kokoro\model\folder
python run.py qwen3:0.6b
```
Close memory-heavy applications before running a larger model.
