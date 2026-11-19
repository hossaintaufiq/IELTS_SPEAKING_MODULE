# 01 — Local speech-to-text: Whisper model size

## Objective
Measure how much CPU time, memory and accuracy each English Whisper model needs when the candidate's speech is transcribed locally with `faster-whisper` instead of a paid API.

## Method
- Three candidate-style passages (about 70 words each) were rendered with two Windows voices (David, Zira) at 16 kHz mono, giving 6 clips and 145.4 s of audio.
- Each model was loaded with `int8` quantisation on CPU and decoded with `beam_size=1`.
- Word error rate (WER) was computed with `jiwer` after lower-casing and stripping punctuation.
- Model RAM is the growth in process memory when the model is loaded.

Machine: Intel Core i7-1195G7 (4 cores), 8 GB RAM, no GPU, Windows 11.

## Results

| Model | Load (s) | Model RAM (MB) | RTF | WER (%) |
|---|---|---|---|---|
| tiny.en | 1.19 | 104 | 0.032 | 0.5 |
| base.en | 1.13 | 127 | 0.052 | 0.5 |
| small.en | 2.60 | 321 | 0.146 | 0.5 |

RTF is decode time divided by audio length. Load times are from a warm disk cache.

## Findings
- All three models decode far faster than real time on a laptop CPU. `small.en` needs about 15% of the audio duration.
- A 9-minute candidate recording would take roughly 17 s (`tiny.en`), 28 s (`base.en`) or 79 s (`small.en`) of one machine's time.
- The hosted alternative costs about $0.003–$0.006 per audio minute (see experiment 07), so local transcription removes roughly $0.03–$0.05 per test at the price of server time.

## Limitations
- Synthetic voices are clean and uniform. The near-zero WER is **not** representative of real candidates with accents, noise or hesitations. Accuracy by model size must be re-measured on recorded human speech before choosing a model.
- Single-user, single-process timing. Concurrency was not tested.

## Reproduce
```
pip install faster-whisper jiwer soundfile psutil
python run.py
```
Outputs `results.json` and `results.md`. Audio is generated into `audio/` (git-ignored).
