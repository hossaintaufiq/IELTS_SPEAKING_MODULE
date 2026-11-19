# 11 — Local TTS: sentence streaming and first-audio latency

## Objective
Test how much splitting examiner speech into sentences, and into a short opening chunk, reduces the time before the candidate hears anything when using local Kokoro TTS on CPU (experiment 03 showed generation is faster than playback but slow per utterance).

## Method
- Three multi-sentence examiner utterances (Part 2 instruction, feedback paragraph, Part 3 question) were synthesised with Kokoro int8, voice `bf_emma`, speed 0.95, after a warm-up.
- Three strategies were timed: whole utterance in one call, first sentence only, and the first six words only.
- Stalls were counted with a simple playback model: sentences play back to back, and a stall occurs when the next sentence finishes generating after the previous one finished playing.

Machine: Intel Core i7-1195G7 (4 cores), 8 GB RAM, no GPU. Single request at a time.

## Results

| Utterance | Sentences | Speech (s) | First audio, whole (s) | First audio, first sentence (s) | First audio, first 6 words (s) | Total generation, streamed (s) | Stalls |
|---|---|---|---|---|---|---|---|
| Part 2 instruction | 3 | 10.5 | 5.42 | 3.37 | 1.41 | 7.45 | 0 |
| Feedback paragraph | 3 | 15.6 | 9.82 | 3.42 | 1.70 | 10.23 | 0 |
| Part 3 question | 3 | 7.5 | 4.60 | 2.22 | 2.08 | 5.55 | 0 |

## Findings
- Waiting for the whole utterance takes 4.6–9.8 s, which is unusable for conversation.
- Playing the first sentence as soon as it is ready cuts first audio by 40–65%, to 2.2–3.4 s, with no stalls in any case.
- A short opening chunk of about six words brings first audio to 1.4–2.1 s, near the 1.5 s target used in the earlier browser lab, at the cost of possibly unnatural prosody at the join (not assessed by ear).
- Generation has a fixed overhead per call of roughly one second, so very short chunks stop helping, as the Part 3 result shows.

## Limitations
- Timing varies between runs by several tenths of a second; one run per cell.
- Stall counts come from a simplified playback model, not from real audio output.
- No listening test of how chunk boundaries sound.
- Pre-rendering fixed prompts (experiment 04) avoids this latency entirely for scripted speech.

## Reproduce
```
pip install kokoro-onnx
set KOKORO_DIR=path\to\kokoro\model\folder
python run.py
```
