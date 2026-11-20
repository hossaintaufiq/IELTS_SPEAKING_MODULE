# 16 — Hybrid routing by test part

## Objective
Estimate the saving from using the expensive live-voice model only where adaptive conversation matters, and cheap scripted turns elsewhere. In the official format Parts 1 and 2 follow a script (fixed questions, fixed task card instructions), while Part 3 is the open discussion.

## Method
A cost model using the same assumptions as experiment 06:

- Audio rates of 10 tokens per second (candidate) and 20 tokens per second (examiner); 400-token system prompt; all prior context billed at the cached rate, new candidate audio at the input rate, examiner audio at the output rate.
- Part 1: 12 turns (15 s candidate, 4 s examiner). Part 2: one 120 s monologue with 24 s of examiner instructions. Part 3: 7 turns (30 s candidate, 8 s examiner).
- Each part handled by Realtime is its own session, so its context starts fresh.
- A **scripted** part plays pre-rendered question audio (experiment 04, $0) and transcribes the candidate either through a hosted transcription API ($0.003 per minute) or locally ($0).

## Results

| Scenario | Part 1 | Part 2 | Part 3 | Total | vs A |
|---|---|---|---|---|---|
| A. All Realtime full | $0.127 | $0.069 | $0.144 | **$0.340** | baseline |
| B. All Realtime mini | $0.043 | $0.022 | $0.047 | **$0.112** | -67% |
| C. Part 1 scripted + API transcription, rest Realtime full | $0.009 | $0.069 | $0.144 | **$0.222** | -35% |
| D. Parts 1 and 2 scripted + API transcription, Part 3 Realtime full | $0.009 | $0.006 | $0.144 | **$0.159** | -53% |
| E. Parts 1 and 2 scripted + API transcription, Part 3 Realtime mini | $0.009 | $0.006 | $0.047 | **$0.062** | -82% |
| F. Fully scripted, local transcription | $0.000 | $0.000 | $0.000 | **$0.000** | -100% |

## Findings
- Scripting Parts 1 and 2 removes more than half the cost of the full model (scenario D) with no change to Part 3.
- Combining scripted Parts 1 and 2 with the mini model for Part 3 (scenario E) cuts about 82% from the all-full baseline, to roughly six cents.
- Part 1 is the biggest single saving because it has the most turns and re-reads the most context.
- Splitting into separate sessions makes scenario A slightly cheaper ($0.340) than the single-session total in experiment 06 ($0.354), because each session carries less history.

## Limitations
- Scenario F has no live LLM and no adaptive follow-ups, so it is not equivalent; it is the floor, not a recommendation.
- Scripted Parts 1 and 2 lose natural reactions ("That sounds interesting") and acknowledgement of what the candidate said, which a live examiner would give. The effect on realism and on candidate performance was not tested.
- The hosted transcription price is from third-party listings and the same cached-context best case applies as in experiment 06.
- Switching between a scripted voice and a live voice mid-test may be audible.

## Reproduce
```
python run.py
```
