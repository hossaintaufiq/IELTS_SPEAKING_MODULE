# 10 — Speech-to-text: built-in voice-activity filter

## Objective
Check whether enabling the `vad_filter` option of `faster-whisper` (which skips non-speech sections before decoding) lowers CPU time on recordings that contain long pauses, as candidates produce in Part 2, without hurting accuracy.

## Method
- Eight clips drawn at random from the synthetic corpus (two Windows voices, three passages) were joined with noise-only gaps of three lengths (1–3 s, 5–10 s, 15–25 s), with microphone-like noise added to the speech as well.
- `base.en`, `int8`, beam 1 on CPU was run with the filter off and on over each recording after a warm-up call.
- WER was computed against the known script with `jiwer`.

Machine: Intel Core i7-1195G7 (4 cores), 8 GB RAM, no GPU.

## Results

| Pauses (s) | Audio (min) | VAD filter | Decode (s) | RTF | WER (%) |
|---|---|---|---|---|---|
| 1–3 | 3.47 | off | 13.7 | 0.066 | 0.20 |
| 1–3 | 3.47 | on | 13.4 | 0.064 | 0.20 |
| 5–10 | 4.25 | off | 13.3 | 0.052 | 0.55 |
| 5–10 | 4.25 | on | 11.8 | 0.046 | 0.55 |
| 15–25 | 6.05 | off | 18.2 | 0.050 | 0.70 |
| 15–25 | 6.05 | on | 12.3 | 0.034 | 0.70 |

## Findings
- The filter costs nothing in accuracy on this corpus and saves more CPU as pauses get longer: about 2%, 11% and 32% of decode time across the three cases.
- Gains are modest because Whisper is already fast (RTF 0.03–0.07 for `base.en`). It is worth enabling by default for recordings with long silences and does not change the cost picture on its own.

## Limitations
- Synthetic speech with clean digital silence between phrases; real hesitations, breaths, fillers and background noise may be treated differently by the filter. Check that it does not cut quiet or hesitant speech, which would lower fluency measurements.
- Single run per condition; differences of a few percent are within timing noise.

## Reproduce
```
pip install faster-whisper jiwer soundfile numpy
python run.py
```
