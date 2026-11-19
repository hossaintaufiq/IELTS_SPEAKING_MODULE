# 02 — Local speech-to-text: quantisation and beam size

## Objective
Find the cheapest `faster-whisper` configuration (precision and beam width) that does not hurt accuracy, to minimise the server memory and CPU needed per concurrent test.

## Method
Same synthetic corpus and machine as experiment 01 (6 clips, 145.4 s, 4-core laptop CPU, 8 GB RAM). Models `base.en` and `small.en` were run at `int8` and `float32` precision with beam sizes 1 and 5. WER uses `jiwer` on normalised text.

## Results

| Model | Precision | Beam | Model RAM (MB) | RTF | WER (%) |
|---|---|---|---|---|---|
| base.en | int8 | 1 | 152 | 0.058 | 0.5 |
| base.en | int8 | 5 | 152 | 0.069 | 0.5 |
| base.en | float32 | 1 | 443 | 0.087 | 0.5 |
| base.en | float32 | 5 | 443 | 0.106 | 0.5 |
| small.en | int8 | 1 | 322 | 0.132 | 0.5 |
| small.en | int8 | 5 | 322 | 0.170 | 0.5 |
| small.en | float32 | 1 | 1159 | 0.270 | 0.5 |
| small.en | float32 | 5 | 1159 | 0.340 | 0.5 |

## Findings
- `int8` uses about 2.9x (base) to 3.6x (small) less RAM and runs about 1.5x to 2x faster than `float32`, with identical WER on this corpus.
- Beam 5 costs roughly 20–30% more decode time than beam 1 and showed no accuracy gain here.
- On this evidence the cheapest configuration is `int8`, beam 1. At about 322 MB per `small.en` instance, 8 GB of RAM holds well over ten copies; CPU time, not memory, is the limit.

## Limitations
- The corpus is clean synthetic speech, so no accuracy difference between settings could appear. Beam search and larger models mainly help on noisy or accented audio. Repeat on recorded candidate speech before locking in beam 1.
- Memory is the growth in process RSS at load time, not peak usage during decoding.

## Reproduce
```
pip install faster-whisper jiwer soundfile psutil
python run.py
```
