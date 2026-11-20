# 03 — Local text-to-speech: Kokoro on CPU

## Objective
Measure whether the examiner's voice can be generated locally with Kokoro-82M (int8 ONNX, `kokoro-onnx`) fast enough for a conversation, replacing the most expensive part of a hosted voice API.

## Method
- Model: `kokoro-v1.0.int8.onnx` (92 MB) with voice `bf_emma`, speed 0.95, British English.
- Eight typical examiner utterances (Part 1 to Part 3 questions and the closing line) and one 267-character feedback paragraph were synthesised after a warm-up call.
- Generation time was measured per utterance without sentence streaming. RTF is generation time divided by speech duration.
- The Windows built-in SAPI engine was timed on the feedback paragraph as a zero-dependency baseline.

Machine: Intel Core i7-1195G7 (4 cores), 8 GB RAM, no GPU.

## Results

| Metric | Value |
|---|---|
| Model load | 0.62 s |
| Model RAM | 127 MB |
| Question generation time, median / max | 1.65 s / 2.76 s |
| Question RTF, median | 0.653 |
| Feedback paragraph (15.6 s of speech) | 8.39 s, RTF 0.539 |
| Windows SAPI, same paragraph | 0.84 s generation |

## Findings
- Generation is faster than playback (RTF 0.5–0.7), so streaming playback sentence by sentence can avoid audible gaps on one request at a time.
- Whole-utterance latency of 1.2–2.8 s is too slow for a natural turn if the full question is generated before playing. Splitting into sentences and playing the first immediately is required to get first audio under about 1.5 s.
- Each minute of examiner speech uses about 0.65 CPU-minutes. Four concurrent tests on this 4-core machine would exceed real time, so capacity must be sized from this RTF (see experiment 08).
- Fixed question-bank prompts do not need live synthesis at all (experiment 04).

## Limitations
- No listening test: voice quality was not rated, and SAPI quality was not compared. The SAPI row is a speed reference only.
- The int8 build was used; the fp32 build the earlier browser lab used may sound slightly different.
- One request at a time. No concurrency was tested.

## Reproduce
```
pip install kokoro-onnx psutil
set KOKORO_DIR=path\to\folder\with\model_and_voices
python run.py
```
Download `kokoro-v1.0.int8.onnx` and `voices-v1.0.bin` from the kokoro-onnx `model-files-v1.0` release into that folder.
