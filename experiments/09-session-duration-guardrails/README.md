# 09 — Session guardrails: duration, idle and quota caps

## Objective
Put a hard ceiling on per-user and total spend for a billed live-voice session, so a forgotten tab, a stuck connection or a misuse cannot run up unbounded cost.

## Design
`session_guard.py` is a small, framework-independent component:

| Control | Default | Effect |
|---|---|---|
| Maximum duration | 15 min | `sweep()` hangs up any session older than the limit |
| Idle timeout | 60 s | A session with no activity for the period is hung up |
| Per-user daily quota | 3 sessions | Further attempts are rejected with `daily_limit` |
| Total concurrency | 20 | Further attempts are rejected with `capacity` |

The hang-up action is injected as an async callable, so the same guard works with a WebRTC call hang-up request, a WebSocket close or any other mechanism. `touch()` is called whenever audio or an event is observed; `sweep()` is called periodically (for example every 5 s).

## Verification
Five unit tests run against a fake clock and a fake hang-up callable:

- a session is closed exactly at the maximum duration and not before;
- an idle session is closed while an active one is kept;
- the daily quota applies per user and per day;
- the concurrency cap frees up when a session is released;
- a rejected attempt does not use up the user's daily quota.

```
python -m unittest
```
All five pass. No network or API key is needed.

## Cost ceiling
With the defaults and the full model (examiner audio output $0.0768 per minute, the most expensive stream, see `gpt-live-voice-api/README.md`), the output cost of one capped session is bounded by about 15 × $0.0768 ≈ $1.15 before input and context costs, and a single user is bounded to 3 such sessions per day. Without a cap the bound is the length of time the connection is left open.

## Limitations
- Only the policy logic is tested. It has not been wired to a real hang-up call or run against a live session.
- State is in memory. A multi-process or multi-server deployment needs the counters in a shared store such as Redis.
- Client-side timers are not trusted: the server must own the clock.
