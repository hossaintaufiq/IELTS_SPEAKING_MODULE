# 18 — Local speech-to-text: robustness to noise by model size

## Objective
Find the noise level at which a smaller (cheaper) Whisper model starts to lose accuracy relative to a larger one, so the model size can follow the expected recording conditions.

## Method
- Six synthetic clips (two Windows voices, three passages, 145.4 s) at 16 kHz.
- Gaussian white noise was added at signal-to-noise ratios of 20, 10, 5 and 0 dB, plus a clean baseline. The noise generator is seeded, so every model sees the same audio.
- `tiny.en`, `base.en` and `small.en` ran with `int8` and beam 1; WER is computed with `jiwer` on normalised text.

## Results

WER (%):

| Model | Clean | 20 dB | 10 dB | 5 dB | 0 dB |
|---|---|---|---|---|---|
| tiny.en | 0.50 | 0.50 | 0.50 | 0.74 | 11.63 |
| base.en | 0.50 | 0.50 | 0.50 | 0.50 | 3.22 |
| small.en | 0.50 | 0.50 | 0.50 | 0.50 | 1.24 |

## Findings
- Down to 10 dB SNR, all three models are indistinguishable on this corpus. The smallest model is enough for clean headset recordings.
- Differences appear only at very low SNR: at 0 dB `tiny.en` loses about 11% of words, `base.en` about 3% and `small.en` about 1%.
- If recordings come from laptop microphones in quiet rooms, `base.en` offers a safe margin at a small cost (RTF 0.05, experiment 01). `small.en` is only worth its 3x compute if noisy environments are common.

## Limitations
- White noise is easier than real-world noise (speech babble, traffic, keyboards, room echo), and the TTS voices are cleaner and more regular than human speech. Treat the thresholds as optimistic.
- Accents, fast speech, hesitations and mumbling were not tested; these are where larger models help most. Repeat with recorded candidate speech before choosing a size.

## Reproduce
```
pip install faster-whisper jiwer soundfile numpy
python run.py
```
