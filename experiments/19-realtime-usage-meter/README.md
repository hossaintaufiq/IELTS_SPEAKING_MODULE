# 19 — Realtime usage meter

## Objective
Replace the cost estimates in experiments 06, 15 and 16 with real figures by metering every Realtime response: how many audio tokens were new, how many were served from the cache, how many were generated, and what that cost.

## Design
`usage_meter.py` consumes the JSON events a Realtime session emits. For each `response.done` event with a `usage` block it records:

- uncached audio input tokens (total audio input minus cached audio),
- cached audio input tokens,
- audio output tokens,
- text input and output tokens,

then computes the audio cost from a per-model price table and reports the **cache hit rate**. A response is counted once even if its event is delivered twice.

## Verification
Five unit tests use hand-built events and a hand-calculated expected cost:

- cached and uncached audio are separated correctly;
- cost equals the manual calculation;
- duplicate events are counted once;
- unrelated events and events without usage are ignored;
- totals and the cache hit rate accumulate across responses.

```
python -m unittest
```
All five pass. No network or API key is needed.

## How it is used
Attach one meter per session, call `feed(event)` for each message from the events channel, and store `summary()` when the session ends. Averaging these summaries over real tests gives the measured cost per test, the real cache hit rate and the real tokens-per-minute figures that experiment 06 assumes.

## Limitations
- The event shape (`response.usage.input_token_details.cached_tokens_details.audio_tokens`, and the output counterparts) follows OpenAI's Realtime documentation as understood at the time of writing. It has **not** been checked against a live session, because no funded API key was available. Compare against a real `response.done` event and adjust the field names if they differ.
- Only audio token cost is computed. Text token cost and input transcription cost are counted but not priced.
- The price table is a copy of the published rates and must be kept up to date.
