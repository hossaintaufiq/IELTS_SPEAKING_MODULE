# 08 — Post-test assessment from the transcript

## Objective
Estimate the cost of producing the scored feedback report with a small text model after the test, instead of having a live voice model assess during the conversation.

## Method
- Transcripts of 3, 9 and 14 minutes of candidate speech were built at 130 words per minute from three sample passages.
- Tokens were counted with `tiktoken` (`o200k_base`).
- Input is the rubric prompt plus the transcript. Output is a fixed 700-token JSON report.
- Two rubric sizes: a stub prompt (84 tokens, measured) and a full band-descriptor prompt (2,000 tokens, assumed).
- Price used: `gpt-4.1-mini` at $0.40 input and $1.60 output per 1M tokens (figures from third-party price listings; verify on the OpenAI pricing page).

## Results

| Candidate speech | Transcript tokens | Rubric tokens | Cost per assessment | Cost per 1,000 |
|---|---|---|---|---|
| 3 min | 446 | 84 | $0.0013 | $1.33 |
| 3 min | 446 | 2,000 | $0.0021 | $2.10 |
| 9 min | 1,338 | 84 | $0.0017 | $1.69 |
| 9 min | 1,338 | 2,000 | $0.0025 | $2.46 |
| 14 min | 2,092 | 84 | $0.0020 | $1.99 |
| 14 min | 2,092 | 2,000 | $0.0028 | $2.76 |

## Findings
- Assessing from text costs a fraction of a cent per test, roughly 100–300x less than the audio conversation itself.
- Transcript length matters little; the fixed output report and the rubric dominate.
- Doing assessment after the session from a stored transcript keeps expensive audio billing out of the scoring step and allows a batch or cached rubric prefix.

## Limitations
- This prices the model call only. It says nothing about scoring quality: a small model's agreement with human examiners was not tested.
- Pronunciation cannot be assessed from a transcript; it needs an audio-based method and cost, which is not covered here.
- Prices are from secondary listings and change; the 2,000-token rubric and 700-token report are planning assumptions.

## Reproduce
```
pip install tiktoken
python run.py
```
