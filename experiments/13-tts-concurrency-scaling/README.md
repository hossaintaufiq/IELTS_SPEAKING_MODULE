# 13 — Local text-to-speech: concurrency scaling

## Objective
Find how much examiner speech one 4-core CPU can generate at the same time, to size local TTS for several simultaneous tests.

## Method
- Kokoro int8 (`bf_emma`, speed 0.95) in separate processes, each with its own ONNX Runtime session and a fixed intra-op thread count, synthesising the same four feedback sentences after a shared start time.
- Configurations: 1 process with 4 threads, 2 with 2 threads, 3 with 1 thread, 4 with 1 thread.
- Worst RTF is the slowest process's generation time divided by the speech it produced. Throughput is total speech seconds produced per wall-clock second.

Machine: Intel Core i7-1195G7 (4 cores), 8 GB RAM, no GPU.

## Results

| Processes | Threads each | Worst RTF | Speech produced per second |
|---|---|---|---|
| 1 | 4 | 0.63 | 1.60 |
| 2 | 2 | 0.94 | 2.14 |
| 3 | 1 | 1.35 | 2.22 |
| 4 | 1 | 1.66 | 2.42 |

## Findings
- Total output saturates at about 2.2–2.4 seconds of speech per second of wall time; extra processes add little and push each stream past real time (RTF above 1).
- Real-time playback without gaps therefore holds for only about two simultaneous generations on this machine. More concurrent requests need more cores, a GPU, or a queue.
- Examiner speech is a fraction of each test (about 25% of a 14-minute test, a planning assumption), so average demand is far below the peak. Requests arrive in bursts after each candidate turn, which is why peak concurrency, not average load, must be sized (see experiment 15).

## Limitations
- Short run on a laptop with thermal limits and other applications open.
- Synthetic load: identical sentences in lockstep, which is harsher than staggered real requests.
- Kokoro on a GPU was not tested; throughput there would be very different.

## Reproduce
```
pip install kokoro-onnx onnxruntime
set KOKORO_DIR=path\to\kokoro\model\folder
python run.py
```
