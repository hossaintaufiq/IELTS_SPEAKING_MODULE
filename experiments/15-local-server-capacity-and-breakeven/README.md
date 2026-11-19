# 15 — Local stack: server capacity and break-even against the API

## Objective
Turn the measured speed of local STT, TTS and LLM (experiments 01, 03, 07, 12, 13) into machine-seconds per test, number of servers for a target concurrency, and the monthly test volume above which a self-hosted fleet becomes cheaper than the Realtime API (experiment 06).

## Method
A calculation with every input listed in `run.py`:

| Input | Value | Source |
|---|---|---|
| Test length | 14 min wall time | planning assumption |
| Candidate / examiner speech | 9.0 / 3.5 min | planning assumption |
| STT RTF | 0.052 (`base.en`), 0.146 (`small.en`) | experiment 01 |
| TTS RTF | 0.65 | experiment 03 |
| LLM time per turn | 2.97 s (`qwen3:1.7b`), 3.98 s (`llama3.2:3b`), 20 turns | experiment 07 |
| Server price | $150 per month per machine | **placeholder**, not a quote |
| Target utilisation | 60% | planning assumption |

Each machine is assumed to match the 4-core laptop the benchmarks ran on. Work per test is the sum of STT, TTS and LLM seconds on one such machine.

## Results

Machine-seconds per test and cost when machines run at the target utilisation:

| STT | LLM | STT s | TTS s | LLM s | Total s | Tests per machine per month | Server cost per test |
|---|---|---|---|---|---|---|---|
| base.en | qwen3:1.7b | 28.1 | 136.5 | 59.4 | 224.0 | 6,943 | $0.022 |
| base.en | llama3.2:3b | 28.1 | 136.5 | 79.6 | 244.2 | 6,369 | $0.024 |
| small.en | qwen3:1.7b | 78.8 | 136.5 | 59.4 | 274.7 | 5,661 | $0.026 |
| small.en | llama3.2:3b | 78.8 | 136.5 | 79.6 | 294.9 | 5,274 | $0.028 |

Machines needed for simultaneous tests (`base.en` + `qwen3:1.7b`; `small.en` + `llama3.2:3b` needs up to 9 at 15 concurrent):

| Concurrent tests | Machines | Monthly cost |
|---|---|---|
| 5 | 3 | $450 |
| 10 | 5 | $750 |
| 15 | 7 | $1,050 |

Break-even test volume per month (fleet cost divided by API cost per test), for `base.en` + `qwen3:1.7b`:

| Concurrent capacity | vs `realtime-2.1-mini` ($0.12) | vs `realtime-2.1`, light examiner ($0.35) | vs `realtime-2.1`, heavy examiner ($0.57) |
|---|---|---|---|
| 5 | 3,750 | 1,286 | 789 |
| 10 | 6,250 | 2,143 | 1,316 |
| 15 | 8,750 | 3,000 | 1,842 |

## Findings
- TTS is about 60% of local compute per test, so the examiner voice, not transcription, drives hardware size.
- Per test, a fully used local machine costs a few cents, far below the API. The fleet is sized for peak concurrency, though, so fixed monthly cost dominates and the saving only appears at volume.
- On these inputs, self-hosting wins above roughly 1,300–3,000 tests per month against the full Realtime model, and above roughly 4,000–9,000 against the mini model. Below those volumes the API is cheaper and needs no operations work.
- Cost per test of the API uses the best-case cached figures of experiment 06; if real cache hit rates are lower the API is more expensive and break-even moves down.

## Limitations
- The server price is a placeholder, and the speeds are from a laptop. A cloud server's cores may be faster or slower; a GPU would change the picture completely. Re-measure on the target hardware.
- The model ignores operations cost, engineering time, monitoring and redundancy.
- Local LLM quality and Pronunciation scoring are not equivalent to the hosted voice model; this compares cost only.
- The concurrency sizing treats load as smooth. Experiment 13 shows TTS exceeds real time beyond about two simultaneous generations per machine, so bursts may need more headroom than shown.

## Reproduce
```
python run.py
```
Edit the constants at the top of `run.py` to test other prices and utilisation.
