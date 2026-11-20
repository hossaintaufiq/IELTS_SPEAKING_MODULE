# 06 — Realtime API: context growth and caching

## Objective
Show how much of a live voice test's cost comes from re-reading the growing conversation on every turn, and how much prompt caching and context truncation reduce it.

## Method
A cost simulation (no API calls). A 20-response test is modelled as three parts:

| Part | Turns | Candidate per turn | Examiner per turn (light / heavy) |
|---|---|---|---|
| Part 1 | 12 | 15 s | 4 s / 9 s |
| Part 2 | 1 | 120 s | 24 s / 40 s |
| Part 3 | 7 | 30 s | 8 s / 20 s |

- Audio token rates: 10 tokens per second of candidate audio and 20 per second of examiner audio (OpenAI's documented approximation, 600 and 1,200 tokens per minute).
- Every response re-reads the system prompt (400 tokens) and all earlier audio as input.
- Prices per 1M tokens: `realtime-2.1` input $32, cached $0.40, output $64; `realtime-2.1-mini` input $10, cached $0.30, output $20.
- Policies: **no-cache** (all prior context billed at the input rate), **cached** (prior context billed at the cached rate, new candidate audio at the input rate), **truncate** (cached, and only the last 8 turns are kept in context).

## Results

| Examiner talk | Model | Context policy | Candidate min | Examiner min | Input | Cached | Output | Total |
|---|---|---|---|---|---|---|---|---|
| light | realtime-2.1 | no-cache | 8.5 | 2.1 | $2.297 | $0.0 | $0.164 | **$2.461** |
| light | realtime-2.1 | cached | 8.5 | 2.1 | $0.163 | $0.027 | $0.164 | **$0.354** |
| light | realtime-2.1 | truncate | 8.5 | 2.1 | $0.163 | $0.021 | $0.164 | **$0.348** |
| light | realtime-2.1-mini | no-cache | 8.5 | 2.1 | $0.718 | $0.0 | $0.051 | **$0.769** |
| light | realtime-2.1-mini | cached | 8.5 | 2.1 | $0.051 | $0.02 | $0.051 | **$0.122** |
| light | realtime-2.1-mini | truncate | 8.5 | 2.1 | $0.051 | $0.015 | $0.051 | **$0.118** |
| heavy | realtime-2.1 | no-cache | 8.5 | 4.8 | $3.048 | $0.0 | $0.369 | **$3.417** |
| heavy | realtime-2.1 | cached | 8.5 | 4.8 | $0.163 | $0.036 | $0.369 | **$0.568** |
| heavy | realtime-2.1 | truncate | 8.5 | 4.8 | $0.163 | $0.027 | $0.369 | **$0.559** |
| heavy | realtime-2.1-mini | no-cache | 8.5 | 4.8 | $0.953 | $0.0 | $0.115 | **$1.068** |
| heavy | realtime-2.1-mini | cached | 8.5 | 4.8 | $0.051 | $0.027 | $0.115 | **$0.193** |
| heavy | realtime-2.1-mini | truncate | 8.5 | 4.8 | $0.051 | $0.021 | $0.115 | **$0.187** |

## Findings
- Context re-reading is the dominant cost if the cache does not hit: with no caching the same test costs 7x (light) to 6x (heavy) more than with caching.
- With a fully effective cache, cost is driven by the examiner's output audio and by the candidate's new audio. Shorter examiner turns lower cost directly.
- Truncating to the last 8 turns saves only 1–2% on top of caching, because cached tokens are cheap. It matters more when the cache misses.
- `realtime-2.1-mini` cuts the total by about 65–70% in every scenario.

## Limitations
- The cached policy assumes a 100% cache hit on all prior context, which is the best case. Real hit rates must be read from the `response.done` usage fields in a live session. The no-cache row is the worst case, so the true cost lies between the two.
- The token rates are OpenAI's rule of thumb, not measured, and the part structure is a planning assumption.
- Text tokens (system prompt output, transcripts) are billed at separate rates and only the 400-token system prompt is included, at audio rates, which slightly overstates it.

## Reproduce
```
python run.py
```
Needs only the Python standard library.
