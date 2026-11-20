# 05 — Silence gating of candidate audio

## Objective
Estimate how much candidate-side input audio, and therefore input token cost, could be removed by not sending silence to a billed voice API.

## Method
- A synthetic 5–7 minute candidate session was built from twelve 24-second clips (two Windows voices, three passages) separated by silent gaps, with microphone-like noise (σ = 0.002) mixed in everywhere.
- Gap length was varied across three ranges: 1–3 s, 3–6 s and 8–15 s.
- A simple energy gate was applied to 30 ms frames: a frame is kept when its level exceeds the 10th-percentile noise floor by a margin (12 dB or 20 dB), with a 300 ms hangover.
- Cost uses the Realtime audio input rate: about 600 tokens per minute at $32 per 1M tokens ($0.0192 per minute).

## Results

| Gap (s) | Margin (dB) | Speech share | Audio kept | Speech recall | Input cost, all audio | Input cost, gated |
|---|---|---|---|---|---|---|
| 1.0–3.0 | 12 | 91.8% | 82.3% | 89.7% | $0.0996 | $0.0819 |
| 1.0–3.0 | 20 | 91.8% | 81.5% | 88.8% | $0.0996 | $0.0812 |
| 3.0–6.0 | 12 | 84.5% | 75.4% | 89.2% | $0.1093 | $0.0824 |
| 3.0–6.0 | 20 | 84.5% | 74.6% | 88.3% | $0.1093 | $0.0816 |
| 8.0–15.0 | 12 | 66.2% | 58.8% | 88.8% | $0.1367 | $0.0804 |
| 8.0–15.0 | 20 | 66.2% | 58.1% | 87.7% | $0.1367 | $0.0794 |

## Findings
- Gating removes 18–42% of the audio, depending on how much the candidate pauses, and the cost saving scales the same way.
- In absolute terms the saving is small: about $0.02–$0.06 on a 5–7 minute candidate recording, because candidate audio is the cheap direction (about $0.019 per minute).
- The margin setting made little difference once noise was present.
- Speech recall of about 89% is understated: the "speech" label covers each whole clip, and the gate also removes the short natural pauses inside the clips. Recall of real words was not measured.

## Limitations
- Synthetic speech and noise; no real microphone, room noise or hesitation sounds.
- It is **not verified** that a gated or muted WebRTC track reduces what the API bills. Tracks that keep sending comfort noise may still be tokenised. This needs a live test with a funded key before the saving can be claimed.
- Cutting audio can clip word starts and breaks the API's own turn detection; a gate must be tested against end-of-turn behaviour.

## Reproduce
```
pip install numpy soundfile
python run.py
```
